"""Loopback transport and shared-validation regressions; no real API keys."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from chat_protocol import endpoint_for, normalize_provider, ProviderValidationError, service_error
from chat_transport import ChatStream

app = QCoreApplication.instance() or QCoreApplication([])
KEY = 'synthetic-private-key-123'
REQUESTS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        case = payload['model']
        REQUESTS.append((self.path, self.headers.get('Authorization'), payload))
        code, kind = 200, 'text/event-stream'
        chunks = [b'data: {"choices":[{"delta":{"content":"OK"}}]}\r\n\r\n', b'data: [DONE]\n\n']
        if case in ('json', 'json_wrong_header'):
            kind = 'application/json' if case == 'json' else 'text/event-stream'
            chunks = [b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}']
        elif case == 'utf8':
            data = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'.encode()
            split = data.index('你'.encode())+1
            chunks = [data[:split], data[split:], b'data: [DONE]']
        elif case == 'multiline':
            chunks = [b': heartbeat\n\ndata: {"choices":\ndata: [{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n']
        elif case == 'bom_cr':
            chunks = [b'\xef', b'\xbb\xbf'+b''.join(chunks).replace(b'\r\n',b'\n').replace(b'\n',b'\r')]
        elif case in ('unauthorized', 'quota', 'model', 'sse_error'):
            code = {'unauthorized': 401, 'quota': 429, 'model': 200, 'sse_error': 200}[case]
            error_code = {'unauthorized': 'invalid_api_key', 'quota': 'insufficient_quota', 'model': 'model_not_found', 'sse_error': 'unsupported_value'}[case]
            body = json.dumps({'error': {'code': error_code, 'message': 'Test failure '+KEY}}).encode()
            kind = 'application/json'
            chunks = [body]
            if case == 'sse_error':
                kind, chunks = 'text/event-stream', [b'data: '+body+b'\n\n']
        elif case == 'empty':
            chunks = [b'data: [DONE]\n\n']
        elif case == 'html':
            code, kind, chunks = 502, 'text/html', [b'<html>secret '+KEY.encode()+b'</html>']
        elif case == 'redirect':
            code = 307
        elif case == 'malformed':
            chunks = [b'data: []\n\n']
        elif case == 'cancel':
            chunks *= 15
        elif case == 'unfinished':
            chunks = chunks[:1]
        self.send_response(code)
        self.send_header('Content-Type', kind)
        if case == 'redirect':
            self.send_header('Location', '/must-not-receive-key')
        self.send_header('Content-Length', str(sum(map(len, chunks))))
        self.end_headers()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(.015)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class ProtocolTests(unittest.TestCase):
    def test_endpoint_preserves_custom_prefix_and_full_endpoint(self):
        for url, expected in [('https://example.test/custom/v1', 'https://example.test/custom/v1/chat/completions'), ('https://example.test/chat/completions/', 'https://example.test/chat/completions'), ('http://localhost:11434', 'http://localhost:11434/chat/completions')]:
            self.assertEqual(endpoint_for({'base_url': url}), expected)
        self.assertEqual(endpoint_for({'base_url':'https://example.test/messages/v1/chat/completions'}),
                         'https://example.test/messages/v1/chat/completions')

    def test_invalid_or_other_protocol_urls_rejected_before_network(self):
        for url in ['', 'not a URL', 'https://example.test/v1/responses', 'https://example.test/v1/messages', 'https://example.test/models', 'http://example.test/v1', 'https://user:pass@example.test', 'https://example.test?api_key=private', 'https://example.test:bad/v1', 'https://example.test\\@else.test/v1']:
            with self.subTest(url=url), self.assertRaises(ProviderValidationError) as caught:
                endpoint_for({'base_url': url})
            self.assertEqual(caught.exception.field, 'base_url')

    def test_model_and_timeout_validation(self):
        for change in ({'model': ''}, {'model': 123}, {'timeout': 'x'}, {'timeout': float('nan')}, {'timeout': 0}):
            with self.assertRaises(ProviderValidationError):
                normalize_provider(dict(base_url='https://example.test/v1', model='test', timeout=30, **{} ) | change)

    def test_error_redaction_is_bounded_before_truncation(self):
        for key in [KEY, 'sk-synthetic-credential']:
            message = service_error(401, {'error': {'message': key + ' '*300 + key}}, key)
            self.assertNotIn(key, message)
            self.assertLess(len(message), 500)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/v1'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, case):
        stream = ChatStream()
        done, errors, delta = [], [], []
        stream.done.connect(done.append)
        stream.failed.connect(errors.append)
        stream.delta.connect(delta.append)
        stream.start(dict(base_url=self.url, model=case, timeout=5), KEY, [dict(role='user', content='synthetic')])
        deadline = time.perf_counter()+4
        while not (done or errors) and time.perf_counter()<deadline:
            QTest.qWait(10)
        self.assertTrue(done or errors, case)
        QTest.qWait(30)
        self.assertEqual(len(done)+len(errors), 1, 'one terminal signal')
        self.assertEqual(stream.key, '')
        stream.cancel()
        stream.deleteLater()
        return done, errors, delta

    def test_stream_json_utf8_multiline_and_eof(self):
        for case in ('normal', 'json', 'json_wrong_header', 'utf8', 'multiline'):
            with self.subTest(case=case):
                done, errors, delta = self.request(case)
                expected = '你好' if case == 'utf8' else 'OK'
                self.assertEqual(errors, [])
                self.assertEqual(done, [expected])
                self.assertEqual(''.join(delta), expected)
                self.assertEqual(REQUESTS[-1][0], '/v1/chat/completions')

    def test_bom_and_cr_separators(self):
        done, errors, delta = self.request('bom_cr')
        self.assertEqual(done,['OK']);self.assertFalse(errors);self.assertEqual(''.join(delta),'OK')

    def test_done_terminates_without_http_eof(self):
        stream=ChatStream();done=[];errors=[]
        stream.text='OK';stream.key=KEY;stream.completed=False;stream.event_lines=[];stream.event_size=0
        stream.timer.start(5000);stream.done.connect(done.append);stream.failed.connect(errors.append)
        stream.sse_line(b'data: [DONE]');stream.sse_line(b'')
        self.assertEqual(done,['OK']);self.assertFalse(errors);self.assertFalse(stream.timer.isActive());self.assertEqual(stream.key,'')
        stream.deleteLater()

    def test_cr_done_terminates_before_eof_and_split_crlf_is_single_separator(self):
        stream=ChatStream();done=[];errors=[]
        stream.text='';stream.key=KEY;stream.completed=False;stream.event_lines=[];stream.event_size=0;stream.skip_lf=False
        stream.done.connect(done.append);stream.failed.connect(errors.append)
        stream.buffer=b'data: {"choices":[{"delta":{"content":"OK"}}]}\r'
        stream.drain_sse();self.assertFalse(done)
        stream.buffer+=b'\n\r\ndata: [DONE]\r\r'
        stream.drain_sse();self.assertEqual(done,['OK']);self.assertFalse(errors)
        stream.deleteLater()

    def test_specific_service_errors_and_secret_redaction(self):
        for case, expected in [('unauthorized','密钥无效'), ('quota','额度不足'), ('model','模型不存在'), ('sse_error','不支持'), ('html','服务端暂时异常')]:
            with self.subTest(case=case):
                done, errors, _ = self.request(case)
                self.assertEqual(done, [])
                self.assertIn(expected, errors[0])
                self.assertNotIn(KEY, errors[0])
                self.assertNotIn('<html>', errors[0])

    def test_no_empty_or_malformed_success(self):
        for case in ('empty', 'malformed', 'unfinished'):
            done, errors, _ = self.request(case)
            self.assertFalse(done)
            self.assertTrue(errors)

    def test_redirect_never_forwards_credentials(self):
        before = len(REQUESTS)
        done, errors, _ = self.request('redirect')
        self.assertEqual(len(REQUESTS), before+1)
        self.assertFalse(done)
        self.assertIn('重定向', errors[0])

    def test_cancel_prevents_late_updates(self):
        stream = ChatStream();done=[];errors=[];delta=[]
        stream.done.connect(done.append);stream.failed.connect(errors.append);stream.delta.connect(delta.append)
        stream.start(dict(base_url=self.url,model='cancel',timeout=5), KEY, [])
        for _ in range(40):
            QTest.qWait(10)
            if delta:break
        stream.cancel();count=len(delta);QTest.qWait(350)
        self.assertFalse(done or errors);self.assertEqual(len(delta),count);self.assertEqual(stream.key,'')
        stream.deleteLater()


if __name__ == '__main__':
    unittest.main()
