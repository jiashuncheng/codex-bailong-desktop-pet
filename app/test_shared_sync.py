import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from token_sync_server import SyncStore
from shared_state import SharedWorker,remember_reads,pending_reads,acknowledge_reads,public

def h(s):return hashlib.sha256(s.encode()).hexdigest()

class SharedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SyncStore(Path(self.temp.name)/'test.db');self.a=self.store.add_device('old-Windows')['device_id'];self.b=self.store.add_device('old-Mac')['device_id'];self.now=time.time()
    def state(self,device,origin,stamp=None,state='working',turn='one',reads=None,ready=True):
        row=dict(session=h('chat'),turn=h(turn),updated=self.now if stamp is None else stamp,state=state,title='真实会话名',summary='已完成数据处理',display='正在处理任务')
        return self.store.shared.ingest(device,dict(origin=origin,sessions=[row],reads=reads or [],ready=ready,accounting_ready=ready),self.now)
    def test_origin_is_actual_device_and_duplicate_session_has_one_owner(self):
        self.state(self.a,'win');value=self.state(self.b,'mac',self.now+1)
        self.assertEqual(len(value['sessions']),1);self.assertEqual(value['sessions'][0]['origin'],'mac')
        with closing(self.store.connect()) as db:self.assertEqual(db.execute('SELECT name FROM devices WHERE id=?',(self.a,)).fetchone()[0],'win')
    def test_stale_running_snapshot_cannot_resurrect_terminal_turn(self):
        self.state(self.a,'win',state='complete');value=self.state(self.b,'mac',self.now-1)
        self.assertEqual(value['sessions'][0]['state'],'complete')
        value=self.state(self.b,'mac',self.now+1,turn='two');self.assertEqual(value['sessions'][0]['state'],'working')
    def test_ttl_is_offline_and_receipts_are_per_turn(self):
        self.state(self.a,'win',reads=[dict(session=h('chat'),turn=h('old'))])
        value=self.store.shared.snapshot(self.now+100)
        self.assertEqual(value['sessions'][0]['state'],'offline');self.assertEqual(value['reads'][0]['turn'],h('old'))
        value=self.state(self.a,'win',self.now+1,turn='new');self.assertEqual(value['sessions'][0]['state'],'working')
    def test_bad_batch_is_rejected_before_writes(self):
        row=dict(origin='win',sessions=[],reads=[dict(session=h('chat'),turn='not-a-hash')],ready=True,accounting_ready=True)
        with self.assertRaises(ValueError):self.store.shared.ingest(self.a,row)
        self.assertEqual(self.store.shared.snapshot()['devices'],[])
    def test_global_quota_and_usage_are_identical_to_all_clients(self):
        self.state(self.a,'win');self.state(self.b,'mac')
        start=self.now-1000;deadline=self.now+100000
        quota=[dict(stamp=start,deadline=deadline,remaining=90,plan='pro',boundary=None,reset_kind=''),dict(stamp=self.now-1,deadline=deadline,remaining=70,plan='pro',boundary=None,reset_kind='')]
        self.store.shared.quotas(self.a,quota);self.store.shared.quotas(self.b,quota)
        r=dict(session=h('chat'),total=600,stamp=self.now-100,model='gpt-6',input=500,output=100,cached=300,speed='standard',effort='high')
        self.store.shared.records(self.a,[r]);self.store.shared.records(self.b,[r])
        x=self.store.snapshot();y=self.store.snapshot()
        self.assertEqual(x['all_total'],600);self.assertEqual(x['week_cycle'],y['week_cycle']);self.assertEqual(x['quota_history']['cycles'][0]['estimated_total'],y['quota_history']['cycles'][0]['estimated_total'])
        self.assertEqual(x['quota_history']['cycles'][0]['estimated_total'],3000)
        self.assertEqual(x['quota_history']['cycles'][0]['change'],None)
    def test_late_checkpoint_rebuilds_usage_and_workload_without_double_count(self):
        r=lambda total,cached,stamp:dict(session=h('chat'),total=total,stamp=stamp,model='m',input=total-10,output=10,cached=cached,speed='standard',effort='high')
        self.store.shared.records(self.a,[r(200,70,self.now)])
        self.store.shared.records(self.b,[r(100,40,self.now-10)])
        self.assertEqual(self.store.snapshot()['all_total'],200)
    def test_public_metadata_redacts_private_paths_and_credentials(self):
        result=public('工作 /home/person/private/file.csv token=abc123 Bearer abcd-secret C:\\Users\\Me\\data.txt')
        self.assertNotIn('abc123',result);self.assertNotIn('private',result);self.assertNotIn('Me',result)
    def test_collector_sends_public_summary_after_completion_but_no_user_prompt(self):
        import json
        from shared_state import SessionCollector
        home=Path(self.temp.name)/'codex';path=home/'sessions/rollout-00000000-0000-0000-0000-000000000001.jsonl';path.parent.mkdir(parents=True)
        sid='00000000-0000-0000-0000-000000000001'
        rows=[dict(type='session_meta',payload=dict(id=sid,source='cli',originator='codex_cli_rs')),
          dict(type='event_msg',payload=dict(type='task_started',turn_id='one')),
          dict(type='event_msg',payload=dict(type='user_message',message='PRIVATE_USER_PROMPT')),
          dict(type='response_item',payload=dict(type='function_call_output',output='PRIVATE_TOOL_OUTPUT')),
          dict(type='response_item',payload=dict(type='message',role='assistant',phase='final',content=[dict(type='output_text',text='已整理公开结果')])),
          dict(type='event_msg',payload=dict(type='task_complete'))]
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows));(home/'session_index.jsonl').write_text(json.dumps(dict(id=sid,thread_name='真实名称'))+'\n')
        items,ready=SessionCollector(home).snapshot();self.assertTrue(ready);self.assertEqual(len(items),1)
        self.assertEqual(items[0]['summary'],'已整理公开结果');self.assertEqual(items[0]['title'],'真实名称')
        self.assertEqual(items[0]['thread'],sid);self.assertNotIn('PRIVATE',json.dumps(items))
    def test_display_identity_preserves_standard_update_contract(self):
        from version import VERSION,DISPLAY_VERSION,UPSTREAM_VERSION,CUSTOM_VERSION,material_compatibility
        from app_updates import version_tuple
        self.assertEqual(DISPLAY_VERSION,UPSTREAM_VERSION+'.'+CUSTOM_VERSION)
        self.assertEqual(version_tuple(VERSION),(0,18,0))
        self.assertEqual(material_compatibility(VERSION),UPSTREAM_VERSION)
    def test_outbox_is_monotonic_and_only_removes_exact_ack(self):
        state=Path(self.temp.name);remember_reads(state,[('session','one'),('session','two')])
        rows=pending_reads(state);acknowledge_reads(state,rows[:1]);self.assertEqual(len(pending_reads(state)),1)
    def test_global_quota_never_uses_local_denominator(self):
        from token_sync import with_local_quota
        global_value=dict(quota_scope='all',week_cycle=dict(used=200),quota_history=dict(cycles=[1]))
        self.assertEqual(with_local_quota(global_value,dict(week_cycle=dict(used=2)))['week_cycle']['used'],200)
        self.assertNotIn('week_cycle',with_local_quota({},dict(week_cycle=dict(used=2))))

if __name__=='__main__':unittest.main()
