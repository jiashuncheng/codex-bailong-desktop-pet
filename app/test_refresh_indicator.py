"""Visible motion, result truthfulness and native snapshot handoffs."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent,QSize,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from refresh_indicator import RefreshButton,REFRESH_SECONDS,BRAKE_SECONDS,FEEDBACK_SECONDS,RESTORE_SECONDS
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])


class RefreshIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        self.button=RefreshButton(clock=lambda:self.now)
        self.button.setFixedSize(28,28);self.button.setIconSize(QSize(18,18))
        self.button.show();APP.processEvents()
    def tearDown(self):
        self.button.close();self.button.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def advance(self,seconds):
        self.now+=seconds;self.button._tick()
    def test_idle_has_no_timer_and_same_place_during_animation(self):
        self.assertFalse(self.button.timer.isActive());geometry=self.button.geometry()
        self.button.set_busy(True)
        self.assertTrue(self.button.timer.isActive())
        for _ in range(45):
            self.advance(.033);self.button.grab()
            self.assertEqual(self.button.geometry(),geometry)
    def test_repeat_busy_does_not_restart_and_disabled_ignores_click(self):
        self.button.set_busy(True);start=self.button.started
        self.advance(.35);pose=self.button.pose();events=[]
        self.button.clicked.connect(lambda:events.append(1))
        self.button.set_busy(True)
        self.assertEqual(self.button.started,start);self.assertEqual(self.button.pose(),pose)
        QTest.mouseClick(self.button,Qt.MouseButton.LeftButton)
        self.assertEqual(events,[])
    def test_finishing_preserves_first_pose_then_shows_success(self):
        self.button.set_busy(True);self.advance(.43);pose=self.button.pose()
        self.button.finish(True)
        self.assertEqual(self.button.pose(),pose)
        self.advance(BRAKE_SECONDS)
        self.assertEqual(self.button.pose()[2:],(0.,1.))
        self.assertTrue(self.button.result);self.assertTrue(self.button.isEnabled())
        self.advance(FEEDBACK_SECONDS+RESTORE_SECONDS+.01)
        self.assertIsNone(self.button.result);self.assertFalse(self.button.timer.isActive())
    def test_failure_is_distinct_and_never_success(self):
        self.button.set_busy(True);self.advance(.4);self.button.finish(False)
        self.advance(.4);self.assertIs(self.button.result,False)
        self.assertEqual(self.button.pose()[3],1.)
    def test_cancel_does_not_show_a_success_check(self):
        self.button.set_busy(True);self.advance(.4);self.button.set_busy(False)
        self.assertEqual(self.button.pose(),(0.,1.,1.,0.))
        self.assertIsNone(self.button.result);self.assertFalse(self.button.timer.isActive())
    def test_hidden_pauses_clock_and_timer(self):
        self.button.set_busy(True);self.advance(.42);pose=self.button.pose()
        self.button.hide();self.advance(10)
        self.assertEqual(self.button.pose(),pose);self.assertFalse(self.button.timer.isActive())
        self.button.show();self.assertEqual(self.button.pose(),pose)
        self.assertTrue(self.button.timer.isActive());self.advance(.1)
        self.assertNotEqual(self.button.pose(),pose)
    def test_result_arriving_under_snapshot_starts_from_frozen_pose(self):
        self.button.set_busy(True);self.advance(.3);pose=self.button.pose()
        self.button.freeze_motion();self.button.hide();self.advance(5)
        self.button.finish(False)
        self.assertEqual(self.button.pose(),pose)
        self.button.show();self.advance(.5)
        self.assertEqual(self.button.pose(),pose);self.assertFalse(self.button.timer.isActive())
        self.button.resume_motion();self.advance(.3)
        self.assertIs(self.button.result,False);self.assertEqual(self.button.pose()[3],1.)
    def test_new_refresh_during_result_reenables_rotation(self):
        self.button.set_busy(True);self.button.finish();self.advance(.5)
        self.button.set_busy(True)
        self.assertIsNone(self.button.result);self.assertTrue(self.button.busy)
        self.assertFalse(self.button.isEnabled());self.advance(.1)
        self.assertGreater(self.button.pose()[0],0)
    def test_speed_is_twenty_percent_faster_not_feedback_shorter(self):
        # The approved liquid task icon now has its own crossing choreography;
        # the existing refresh action retains its speed and readable feedback.
        self.assertAlmostEqual(2.4/REFRESH_SECONDS,1.2)
        self.assertGreaterEqual(FEEDBACK_SECONDS,1.)
    def test_real_bubble_navigation_freezes_and_reuses_button(self):
        with patch('compact_bubble.RefreshButton',side_effect=lambda parent=None:RefreshButton(parent,clock=lambda:self.now)):
            b=CompactBubble()
        b.show();APP.processEvents()
        try:
            button=b.refresh_button;b.set_refresh_busy(True);self.now+=.31;button._tick()
            start=button._motion_now();pose=button.pose()
            b.toggle_details();t=b.size_transition;t.animation.pause()
            self.now+=.8
            self.assertEqual(button._motion_now(),start);self.assertEqual(button.pose(),pose)
            self.assertFalse(button.timer.isActive())
            t.animation.resume();t.complete();t.release_landing();APP.processEvents()
            self.assertIs(b.refresh_button,button);self.assertEqual(button.pose(),pose)
            self.assertTrue(button.timer.isActive())
            self.now+=.1;button._tick();self.assertNotEqual(button.pose(),pose)
        finally:
            b.size_transition.cancel();b.close();b.deleteLater()
            APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main()
