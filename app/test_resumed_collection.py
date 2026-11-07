"""Previously known rollouts must be rediscovered when a completed chat resumes."""
from pathlib import Path
from unittest.mock import patch
import tempfile,json,time,unittest
from shared_state import SessionCollector,hashed
from session_read_state import session_id

class ResumedCollectionTests(unittest.TestCase):
    def test_evicted_completed_chat_resumes_without_a_database_seed(self):
        with tempfile.TemporaryDirectory() as temp,patch('session_read_state.active_conversations',return_value=[]):
            home=Path(temp);folder=home/'sessions';folder.mkdir()
            sid='00000000-0000-0000-0000-000000000001'
            def write(path,sid,turn,complete=True):
                rows=[dict(type='session_meta',payload=dict(id=sid,source='cli')),
                      dict(type='event_msg',payload=dict(type='task_started',turn_id=turn))]
                if complete:rows.append(dict(type='event_msg',payload=dict(type='task_complete',turn_id=turn)))
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            target=folder/('rollout-'+sid+'.jsonl');write(target,sid,'old')
            c=SessionCollector(home);c.snapshot()
            for i in range(2,45):
                other=f'00000000-0000-0000-0000-{i:012d}';write(folder/('rollout-'+other+'.jsonl'),other,'fixture')
            for _ in range(3):c.tail.catalog.discover(force=True);c.snapshot()
            self.assertNotIn(target,c.tail.files)
            with target.open('a') as f:
                f.write(json.dumps(dict(type='event_msg',payload=dict(type='task_started',turn_id='resumed')))+'\n')
                f.write(json.dumps(dict(type='response_item',payload=dict(type='function_call_output',output='x'*600000)))+'\n')
            generation=c.tail.generation
            for _ in range(5):
                rows,ready=c.snapshot()
                found=next((r for r in rows if r['session']==hashed(sid) and r['turn']==hashed('resumed')),None)
                if found:break
            self.assertIsNotNone(found,'an existing dormant log was never reopened')
            self.assertTrue(ready);self.assertIn(found['state'],('thinking','working','responding'))
            self.assertEqual(c.tail.generation,generation,'append recovery must not require directory rediscovery')
            with target.open('a') as f:f.write(json.dumps(dict(type='event_msg',payload=dict(type='task_complete',turn_id='resumed')))+'\n')
            rows,_=c.snapshot();found=next(r for r in rows if r['session']==hashed(sid))
            self.assertEqual(found['state'],'complete')

if __name__=='__main__':unittest.main()
