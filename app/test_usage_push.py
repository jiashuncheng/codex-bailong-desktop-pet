import tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import patch
from token_sync_server import SyncStore
from shared_state import hashed,SharedWorker
from shared_rates import wire,local

class UsagePushTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=SyncStore(Path(self.tmp.name)/'server.db');self.a=self.store.add_device('win')['device_id'];self.b=self.store.add_device('mac')['device_id'];self.now=time.time()
    def state(self,device,origin,rates):
        return self.store.shared.ingest(device,dict(origin=origin,sessions=[],reads=[],ready=True,accounting_ready=True,rates=rates))
    def rate(self,sid='one',rate=20,stamp=None):
        stamp=self.now if stamp is None else stamp
        return dict(session=hashed(sid),sampled_at=stamp,rate=rate,interval=2,expires=stamp+12,name='task')
    def test_usage_revision_changes_once_per_new_counter_and_push_wakes(self):
        before=self.store.shared.snapshot();r=dict(session=hashed('one'),total=600,stamp=self.now,model='gpt-6',input=500,output=100,cached=300,speed='standard',effort='high')
        with patch.object(self.store.shared.events,'notify',wraps=self.store.shared.events.notify) as wake:
            self.store.shared.records(self.a,[r]);value=self.store.shared.snapshot()
            self.assertGreater(value['revision'],before['revision']);self.assertGreater(value['usage_revision'],before['usage_revision']);wake.assert_called_once()
            self.store.shared.records(self.b,[r]);self.assertEqual(self.store.shared.snapshot()['usage_revision'],value['usage_revision'])
        self.assertEqual(self.store.snapshot()['all_total'],600)
    def test_rates_merge_distinct_sessions_and_deduplicate_mirrors(self):
        self.state(self.a,'win',[self.rate()]);value=self.state(self.b,'mac',[self.rate(),self.rate('two',30)])
        self.assertEqual(value['live_output_rate']['rate'],50);self.assertEqual(value['live_output_rate']['sessions'],2)
        self.assertEqual(local(value['live_output_rate'])['rate'],50)
        self.assertIsNone(self.store.shared.snapshot(self.now+20)['live_output_rate']['rate'])
    def test_invalid_rates_are_atomic_and_disconnected_devices_do_not_count(self):
        with self.assertRaises(ValueError):self.state(self.a,'win',[self.rate(rate=float('nan'))])
        self.assertEqual(self.store.shared.snapshot()['devices'],[])
        self.state(self.a,'win',[self.rate()]);value=self.store.shared.ingest(self.a,dict(origin='win',sessions=[],ready=False,accounting_ready=False,rates=[]))
        self.assertIsNone(value['live_output_rate']['rate'])
    def test_replayed_rate_does_not_renew_expiry(self):
        row=self.rate();self.state(self.a,'win',[row]);self.state(self.a,'win',[row])
        value=self.store.shared.snapshot();self.assertEqual(value['live_output_rate']['details'][0]['expires_at'],row['expires'])
    def test_usage_events_do_not_request_upload_or_model_calls(self):
        events=[];worker=SharedWorker(Path(self.tmp.name)/'state',Path(self.tmp.name)/'home',threading.Event(),events.append)
        value=self.store.shared.snapshot()
        with patch('token_sync.read_config',return_value=dict(enabled=True,view='all')):
            worker.accept(value,stream_new=True)
            self.assertTrue(worker.usage_wake.is_set());worker.usage_wake.clear()
            worker.accept(value);self.assertFalse(worker.usage_wake.is_set())
    def test_wire_contains_hashed_identity_and_fixed_expiry(self):
        sample=dict(details=[dict(session='/private/log/one.jsonl',sampled_at=self.now,rate=20,interval=2,expires=time.monotonic()+12,name='task')])
        r=wire(sample)[0];self.assertEqual(len(r['session']),64);self.assertNotIn('/private',str(r));self.assertEqual(r['expires'],self.now+12)

    def test_custom_label_is_independent_of_origin_and_old_clients_preserve_it(self):
        from test_state_push import row
        p=dict(origin='win',label='我的电脑',sessions=[row()],ready=True,accounting_ready=True,rates=[self.rate()])
        value=self.store.shared.ingest(self.a,p)
        self.assertEqual(value['sessions'][0]['origin'],'win');self.assertEqual(value['sessions'][0]['source_label'],'我的电脑')
        self.assertEqual(value['live_output_rate']['details'][0]['source_label'],'我的电脑')
        p.pop('label');value=self.store.shared.ingest(self.a,p)
        self.assertEqual(value['sessions'][0]['source_label'],'我的电脑')

if __name__=='__main__':unittest.main()
