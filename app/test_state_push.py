"""Real loopback streams plus client ordering, deduplication and live-state tests."""
import hashlib,http.client,json,tempfile,threading,time,unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from token_sync_server import SyncStore,Handler
from shared_state import SharedWorker,hashed
from enhanced_core import Session

def row(state='working',turn='one'):
    return dict(session=hashed('chat'),turn=hashed(turn),updated=time.time(),state=state,title='fixture',summary='public progress',display='working')
def payload(rows):return dict(origin='win',sessions=rows,reads=[],ready=True,accounting_ready=True)

class PushServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SyncStore(Path(self.temp.name)/'usage.db');self.device=self.store.add_device('win')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True;self.server.store=self.store
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.clients=[]
    def tearDown(self):
        for connection,response in self.clients:response.close();connection.close()
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,body=None,token=None):
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        conn.request('POST' if body is not None else 'GET',path,body=json.dumps(body) if body is not None else None,headers={'Authorization':'Bearer '+(token or self.device['token'])})
        response=conn.getresponse();value=json.loads(response.read());conn.close();return response.status,value
    def stream(self):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        connection.request('GET','/v3/events',headers={'Authorization':'Bearer '+self.device['token']})
        response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.getheader('X-Accel-Buffering'),'no')
        self.clients.append((connection,response));return response
    def event(self,response):
        while True:
            line=response.readline()
            if line.startswith(b'data:'):return json.loads(line[5:])
            if not line:raise AssertionError('stream ended')
    def test_one_commit_pushes_to_two_connected_clients_without_polling(self):
        a,b=self.stream(),self.stream();initial=self.event(a);self.event(b)
        before=time.monotonic();status,result=self.request('/v2/state',payload([row()]))
        x,y=self.event(a),self.event(b)
        self.assertEqual(status,200);self.assertLess(time.monotonic()-before,2)
        self.assertEqual(x['revision'],y['revision']);self.assertGreater(x['revision'],initial['revision'])
        self.assertEqual(x['sessions'],y['sessions']);self.assertEqual(x['sessions'][0]['origin'],'win')
    def test_duplicate_and_heartbeat_do_not_create_new_state_revision(self):
        p=payload([row()]);self.store.shared.ingest(self.device['device_id'],p)
        first=self.store.shared.snapshot()['revision'];self.store.shared.ingest(self.device['device_id'],p)
        self.assertEqual(self.store.shared.snapshot()['revision'],first)
        p['reads']=[dict(session=hashed('chat'),turn=hashed('one'))]
        second=self.store.shared.ingest(self.device['device_id'],p)['revision'];self.assertGreater(second,first)
        self.assertEqual(self.store.shared.ingest(self.device['device_id'],p)['revision'],second)

    def test_token_commit_notifies_both_streams_without_session_change(self):
        a,b=self.stream(),self.stream();initial=self.event(a);self.event(b)
        record=dict(session=hashed('usage-only'),total=120,stamp=time.time(),model='gpt-6',input=100,output=20)
        started=time.monotonic();status,_=self.request('/v2/records',dict(records=[record]));x,y=self.event(a),self.event(b)
        self.assertEqual(status,200);self.assertLess(time.monotonic()-started,2)
        self.assertGreater(x['usage_revision'],initial['usage_revision']);self.assertEqual(x['usage_revision'],y['usage_revision'])
        self.assertEqual(x['sessions'],[]);self.assertEqual(self.store.snapshot()['all_total'],120)
    def test_invalid_batch_is_atomic_and_stream_requires_auth(self):
        status,_=self.request('/v3/events',token='wrong');self.assertEqual(status,401)
        bad=payload([dict(row(),unexpected='private')]);status,_=self.request('/v2/state',bad)
        self.assertEqual(status,400);self.assertEqual(self.store.shared.snapshot()['revision'],0)
    def test_offline_presence_and_restart_are_replayable(self):
        now=time.time();self.store.shared.ingest(self.device['device_id'],payload([row()]),now=now)
        first=self.store.shared.snapshot();self.store.shared.events.expire(now+100)
        after=self.store.shared.snapshot(now+100);self.assertGreater(after['revision'],first['revision'])
        self.assertEqual(after['sessions'][0]['state'],'offline')
        restored=SyncStore(self.store.path).shared.snapshot();self.assertEqual(restored['revision'],after['revision']);self.assertNotEqual(restored['stream_id'],after['stream_id'])

class PushClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.events=[];self.worker=SharedWorker(self.root,self.root/'codex',threading.Event(),self.events.append)
    def test_out_of_order_replies_and_old_server_epoch_cannot_overwrite_new_snapshot(self):
        def value(epoch,rev,state):return dict(schema=2,revision=rev,stream_id=epoch,sessions=[dict(row(state),origin='mac',stale=False,device_id='mac')],reads=[])
        self.assertTrue(self.worker.accept(value('one',2,'complete'),stream_new=True))
        self.assertFalse(self.worker.accept(value('one',1,'working')))
        self.assertTrue(self.worker.accept(value('two',0,'working'),stream_new=True))
        self.assertFalse(self.worker.accept(value('one',99,'complete')))
        self.assertEqual(self.worker.epoch,'two');self.assertEqual(self.worker.revision,0)
    def test_live_ipc_idle_is_uploaded_and_no_change_sends_no_network_request(self):
        path=self.root/'log.jsonl';path.write_text('fixture')
        sid='00000000-0000-0000-0000-000000000001';session=Session(state='working',turn='one',done=False,provenance_known=True,source_kind='local',display='working')
        tail=SimpleNamespace(reducer=SimpleNamespace(sessions={sid:session}),files={path:dict(sid=sid)},health=dict(state='available'))
        self.worker.update_local(tail,{sid:'actual name'});self.assertTrue(self.worker.wake.is_set())
        store=SyncStore(self.root/'server.db');device=store.add_device('win');calls=[]
        def api(config,path,payload=None,*args,**kwargs):
            calls.append(path);return store.shared.ingest(device['device_id'],payload)
        with patch('token_sync.read_config',return_value=dict(enabled=True,origin='win')),patch('token_sync.token_for',return_value='fixture'),patch('token_sync.request',side_effect=api):
            self.worker.push_connected=True;self.worker.once();self.worker.once()
            self.assertEqual(calls,['/v2/state'])
            session.runtime_active=False;session.runtime_turn='one';self.worker.update_local(tail,{sid:'actual name'});self.worker.once()
        self.assertEqual(store.shared.snapshot()['sessions'][0]['state'],'idle')
        self.assertTrue(any(e.get('session')==sid and e.get('shared') for e in self.events))
    def test_disabled_sync_neither_uploads_nor_stays_connected(self):
        self.worker.connected=True;self.worker.push_connected=True
        with patch('token_sync.read_config',return_value=dict(enabled=False)),patch('token_sync.request') as network:
            self.assertIsNone(self.worker.once());network.assert_not_called()
        self.assertFalse(self.worker.connected);self.assertFalse(self.worker.push_connected)

    def test_stream_decoder_keeps_credentials_in_header_and_accepts_heartbeats(self):
        import io,email.message
        from token_sync import state_events
        response=io.BytesIO(b': keepalive\n\nevent: state\nid: 7\ndata: {"schema":2,"sessions":[],"revision":7}\n\n')
        response.headers=email.message.Message();response.headers['Content-Type']='text/event-stream'
        opener=SimpleNamespace(open=lambda request,timeout:response)
        captured=[]
        def open_request(request,timeout):captured.append(request);return response
        opener.open=open_request
        with patch('token_sync.connection',return_value=('https://example.test',opener)):
            generator=state_events({},'private-device-token',lambda:False)
            self.assertEqual(next(generator)['revision'],7);generator.close()
        self.assertNotIn('private-device-token',captured[0].full_url)
        self.assertEqual(captured[0].get_header('Authorization'),'Bearer private-device-token')

    def test_token_only_append_does_not_change_public_state_timestamp(self):
        path=self.root/'log.jsonl';path.write_text('one');sid='00000000-0000-0000-0000-000000000001'
        tail=SimpleNamespace(reducer=SimpleNamespace(sessions={sid:Session(state='working',turn='one',done=False,provenance_known=True)}),files={path:dict(sid=sid)},health=dict(state='available'))
        self.worker.update_local(tail,{sid:'name'});first=self.worker.local_snapshot()[0]
        path.write_text('more token data');self.worker.update_local(tail,{sid:'name'})
        self.assertEqual(first,self.worker.local_snapshot()[0])

if __name__=='__main__':unittest.main()
