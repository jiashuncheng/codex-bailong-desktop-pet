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
from bridge import Writer
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
        for obj in records: events.extend(reducer.apply('test',obj))
        self.assertTrue(any(e.get('state')=='working' for e in events))
        self.assertTrue(any(e.get('state')=='thinking' for e in events))
        self.assertEqual(sum(e['kind']=='complete' for e in events),1)
        self.assertTrue(any(e.get('title','').startswith('[gpu228]') for e in events))
        self.writer.apply(snap('working',turn='b'))
        self.writer.disconnect()
        for obj in self.records()[len(records):]: reducer.apply('test',obj)
        self.assertTrue(reducer.sessions['test'].done)
        self.assertEqual(reducer.sessions['test'].state,'interrupted')
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

if __name__=='__main__': unittest.main()
