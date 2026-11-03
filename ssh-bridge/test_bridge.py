import importlib.util
import json
import sys
import tempfile
import sqlite3
import unittest
from pathlib import Path

import os
BASE=Path(__file__).resolve().parent
SOURCE=Path(os.environ.get('BAILONG_SOURCE_ROOT',str(BASE.parent)))
sys.path.insert(0,str(SOURCE/'app'))
sys.path.insert(0,str(BASE))
from bridge import Writer, Bridge
from remote_codex_agent import Collector
from enhanced_core import ActivityReducer, RolloutTail

def snap(state='working',turn='a',**values):
    return {'available':True,'host':'test','sessions':[dict(id='server-id',title='远程测试任务',turn=turn,state=state,activity='execute',display='正在执行',summary='',**values)]}

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bridge-test-')
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'codex'
        self.writer=Writer(self.home,Path(self.temp.name)/'state','gpu228')

    def records(self):
        return [json.loads(line) for p in self.writer.root.glob('*.jsonl') for line in p.read_text(encoding='utf-8').splitlines()]

    def test_actual_pet_parser_lifecycle_and_disconnect(self):
        self.writer.apply(snap())
        self.writer.apply(snap('thinking'))
        self.writer.apply(snap('complete'))
        records=self.records();reducer=ActivityReducer();events=[]
        for obj in records: events.extend(reducer.apply(records[0]['payload']['id'],obj))
        self.assertTrue(any(e.get('state')=='working' for e in events))
        self.assertTrue(any(e.get('state')=='thinking' for e in events))
        self.assertEqual(sum(e['kind']=='complete' for e in events),1)
        self.assertTrue(any(e.get('title','').startswith('[gpu228]') for e in events))
        self.writer.apply(snap('working',turn='b'))
        self.writer.disconnect()
        for obj in self.records()[len(records):]: reducer.apply(records[0]['payload']['id'],obj)
        self.assertTrue(reducer.sessions[records[0]['payload']['id']].done)
        self.assertEqual(reducer.sessions[records[0]['payload']['id']].state,'offline')
        self.writer.apply(snap('working',turn='b'))
        self.assertEqual(len(list(self.writer.root.glob('*.jsonl'))),1)

    def test_no_old_completion_and_status_heartbeat(self):
        self.writer.apply(snap('complete'))
        self.assertFalse(list(self.writer.root.glob('*.jsonl')))
        self.writer.apply(snap())
        count=len(self.records());self.writer.apply(snap())
        self.assertEqual(len(self.records()),count)
        old=next(iter(self.writer.sessions.values()));old['emitted']-=16
        self.writer.apply(snap());self.assertGreater(len(self.records()),count)

    def test_archived_directory_discovery(self):
        self.writer.apply(snap())
        tail=RolloutTail(self.home);tail.poll()
        self.assertEqual(len(tail.files),1)
        self.writer.apply(snap('thinking'))
        events=tail.poll()
        self.assertTrue(any(e.get('state')=='thinking' for e in events))

    def test_no_hidden_reasoning_arguments_or_usage(self):
        collector=Collector(self.home)
        s=dict(state='working',turn='x',title='safe')
        collector.apply(s,{'type':'response_item','payload':{'type':'reasoning','content':'SECRET_REASONING'}})
        collector.apply(s,{'type':'response_item','payload':{'type':'function_call','name':'exec_command','arguments':'SECRET_ARGUMENTS'}})
        self.assertNotIn('SECRET',json.dumps(s))
        self.writer.apply(snap())
        self.assertFalse(any((r.get('payload') or {}).get('type')=='token_count' for r in self.records()))

    def test_restart_reuses_file_and_namespaced_identity(self):
        self.writer.apply(snap())
        self.writer.disconnect()
        other=Writer(self.home,Path(self.temp.name)/'state','gpu228')
        other.apply(snap())
        self.assertEqual(len(list(self.writer.root.glob('*.jsonl'))),1)
        self.assertNotEqual(self.records()[0]['payload']['id'],'server-id')

    def test_crash_recovery_does_not_leave_stale_work(self):
        self.writer.apply(snap())
        other=Writer(self.home,Path(self.temp.name)/'state','gpu228')
        other.apply(snap('complete'))
        self.assertEqual(self.records()[-1]['payload']['type'],'turn_aborted')

    def test_explicit_session_name_wins_and_rename_refreshes(self):
        self.home.mkdir()
        db=sqlite3.connect(self.home/'state_5.sqlite')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE threads (id TEXT,name TEXT,title TEXT)')
        db.execute('INSERT INTO threads VALUES (?,?,?)',('session','jsc-4','最初的问题内容'));db.commit()
        (self.home/'session_index.jsonl').write_text(json.dumps(dict(id='session',thread_name='旧索引名'))+'\n',encoding='utf-8')
        c=Collector(self.home)
        self.assertEqual(c.titles()['session'],'jsc-4')
        db.execute('UPDATE threads SET name=?',('jsc-renamed',));db.commit()
        self.assertEqual(c.titles()['session'],'jsc-renamed')

    def test_index_name_beats_prompt_when_name_column_missing(self):
        self.home.mkdir()
        db=sqlite3.connect(self.home/'state_5.sqlite')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE threads (id TEXT,title TEXT)')
        db.execute('INSERT INTO threads VALUES (?,?)',('session','最初的问题内容'));db.commit()
        index=self.home/'session_index.jsonl'
        index.write_text(json.dumps(dict(id='session',thread_name='old'))+'\n'+json.dumps(dict(id='session',thread_name='jsc-3'))+'\n',encoding='utf-8')
        self.assertEqual(Collector(self.home).titles()['session'],'jsc-3')

    def test_renamed_title_keeps_current_work_state(self):
        first=snap();self.writer.apply(first)
        renamed=snap();renamed['sessions'][0]['title']='jsc-4';self.writer.apply(renamed)
        reducer=ActivityReducer()
        for obj in self.records():reducer.apply('test',obj)
        self.assertEqual(reducer.sessions['test'].title,'[gpu228] jsc-4')
        self.assertEqual(reducer.sessions['test'].state,'working')

class ReconnectTests(unittest.TestCase):
    setUp=BridgeTests.setUp
    records=BridgeTests.records
    def reduce(self):
        reducer=ActivityReducer();events=[];records=self.records()
        sid=records[0]['payload']['id']
        for obj in records:events.extend(reducer.apply(sid,obj))
        return reducer,sid,events

    def test_offline_is_visible_without_activity_or_false_completion(self):
        from conversation_roster import ConversationRoster
        self.writer.apply(snap());self.writer.disconnect('heartbeat_timeout',1,.5)
        reducer,sid,events=self.reduce();last=events[-1]
        self.assertEqual(last['state'],'offline');self.assertEqual(last['active'],0)
        self.assertFalse(any(e['kind']=='complete' for e in events))
        self.assertEqual(reducer.sessions[sid].title,'[gpu228] 远程测试任务')
        self.assertIn('上次：正在运行命令',last['display'])
        roster=ConversationRoster()
        last.update(source_kind='ssh',source_label='gpu228');roster.observe(last)
        selected,extra=roster.selection([])
        self.assertEqual([v['session'] for v in selected],[sid])
        self.assertEqual(extra,0)
        status=json.loads((self.writer.state_dir/'status.json').read_text())
        self.assertEqual(status['reason'],'heartbeat_timeout')
        self.assertIsNotNone(status['last_success'])
        self.assertEqual(status['retry_in'],.5)
        count=len(self.records());self.writer.disconnect('ssh_exit',2,1)
        self.assertEqual(len(self.records()),count)

    def test_completion_during_outage_is_delivered_once(self):
        self.writer.apply(snap());self.writer.disconnect()
        self.writer.apply(snap('complete'));self.writer.apply(snap('complete'))
        reducer,sid,events=self.reduce()
        self.assertEqual(sum(e['kind']=='complete' for e in events),1)
        self.assertEqual(reducer.sessions[sid].state,'complete')

    def test_reconnect_same_turn_keeps_name_and_resumes(self):
        self.writer.apply(snap());self.writer.disconnect();self.writer.apply(snap())
        reducer,sid,events=self.reduce()
        self.assertEqual(reducer.sessions[sid].state,'working')
        self.assertEqual(reducer.sessions[sid].title,'[gpu228] 远程测试任务')
        self.assertEqual(events[-1]['active'],1)
        self.assertFalse(any(e['kind']=='complete' for e in events))
        self.assertEqual(len(list(self.writer.root.glob('*.jsonl'))),1)

    def test_missing_session_after_reconnect_retires_placeholder(self):
        self.writer.apply(snap());self.writer.disconnect()
        self.writer.apply(dict(available=True,host='test',sessions=[]))
        reducer,sid,events=self.reduce()
        self.assertEqual(reducer.sessions[sid].state,'interrupted')
        self.assertEqual(events[-1]['active'],0)

    def test_unseen_new_turn_completion_does_not_complete_old_turn(self):
        self.writer.apply(snap());self.writer.disconnect()
        self.writer.apply(snap('complete',turn='unseen-new-turn'))
        reducer,sid,events=self.reduce()
        self.assertFalse(any(e['kind']=='complete' for e in events))
        self.assertEqual(reducer.sessions[sid].state,'interrupted')

    def test_local_logs_cannot_invent_ssh_outage(self):
        reducer=ActivityReducer();reducer.apply('local',dict(type='event_msg',payload=dict(type='task_started')))
        self.assertEqual(reducer.apply('local',dict(type='event_msg',payload=dict(type='bridge_disconnected'))),[])
        self.assertFalse(reducer.sessions['local'].done)

class TransportTests(unittest.TestCase):
    def test_blocked_upload_is_inside_deadline(self):
        import threading,time
        from unittest.mock import patch,Mock
        import bridge
        release=threading.Event()
        process=Mock();process.poll.return_value=None
        def blocked_write(source):release.wait(2);raise BrokenPipeError()
        process.stdin.write.side_effect=blocked_write
        process.terminate.side_effect=release.set
        writer=Mock();runner=Bridge('test',Path('missing'),writer)
        started=time.monotonic()
        with patch.object(runner,'close_process',side_effect=process.terminate),patch.object(runner,'command',return_value=['fake']),patch.object(bridge.subprocess,'Popen',return_value=process),patch.object(bridge,'STARTUP_TIMEOUT',.06),patch.object(bridge,'POLL_SECONDS',.01):
            self.assertEqual(runner.run(once=True),2)
        self.assertLess(time.monotonic()-started,1)
        process.terminate.assert_called_once()
        writer.disconnect.assert_called_once_with(reason='startup_timeout')

    def test_real_pipe_stall_fast_retry_and_fresh_snapshot(self):
        import sys,time
        from unittest.mock import patch
        import bridge
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);marker=d/'attempt';writer=Writer(d/'home',d/'state','test')
            # First real child accepts upload then stalls; second publishes a
            # fresh snapshot. This exercises pipes, kill, retry and reconciliation.
            code="import sys,time,json;from pathlib import Path;sys.stdin.buffer.read();p=Path(sys.argv[1]);first=not p.exists();p.touch();time.sleep(3) if first else print(json.dumps(json.loads(sys.argv[2])),flush=True)"
            runner=Bridge('test',Path('missing'),writer);started=time.monotonic()
            with patch.object(runner,'command',return_value=[sys.executable,'-c',code,str(marker),json.dumps(dict(schema=1,**snap()))]),patch.object(bridge,'STARTUP_TIMEOUT',.5),patch.object(bridge,'POLL_SECONDS',.01),patch.object(bridge,'RETRY_DELAYS',(.02,)):
                self.assertEqual(self.run_until_snapshot(runner,writer),0)
            self.assertLess(time.monotonic()-started,1.5)
            self.assertTrue(json.loads((d/'state/status.json').read_text())['connected'])

    def run_until_snapshot(self,runner,writer):
        from unittest.mock import patch
        original=writer.apply
        import threading
        runner.stop_handle=threading.Event()
        timer=threading.Timer(3,runner.stop_handle.set);timer.start()
        # once=True would intentionally stop after the first failed connection.
        # End using a sentinel after applying the second connection's snapshot.
        class Done(Exception):pass
        def finish(value):original(value);raise Done()
        try:
            with patch.object(writer,'apply',side_effect=finish):runner.run()
        except Done:return 0
        finally:timer.cancel()
        self.fail('No fresh snapshot')

if __name__=='__main__': unittest.main()
