"""Cross-device replay, partial logs, offline retry and private-data boundaries."""
import itertools
from contextlib import closing
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from sync_ledger import SyncLedger
from token_sync_server import SyncStore
from token_sync import sync_once,apply_sync,atomic,SyncError,request


def record(sid='a',total=100,stamp=None):
    return dict(session=sid*64,total=total,stamp=stamp or time.time()-100,model='fixture-model',input=total*4//5,output=total-total*4//5)

def log(home,name='x',sid='same-session',totals=(100,300)):
    path=Path(home)/'sessions'/('rollout-'+name+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
    rows=[dict(type='session_meta',payload=dict(id=sid,base_instructions='PRIVATE_NEVER_UPLOAD')),dict(type='turn_context',payload=dict(model='fixture-model'))]
    for total in totals:
        r=record(total=total);rows.append(dict(timestamp=__import__('datetime').datetime.fromtimestamp(r['stamp'],__import__('datetime').timezone.utc).isoformat(),type='event_msg',payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=r['input'],output_tokens=r['output'])))))
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8');return path

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=SyncStore(self.root/'server.sqlite3');self.a=self.store.add_device('Windows');self.b=self.store.add_device('Mac')
    def test_partial_copies_late_history_and_retries_never_inflate(self):
        self.store.ingest(self.a['device_id'],[record(total=1000)])
        self.assertEqual(self.store.snapshot()['all_total'],1000)
        self.store.ingest(self.b['device_id'],[record(total=100),record(total=400),record(total=1000)])
        self.assertEqual(self.store.snapshot()['all_total'],1000)
        self.assertEqual(self.store.ingest(self.a['device_id'],[record(total=1000)])['inserted'],0)
        self.assertEqual(self.store.snapshot()['report']['sessions'],1)
    def test_same_numbers_in_different_sessions_are_independent(self):
        self.store.ingest(self.a['device_id'],[record('a'),record('b')])
        self.assertEqual(self.store.snapshot()['all_total'],200)
    def test_order_and_batch_boundaries_cannot_change_totals(self):
        for i,order in enumerate(itertools.permutations([100,300,1000])):
            store=SyncStore(self.root/(str(i)+'.sqlite3'));device=store.add_device('fixture')
            for n in order:store.ingest(device['device_id'],[record(total=n)])
            snapshot=store.snapshot();self.assertEqual(snapshot['all_total'],1000)
            self.assertEqual(sum(r['input'] for r in snapshot['report']['daily_models']),800)
    def test_entire_invalid_batch_is_rejected_without_partial_commit(self):
        for bad in [dict(record(),text='PRIVATE'),dict(record(),total=True),dict(record(),stamp=float('nan')),dict(record(),session='local/path')]:
            with self.assertRaises(ValueError):self.store.ingest(self.a['device_id'],[record(total=10),bad])
        self.assertEqual(self.store.snapshot()['all_total'],0)
    def test_pairing_is_single_use_and_authentication_revocable(self):
        self.assertEqual(self.store.authenticate(self.a['token']),self.a['device_id']);self.assertIsNone(self.store.authenticate('invalid'))
        invite=self.store.invite();new=self.store.enroll(invite['invite'],'Linux');self.assertEqual(self.store.authenticate(new['token']),new['device_id'])
        with self.assertRaises(ValueError):self.store.enroll(invite['invite'],'duplicate')
        with closing(self.store.connect()) as db,db:db.execute('DELETE FROM devices WHERE id=?',(new['device_id'],))
        self.assertIsNone(self.store.authenticate(new['token']))
    def test_unknown_messages_are_not_reported_as_zero_real_messages(self):
        s=self.store.snapshot();self.assertEqual(s['scope'],'all');self.assertIsNone(s['report']['messages']);self.assertFalse(s['report']['messages_available'])

class LedgerTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_copies_and_renames_use_session_identity_not_absolute_path(self):
        home=self.root/'home';first=log(home);log(home,'copied')
        ledger=SyncLedger(self.root/'ledger.sqlite3',home);ledger.scan(budget=5)
        self.assertEqual([r['total'] for r in ledger.batch('test')],[100,300])
        first.rename(first.with_name('rollout-renamed.jsonl'));ledger.scan(budget=5);self.assertEqual(len(ledger.batch('test')),2)
        with closing(ledger.connect()) as db:self.assertNotIn('PRIVATE_NEVER_UPLOAD','\n'.join(db.iterdump()))
    def test_truncation_and_rebuild_preserve_old_checkpoints_without_recount(self):
        home=self.root/'home';log(home);ledger=SyncLedger(self.root/'ledger.sqlite3',home);ledger.scan(budget=5)
        log(home,totals=(100,));ledger.scan(budget=5);self.assertEqual(len(ledger.batch('x')),2)
        log(home,totals=(100,300,500));ledger.scan(budget=5);self.assertEqual([r['total'] for r in ledger.batch('x')],[100,300,500])
    def test_cursor_only_advances_for_its_own_target(self):
        home=self.root/'home';log(home);ledger=SyncLedger(self.root/'ledger.sqlite3',home);ledger.scan(budget=5)
        rows=ledger.batch('one');ledger.acknowledge('one',rows[-1]['seq']);self.assertFalse(ledger.batch('one'));self.assertEqual(len(ledger.batch('two')),2)
    def test_unfinished_line_is_retried_after_completion(self):
        home=self.root/'home';path=log(home);raw=path.read_bytes();path.write_bytes(raw[:-1]);ledger=SyncLedger(self.root/'ledger.sqlite3',home);ledger.scan(budget=5)
        self.assertEqual(len(ledger.batch('x')),1);self.assertFalse(ledger.scan(budget=5)['more']);path.write_bytes(raw);ledger.scan(budget=5);self.assertEqual(len(ledger.batch('x')),2)
    def test_same_size_replacement_with_same_header_is_rescanned(self):
        home=self.root/'home';path=log(home,totals=(200,));ledger=SyncLedger(self.root/'ledger.sqlite3',home);ledger.scan(budget=5)
        old=path.stat().st_size;log(home,totals=(300,));self.assertEqual(path.stat().st_size,old)
        ledger.scan(budget=5);self.assertEqual([r['total'] for r in ledger.batch('x')],[200,300])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.state=self.root/'state';self.home=self.root/'home';log(self.home)
        self.store=SyncStore(self.root/'server.sqlite3');self.device=self.store.add_device('fixture')
        atomic(self.state/'token-sync.json',dict(enabled=True,url='https://example.test',device_id=self.device['device_id'],view='all'))
    def api(self,config,path,payload=None,token='',**kw):
        if path=='/v1/records':return self.store.ingest(self.device['device_id'],payload['records'])
        if path=='/v1/snapshot':return self.store.snapshot()
        raise AssertionError(path)
    def test_lost_reply_then_retry_is_idempotent(self):
        lost=[True]
        def api(*args,**kw):
            result=self.api(*args,**kw)
            if args[1]=='/v1/records' and lost[0]:lost[0]=False;raise SyncError('lost acknowledgement')
            return result
        with patch('token_sync.token_for',return_value='fixture-token'),patch('token_sync.request',side_effect=api):
            with self.assertRaises(SyncError):sync_once(self.state,self.home)
            self.assertEqual(sync_once(self.state,self.home)['all_total'],300)
            self.assertEqual(self.store.snapshot()['all_total'],300)
    def test_offline_keeps_last_aggregate_instead_of_dropping_to_local(self):
        with patch('token_sync.token_for',return_value='fixture-token'),patch('token_sync.request',side_effect=self.api):sync_once(self.state,self.home)
        with patch('token_sync.token_for',return_value='fixture-token'),patch('token_sync.request',side_effect=SyncError('offline')):
            result=apply_sync(dict(all_total=20),self.state,self.home)
        self.assertEqual(result['all_total'],300);self.assertTrue(result['sync_stale']);self.assertTrue(result['partial'])
    def test_offline_without_cache_labels_local_fallback(self):
        with patch('token_sync.token_for',return_value='fixture-token'),patch('token_sync.request',side_effect=SyncError('offline')):
            result=apply_sync(dict(all_total=20),self.state,self.home)
        self.assertEqual(result['all_total'],20);self.assertIn('本机',result['source']);self.assertFalse(result['sync_connected'])
    def test_cleartext_or_credential_urls_are_rejected(self):
        for url in ('http://example.test','https://user:secret@example.test','https://example.test/path'):
            with self.assertRaises(SyncError):request(dict(url=url),'/health')
    def test_local_view_still_uploads_but_returns_local_statistics(self):
        config=json.loads((self.state/'token-sync.json').read_text());config['view']='local';atomic(self.state/'token-sync.json',config)
        with patch('token_sync.token_for',return_value='fixture-token'),patch('token_sync.request',side_effect=self.api):result=apply_sync(dict(all_total=20),self.state,self.home)
        self.assertEqual(result['all_total'],20);self.assertEqual(self.store.snapshot()['all_total'],300)

class CloudUiTests(unittest.TestCase):
    def test_aggregate_card_and_overview_handle_unknown_message_counts(self):
        from PySide6.QtWidgets import QApplication
        from dashboard_cards import CardDeck
        from daily_report import OverviewStats,DailyReport
        from types import SimpleNamespace
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            cloud=SyncStore(Path(folder)/'cloud.sqlite3').snapshot()
            deck=CardDeck('tokens',cloud,None,False,False)
            stats=OverviewStats(cloud['report']);stats.resize(300,158)
            try:
                self.assertEqual(deck.tabs.buttons['tokens'].text(),'全端')
                self.assertFalse(stats.grab().isNull());self.assertFalse(deck.grab().isNull())
                note=DailyReport._note(SimpleNamespace(snapshot=cloud,page='overview'),cloud['report'])
                self.assertIn('多端',note);self.assertIn('消息数不汇总',note)
            finally:stats.close();deck.close();stats.deleteLater();deck.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
