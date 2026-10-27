"""Completion lifetimes, restart persistence and both visible status surfaces."""
import json,tempfile,unittest
from pathlib import Path
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from status_indicator import StatusIndicator

APP=QApplication.instance() or QApplication([])

class CompletionExpiryTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        self.icon=StatusIndicator(clock=lambda:self.now,wall_clock=lambda:self.now)
    def tearDown(self):
        self.icon.close();self.icon.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_each_notice_expires_independently_without_clearing_running_work(self):
        icon=self.icon
        icon.notify_complete(dict(session='a',turn='old'))
        self.now=110.;icon.notify_complete(dict(session='b',turn='new'))
        icon.observe(dict(state='working',active=1))
        self.now=129.9;self.assertFalse(icon.expire_completed())
        self.now=130.;self.assertTrue(icon.expire_completed())
        self.assertEqual(icon.unread,[('b','new')]);self.assertTrue(icon.is_busy())
        self.now=140.;self.assertTrue(icon.expire_completed())
        self.assertFalse(icon.unread);self.assertEqual(icon.visual(),'busy')
        self.now=10000.;self.assertFalse(icon.expire_completed());self.assertTrue(icon.is_busy())
    def test_restart_keeps_original_deadline_and_old_completion_cannot_return(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'notices.json';self.icon.set_store(path,Path(temp))
            event=dict(session='a',turn='done');self.icon.notify_complete(event)
            self.now=120.;restored=StatusIndicator(wall_clock=lambda:self.now)
            try:
                restored.set_store(path,Path(temp))
                self.assertEqual(restored.completion_expiries[('a','done')],130.)
                self.assertFalse(restored.notify_complete(event))
                self.now=130.;self.assertTrue(restored.expire_completed())
                self.assertFalse(json.loads(path.read_text())['unread'])
                restored.observe(dict(state='complete',active=0))
                self.assertEqual(restored.visual(),'idle')
                self.assertFalse(restored.notify_complete(event))
                self.assertTrue(restored.notify_complete(dict(session='a',turn='next')))
            finally:restored.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_legacy_notices_get_one_grace_period_persisted_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'notices.json';path.write_text(json.dumps(dict(unread=[['a','old']],seen=[])))
            self.icon.set_store(path,Path(temp));self.assertTrue(self.icon.unread)
            self.now=120.;restored=StatusIndicator(wall_clock=lambda:self.now)
            try:
                restored.set_store(path,Path(temp));self.assertEqual(restored.completion_expiries[('a','old')],130.)
                self.now=131.;self.assertTrue(restored.expire_completed());self.assertFalse(restored.unread)
            finally:restored.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_real_timer_expires_while_indicator_hidden(self):
        icon=StatusIndicator();icon.COMPLETION_SECONDS=.04
        try:
            icon.notify_complete(dict(session='a',turn='done'))
            self.assertTrue(icon.isHidden());self.assertTrue(icon.completion_timer.isActive())
            QTest.qWait(100)
            self.assertFalse(icon.unread);self.assertFalse(icon.completion_timer.isActive())
            self.assertEqual(icon.visual(),'idle')
        finally:icon.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_manual_confirmation_does_not_leave_an_endless_complete_summary(self):
        self.icon.notify_complete(dict(session='a',turn='done'))
        self.icon.acknowledge();self.assertEqual(self.icon.visual(),'complete')
        self.now+=2.;self.icon.observe(dict(state='complete',active=0))
        self.assertEqual(self.icon.visual(),'idle');self.assertFalse(self.icon.completion_timer.isActive())
    def test_both_surfaces_remove_done_and_keep_execution_even_with_rotation_disabled(self):
        for mode in ('auto','mini'):
            with self.subTest(mode=mode):
                b=CompactBubble();icon=b.status_indicator;icon.wall_clock=lambda:self.now
                try:
                    self.now=100.;b.conversation_auto_scroll=False
                    icon.notify_complete(dict(session='done',turn='old'))
                    b.roster.observe(dict(session='done',kind='complete',turn='old',title='已结束的测试'))
                    b.roster.observe(dict(session='running',state='working',turn='new',title='持续执行的测试'))
                    icon.observe(dict(state='working',active=1))
                    b.set_mode(mode);b.size_transition.complete();b.show();b.refresh_status();APP.processEvents()
                    self.assertEqual(len(b.roster.selection(icon.unread)[0]),2)
                    self.now=130.;icon.expire_completed();APP.processEvents()
                    chosen,_=b.roster.selection(icon.unread)
                    self.assertEqual([(v['session'],v['state']) for v in chosen],[('running','working')])
                    if mode=='mini':self.assertNotIn('完成',b.island.text.text());self.assertIn('执行',b.island.text.text())
                    else:self.assertEqual(list(b.status_view.rows),['running'])
                    self.now=86400.;icon.expire_completed();b.refresh_status()
                    self.assertEqual(b.roster.selection(icon.unread)[0][0]['session'],'running')
                finally:b.close();b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_new_turn_in_same_session_is_not_masked_by_old_completion(self):
        from conversation_roster import ConversationRoster
        roster=ConversationRoster();roster.observe(dict(session='a',kind='complete',turn='old'))
        roster.observe(dict(session='a',state='working',turn='new'))
        chosen,_=roster.selection([('a','old')])
        self.assertEqual([(v['session'],v['state']) for v in chosen],[('a','working')])
    def test_restored_completion_without_roster_returns_to_idle_in_capsule(self):
        b=CompactBubble();icon=b.status_indicator;icon.wall_clock=lambda:self.now
        try:
            icon.notify_complete(dict(session='restored',turn='old'))
            b.set_mode('mini');b.size_transition.complete();b.show();APP.processEvents()
            self.assertIn('完成',b.island.text.text())
            self.now=130.;icon.expire_completed();APP.processEvents()
            self.assertEqual(b.island.text.text(),'待命')
        finally:b.close();b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

if __name__=='__main__':unittest.main()
