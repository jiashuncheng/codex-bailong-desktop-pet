import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from session_read_state import conversation_names

SID='11111111-1111-4111-8111-111111111111'


class LocalConversationNameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.home=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def index(self,name,mode='w'):
        with (self.home/'session_index.jsonl').open(mode,encoding='utf-8') as stream:
            stream.write(json.dumps(dict(id=SID,thread_name=name),ensure_ascii=False)+'\n')

    def catalog(self,rows):
        folder=self.home/'sqlite';folder.mkdir()
        with closing(sqlite3.connect(folder/'codex.db')) as db:
            db.execute('CREATE TABLE local_thread_catalog(host_id TEXT,thread_id TEXT,display_title TEXT)')
            db.executemany('INSERT INTO local_thread_catalog VALUES(?,?,?)',rows)
            db.commit()

    def test_new_chat_missing_from_old_database_uses_its_real_name(self):
        self.index('重启桌宠')
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'重启桌宠'})
        self.assertFalse((self.home/'state_5.sqlite').exists())
        self.assertFalse((self.home/'sqlite').exists())

    def test_catalog_covers_new_chat_and_wins_over_older_index(self):
        self.index('旧名称')
        self.catalog([('local',SID,'重启桌宠'),('remote-control:server',SID,'其他服务器的会话')])
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'重启桌宠'})

    def test_remote_catalog_entry_is_not_a_local_name(self):
        self.catalog([('remote-control:server',SID,'其他服务器的会话')])
        self.assertEqual(conversation_names(self.home,[SID]),{})

    def test_index_rename_replaces_stale_old_database_name(self):
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db:
            db.execute('CREATE TABLE threads(id TEXT,name TEXT,title TEXT)')
            db.execute('INSERT INTO threads VALUES(?,?,?)',(SID,'旧名称','# AGENTS.md instructions'))
            db.commit()
        self.index('新会话名')
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'新会话名'})
        self.index('再次改名','a')
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'再次改名'})

    def test_partial_index_append_does_not_replace_valid_name(self):
        self.index('已有名称')
        path=self.home/'session_index.jsonl'
        record=json.dumps(dict(id=SID,thread_name='新名称'),ensure_ascii=False)
        with path.open('a',encoding='utf-8') as stream:stream.write(record[:20])
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'已有名称'})
        with path.open('a',encoding='utf-8') as stream:stream.write(record[20:]+'\n')
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'新名称'})

    def test_malformed_rows_and_prompt_text_are_not_names(self):
        (self.home/'session_index.jsonl').write_text('bad json\n'+json.dumps(dict(id=SID,text='import os; secret code'))+'\n[]\n',encoding='utf-8')
        self.assertEqual(conversation_names(self.home,[SID]),{})

    def test_removed_index_does_not_return_cached_name(self):
        self.index('已有名称')
        self.assertEqual(conversation_names(self.home,[SID]),{SID:'已有名称'})
        (self.home/'session_index.jsonl').unlink()
        self.assertEqual(conversation_names(self.home,[SID]),{})


if __name__=='__main__':unittest.main()
