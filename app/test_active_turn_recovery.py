import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from enhanced_core import ActivityReducer,Session
from session_read_state import restore_active_turns
from shared_state import SessionCollector

SID='00000000-0000-0000-0000-000000000001'
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.home=Path(self.temp.name)
        self.reducer=ActivityReducer();self.seed=dict(session=SID,turn='active-turn',title='fixture')
    def test_long_log_tail_missing_start_still_uploads_active_turn(self):
        path=self.home/'sessions'/('rollout-'+SID+'.jsonl');path.parent.mkdir()
        rows=[dict(type='session_meta',payload=dict(id=SID,source='cli')),
              dict(type='event_msg',payload=dict(type='task_started',turn_id='active-turn')),
              dict(type='response_item',payload=dict(type='function_call_output',output='x'*600000)),
              dict(type='response_item',payload=dict(type='function_call',name='functions.exec',arguments='{}'))]
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        (self.home/'session_index.jsonl').write_text(json.dumps(dict(id=SID,thread_name='fixture'))+'\n')
        with patch('session_read_state.active_conversations',return_value=[self.seed]):
            collector=SessionCollector(self.home);items,ready=collector.snapshot();again,_=collector.snapshot()
        self.assertTrue(ready);self.assertEqual(len(items),1);self.assertEqual(items[0]['state'],'working')
        self.assertEqual(items[0]['thread'],SID);self.assertEqual(items,again)
    def test_default_idle_with_missing_turn_becomes_active_but_explicit_terminal_does_not_reopen(self):
        self.reducer.sessions[SID]=Session(provenance_known=True)
        self.assertEqual(len(restore_active_turns(self.home,self.reducer,[self.seed])),1)
        s=self.reducer.sessions[SID];self.assertFalse(s.done);self.assertEqual(s.turn,'active-turn')
        self.reducer.terminate(SID,'completed','active-turn')
        self.assertEqual(restore_active_turns(self.home,self.reducer,[self.seed]),[]);self.assertTrue(s.done)
    def test_database_ordinal_allows_new_turn_but_rejects_stale_seed(self):
        with closing(sqlite3.connect(self.home/'thread_history_1.sqlite')) as db,db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,rollout_ordinal INTEGER)')
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?)',[(SID,'old',1),(SID,'active-turn',2),(SID,'newer',3)])
        self.reducer.sessions[SID]=Session(turn='old',closed_turn='old',done=True)
        restore_active_turns(self.home,self.reducer,[self.seed]);self.assertEqual(self.reducer.sessions[SID].turn,'active-turn')
        self.reducer.sessions[SID]=Session(turn='newer',done=False)
        self.assertEqual(restore_active_turns(self.home,self.reducer,[self.seed]),[]);self.assertEqual(self.reducer.sessions[SID].turn,'newer')
    def test_subagents_and_explicit_runtime_idle_are_preserved(self):
        self.reducer.sessions[SID]=Session(source_subagent=True)
        self.assertEqual(restore_active_turns(self.home,self.reducer,[self.seed]),[])
        self.reducer.sessions[SID]=Session(turn='active-turn',done=False,runtime_active=False,runtime_turn='active-turn')
        self.assertEqual(restore_active_turns(self.home,self.reducer,[self.seed]),[])
        self.assertFalse(self.reducer.sessions[SID].runtime_active)

if __name__=='__main__':unittest.main()
