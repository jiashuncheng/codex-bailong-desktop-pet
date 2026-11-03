"""Real bubble handoffs must preserve the shared glyph's geometry and clock."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from status_indicator import StatusIndicator
from surface_morph import SurfaceState

APP=QApplication.instance() or QApplication([])

def alpha(pixmap):
    image=pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return bytes(image.constBits())[3::4]

class StatusHandoffTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        with patch('compact_bubble.StatusIndicator',side_effect=lambda parent:StatusIndicator(parent,clock=lambda:self.now)):
            self.b=CompactBubble()
        self.b.move(10000,10000);self.b.show();APP.processEvents()
        self.icon=self.b.status_indicator
    def tearDown(self):
        self.b.size_transition.complete();self.b.size_transition.release_landing()
        self.b.close();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def working(self):
        self.icon.observe(dict(state='working',active=1,waiting=0))
        self.icon.motion.settle();self.now+=.3;self.icon._tick()
    def land(self):
        t=self.b.size_transition
        t.animation.resume();t.complete()
        if t.landing.image is not None:t.release_landing()
    def test_both_directions_freeze_before_first_capture_through_native_landing(self):
        for mode in ('mini','auto'):
            self.working();icon=self.icon;before=icon._motion_now();captured=[]
            original=SurfaceState.capture.__func__
            def capture(cls,bubble,origin=None,frame=None,content=None):
                captured.append(icon._motion_now())
                self.now+=.075  # Expensive layout/render must not advance the glyph.
                result=original(cls,bubble,origin,frame=frame,content=content)
                captured.append(icon._motion_now())
                return result
            with patch.object(SurfaceState,'capture',classmethod(capture)):
                self.b.set_mode(mode)
            t=self.b.size_transition;t.animation.pause()
            self.assertEqual(captured,[before]*4)
            self.assertEqual(alpha(t.morph.start.icon),alpha(t.morph.end.icon))
            self.assertFalse(icon.timer.isActive())
            self.now+=.4
            self.assertEqual(icon._motion_now(),before)
            t.animation.resume();t.complete()
            if t.landing.image is not None:
                self.now+=.034
                self.assertEqual(icon._motion_now(),before)
                self.assertFalse(icon.timer.isActive())
                t.release_landing()
            self.assertNotIn('surface',icon._motion_holds)
            self.assertTrue(icon.timer.isActive())
            self.now+=.1
            self.assertAlmostEqual(icon._motion_now(),before+.1)
    def test_waiting_update_while_covered_morphs_only_after_both_handoffs(self):
        for mode in ('mini','auto'):
            self.working();icon=self.icon
            source=icon.motion.sample(icon._motion_now())
            self.b.set_mode(mode);t=self.b.size_transition;t.animation.pause()
            self.assertFalse(icon.isVisible())
            self.now+=.15;icon.observe(dict(state='waiting',active=1,waiting=1))
            self.assertEqual(icon.visual(),'waiting')
            self.assertIsNotNone(icon.motion.started)
            self.assertEqual(icon.motion.sample(icon._motion_now()),source)
            self.now+=.5
            self.assertEqual(icon.motion.sample(icon._motion_now()),source)
            self.land()
            self.assertEqual(icon.motion.sample(icon._motion_now()),source)
            self.assertTrue(icon.timer.isActive())
            self.now+=.2;icon._tick()
            self.assertNotEqual(icon.motion.sample(icon._motion_now()),source)
            self.now+=.4;icon._tick()
            self.assertEqual([round(p.y,6) for p in icon.motion.sample(icon._motion_now())],[8,8,8])
    def test_old_completion_hidden_then_new_completion_restarts_wiggle(self):
        icon=self.icon;icon.notify_complete(dict(session='a',turn='one'))
        self.b.hide();self.now+=3;self.b.show();APP.processEvents()
        self.assertFalse(icon.timer.isActive())
        icon.notify_complete(dict(session='b',turn='two'))
        self.assertTrue(icon.timer.isActive())
        self.assertTrue(icon.motion.shaking(icon._motion_now()))
        self.now+=1.5;icon._tick()
        self.assertFalse(icon.timer.isActive())
        self.assertEqual(icon.visual(),'attention')
        self.assertEqual(len(icon.unread),2)
    def test_new_completion_during_navigation_restarts_wiggle_after_landing(self):
        icon=self.icon;icon.notify_complete(dict(session='a',turn='one'))
        self.now+=3;icon._tick();self.assertFalse(icon.timer.isActive())
        self.b.set_mode('mini');t=self.b.size_transition;t.animation.pause()
        self.assertFalse(icon.isVisible())
        icon.notify_complete(dict(session='b',turn='two'))
        self.assertFalse(icon.timer.isActive())
        self.now+=.6;self.land()
        self.assertTrue(icon.timer.isActive())
        self.assertTrue(icon.motion.shaking(icon._motion_now()))
        self.now+=1.5;icon._tick()
        self.assertFalse(icon.timer.isActive())
    def test_no_resize_and_cancelled_preparation_release_only_surface_hold(self):
        self.working();icon=self.icon;t=self.b.size_transition
        for end in (t.commit,t.cancel):
            t.begin();frozen=icon._motion_now();self.now+=.5
            self.assertFalse(icon.timer.isActive())
            self.assertEqual(icon._motion_now(),frozen)
            end()
            self.assertNotIn('surface',icon._motion_holds)
            self.assertTrue(icon.timer.isActive())
        t.begin();self.b.hide()
        self.assertNotIn('surface',icon._motion_holds)
        self.assertIn('hidden',icon._motion_holds)
        self.assertFalse(icon.timer.isActive())
        self.now+=2;self.b.show()
        self.assertFalse(icon._motion_holds)
        self.assertTrue(icon.timer.isActive())

if __name__=='__main__':unittest.main()
