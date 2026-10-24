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
            for _ in range(5):
                self.b._auto_cycle_conversations();seen.update(self.b.status_view.rows)
                self.assertEqual(len(self.b.status_view.rows),2)
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
    def test_interval_is_bounded_and_default_is_six(self):
        self.assertEqual(normalized({})['conversation_scroll_seconds'],6)
        for value in [float('nan'),None,'invalid']:
            self.assertEqual(normalized({'conversation_scroll_seconds':value})['conversation_scroll_seconds'],6)
        self.assertEqual(normalized({'conversation_scroll_seconds':0})['conversation_scroll_seconds'],2)

if __name__=='__main__':unittest.main()
