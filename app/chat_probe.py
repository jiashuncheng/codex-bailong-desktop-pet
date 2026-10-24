"""Isolated configure-save-reopen-send acceptance, usable in the frozen app."""
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def run(output):
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtNetwork import QSslSocket
    from chat_config import load_chat_config, save_chat_config, load_provider_key
    from chat_window import ProviderDialog, ChatWindow
    from version import VERSION
    app = QApplication.instance() or QApplication([])
    from typography import install_ui_font
    install_ui_font(app)
    app.setQuitOnLastWindowClosed(False)
    requested = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requested.append(self.path)
            assert self.headers['Authorization'] == 'Bearer isolated-chat-probe-key'
            case = body['model']
            if case == 'stream':
                kind, code, data = 'text/event-stream', 200, 'data: {"choices":[{"delta":{"content":"隔离验证成功"}}]}\n\ndata: [DONE]\n\n'
            elif case == 'json':
                kind, code, data = 'application/json', 200, '{"choices":[{"message":{"content":"JSON验证成功"},"finish_reason":"stop"}]}'
            else:
                kind, code, data = 'application/json', 401, '{"error":{"code":"invalid_api_key","message":"Invalid key isolated-chat-probe-key"}}'
            raw = data.encode('utf-8')
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    proof = dict(version=VERSION,isolated=True,realAccountUsed=False,paidEndpointUsed=False)
    try:
        with tempfile.TemporaryDirectory(prefix='bailong-chat-proof-') as folder:
            root=Path(folder)
            dialog=ProviderDialog(root,embedded=True)
            dialog.fields['name'].setText('隔离服务')
            dialog.fields['base_url'].setText(f'http://127.0.0.1:{server.server_port}/v1')
            dialog.fields['model'].setText('stream')
            dialog.fields['key'].setText('isolated-chat-probe-key')
            dialog.save()
            config=load_chat_config(root);provider=config['providers'][0]
            assert load_provider_key(root,provider)=='isolated-chat-probe-key'
            assert b'isolated-chat-probe-key' not in (root/'credentials.dpapi.json').read_bytes()
            proof['editorSaveAndEncryptedKey']=True
            dialog.deleteLater()
            reopened=ProviderDialog(root,embedded=True)
            assert reopened.fields['model'].text()=='stream'
            assert not reopened.fields['key'].text()
            proof['reopenPreservesConfiguration']=True
            reopened.resize(530,650);reopened.show();app.processEvents()
            reopened.grab().save(str(Path(output).with_suffix('.png')))
            reopened.hide();reopened.deleteLater()
            pet=QWidget();pet.settings={};pet.manifest={}
            chat=ChatWindow(pet,root,embedded=True)
            for case in ('stream','json','auth'):
                config=load_chat_config(root);config['providers'][0]['model']=case
                save_chat_config(root,config,provider['id'])
                chat.input.setPlainText('隔离测试消息');chat.send()
                deadline=time.perf_counter()+6
                while chat.busy and time.perf_counter()<deadline:
                    app.processEvents();time.sleep(.005)
                assert not chat.busy,case
                if case=='auth':
                    assert '密钥无效' in chat.status.text()
                    assert 'isolated-chat-probe-key' not in chat.status.text()
                    assert chat.session['messages'][-1]['role']=='user'
                else:
                    assert chat.session['messages'][-1]['role']=='assistant'
                    assert '验证成功' in chat.session['messages'][-1]['content']
                proof[case+'CompleteFlow']=True
            assert requested==['/v1/chat/completions']*3
            chat.shutdown();chat.deleteLater();pet.deleteLater();app.processEvents()
            proof['qtTlsAvailable']=QSslSocket.supportsSsl()
            proof['qtTlsBackend']=QSslSocket.activeBackend()
            assert proof['qtTlsAvailable']
        proof['passed']=True
    except Exception as error:
        proof.update(passed=False,errorType=type(error).__name__)
    finally:
        server.shutdown();server.server_close()
    Path(output).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if proof['passed'] else 1
