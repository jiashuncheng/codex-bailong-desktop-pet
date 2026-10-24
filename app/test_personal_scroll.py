import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QPointF,Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from desktop_core import normalized

APP=QApplication.instance() or QApplication([])

class ScrollTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents()
        for i in range(5):
            self.b.roster.observe(dict(session=f'11111111-2222-4333-8444-{i:012d}',title=f'测试会话 {i+1}',state='working',display='正在运行测试'))
        self.b.redraw();APP.processEvents()
    def tearDown(self):
        self.b.close();self.b.deleteLater();APP.processEvents()
    def test_rotation_covers_all_five_with_two_rows(self):
        seen=set(self.b.status_view.rows)
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            changed_slots=[]
            for _ in range(5):
                before=list(self.b.status_view.rows);widgets=dict(self.b.status_view.rows)
                self.b.status_view.animation.setCurrentTime(300)
                self.b._auto_cycle_conversations();after=list(self.b.status_view.rows);seen.update(after)
                self.assertEqual(len(after),2)
                changed=[i for i in range(2) if before[i]!=after[i]]
                self.assertEqual(len(changed),1);changed_slots.extend(changed)
                stable=after[1-changed[0]]
                self.assertIs(self.b.status_view.rows[stable],widgets[stable])
                from PySide6.QtCore import QAbstractAnimation
                self.assertNotEqual(self.b.status_view.animation.state(),QAbstractAnimation.State.Running)
                self.b.status_view.animation.setCurrentTime(300)
                self.assertEqual(widgets[stable].y(),(1-changed[0])*self.b.status_view.line_height)
            self.assertEqual(changed_slots,[0,1,0,1,0])
        self.assertEqual(len(seen),5)
    def test_timer_rotates_and_hover_and_disabled_pause(self):
        first=list(self.b.status_view.rows)
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            self.b.conversation_timer.setInterval(60)
            for _ in range(20):
                QTest.qWait(15)
                if self.b.roster.page:break
        self.b.conversation_timer.stop()
        self.assertNotEqual(first,list(self.b.status_view.rows))
        page=self.b.roster.page
        with patch('PySide6.QtGui.QCursor.pos',return_value=self.b.status_view.mapToGlobal(QPoint(5,5))):self.b._auto_cycle_conversations()
        self.assertEqual(page,self.b.roster.page)
        self.b.conversation_auto_scroll=False;self.b._auto_cycle_conversations();self.assertEqual(page,self.b.roster.page)
    def test_wheel_on_child_moves_forward_and_back(self):
        before=list(self.b.status_view.rows)
        def wheel(delta):
            row=next(iter(self.b.status_view.rows.values()))
            event=QWheelEvent(QPointF(4,4),QPointF(row.mapToGlobal(QPoint(4,4))),QPoint(),QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            APP.sendEvent(row,event)
        wheel(-120);self.assertNotEqual(before,list(self.b.status_view.rows))
        wheel(120);self.assertEqual(before,list(self.b.status_view.rows))
    def test_new_waiting_still_takes_priority(self):
        self.b.cycle_conversations()
        sid='11111111-2222-4333-8444-000000000004'
        self.b.roster.observe(dict(session=sid,state='waiting',display='等待操作'))
        self.b.refresh_status();self.assertIn(sid,self.b.status_view.rows)
    def test_background_refreshes_and_repeated_waiting_do_not_reset_rotation(self):
        sid=list(self.b.roster.items)[-1]
        self.b.roster.observe(dict(session=sid,state='waiting',display='等待操作'))
        self.b.refresh_status()
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            for _ in range(2):self.b._auto_cycle_conversations()
        before=list(self.b.status_view.rows);page=self.b.roster.page
        self.b.roster.observe(dict(session=sid,state='waiting',display='等待操作'))
        self.b.refresh_status();self.b.refresh_status()
        self.assertEqual(list(self.b.status_view.rows),before);self.assertEqual(self.b.roster.page,page)

    def test_removed_session_replaces_only_its_slot_and_new_unread_is_prioritized(self):
        from conversation_roster import ConversationRoster
        r=ConversationRoster()
        for sid in 'abcde':r.observe(dict(session=sid,state='working',title=sid))
        r.rotate_one([]);before=[v['session'] for v in r.selection([])[0]]
        r.observe(dict(session=before[0],state='idle'))
        after=[v['session'] for v in r.selection([])[0]]
        self.assertEqual(after[1],before[1]);self.assertNotIn(before[0],after);self.assertEqual(len(set(after)),2)
        r.observe(dict(session='new',kind='complete'))
        self.assertIn('new',[v['session'] for v in r.selection([('new','turn')])[0]])

    def test_two_or_fewer_sessions_do_not_rotate(self):
        from conversation_roster import ConversationRoster
        r=ConversationRoster()
        self.assertFalse(r.rotate_one([]))
        for sid in 'ab':
            r.observe(dict(session=sid,state='working'));before=r.selection([])
            self.assertFalse(r.rotate_one([]));self.assertEqual(r.selection([]),before)

    def test_interval_is_bounded_and_default_is_three(self):
        self.assertEqual(normalized({})['conversation_scroll_seconds'],3)
        for value in [float('nan'),None,'invalid']:
            self.assertEqual(normalized({'conversation_scroll_seconds':value})['conversation_scroll_seconds'],3)
        self.assertEqual(normalized({'conversation_scroll_seconds':0})['conversation_scroll_seconds'],2)
        migrated=normalized({'conversation_scroll_seconds':6})
        self.assertEqual(migrated['conversation_scroll_seconds'],3)
        self.assertEqual(normalized({'conversation_scroll_seconds':4})['conversation_scroll_seconds'],4)
        migrated['conversation_scroll_seconds']=6
        self.assertEqual(normalized(migrated)['conversation_scroll_seconds'],6)

if __name__=='__main__':unittest.main()
