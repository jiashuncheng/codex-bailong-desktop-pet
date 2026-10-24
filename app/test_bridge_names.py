import json,sqlite3,tempfile,unittest
from pathlib import Path
from session_read_state import conversation_names

A='11111111-2222-4333-8444-000000000001'
B='11111111-2222-4333-8444-000000000002'

class BridgeNamesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def log(self,sid=A,host='gpu228',title='jsc-2',origin='BailongSSHBridge'):
        folder=self.home/'archived_sessions'/('bailong-remote-'+host);folder.mkdir(parents=True,exist_ok=True)
        path=folder/('rollout-remote-'+sid+'.jsonl')
        header=dict(type='session_meta',payload=dict(id=sid,originator=origin,remote_host=host))
        path.write_text(json.dumps(header)+'\n',encoding='utf-8')
        self.title(path,host,title)
        return path
    def title(self,path,host,title):
        with path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(type='response_item',payload=dict(type='message',role='user',content=[dict(type='input_text',text=f'[{host}] {title}')])) )+'\n')
    def test_multiple_hosts_and_ids_are_not_hardcoded(self):
        self.log();self.log(B,'other-server','科研计算')
        self.assertEqual(conversation_names(self.home,[A,B]),{A:'[gpu228] jsc-2',B:'[other-server] 科研计算'})
        self.assertFalse((self.home/'state_5.sqlite').exists())
    def test_completed_unread_after_new_lookup_has_name(self):
        p=self.log()
        with p.open('a') as f:f.write(json.dumps(dict(type='event_msg',payload=dict(type='task_complete')))+'\n')
        self.assertEqual(conversation_names(self.home,[A])[A],'[gpu228] jsc-2')
    def test_title_rename_and_long_log_tail(self):
        p=self.log()
        with p.open('a') as f:f.write(('{}\n')*60000)
        self.title(p,'gpu228','new name')
        self.assertEqual(conversation_names(self.home,[A])[A],'[gpu228] new name')
    def test_truncated_last_line_preserves_valid_title(self):
        p=self.log()
        with p.open('a') as f:f.write('{"type":')
        self.assertEqual(conversation_names(self.home,[A])[A],'[gpu228] jsc-2')
    def test_rename_in_middle_survives_restart_and_new_status(self):
        from session_read_state import _bridge_name_cache
        p=self.log()
        self.title(p,'gpu228','later name')
        with p.open('a') as f:f.write(('{}\n')*100000)
        _bridge_name_cache.clear()
        self.assertEqual(conversation_names(self.home,[A])[A],'[gpu228] later name')
        self.title(p,'gpu228','newest name')
        self.assertEqual(conversation_names(self.home,[A])[A],'[gpu228] newest name')
    def test_local_custom_name_still_wins(self):
        self.log()
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id TEXT,name TEXT,title TEXT)')
            db.execute('INSERT INTO threads VALUES(?,?,?)',(A,'自定义名称','旧标题'))
        db.close()
        self.assertEqual(conversation_names(self.home,[A])[A],'自定义名称')
    def test_untrusted_header_does_not_supply_a_title(self):
        self.log(origin='someone-else')
        self.assertEqual(conversation_names(self.home,[A]),{})
    def test_missing_or_malformed_logs_do_not_break_lookup(self):
        p=self.log();p.write_text('broken\n',encoding='utf-8')
        self.assertEqual(conversation_names(self.home,[A,B]),{})

if __name__=='__main__':unittest.main()
