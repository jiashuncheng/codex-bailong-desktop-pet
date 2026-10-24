"""Event-driven glyph transitions, rapid reversals and frozen native handoffs."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import math,unittest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from status_indicator import StatusIndicator
from status_motion import GlyphMotion,MORPH_SECONDS

APP=QApplication.instance() or QApplication([])

class MorphTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        self.icon=StatusIndicator(clock=lambda:self.now)
        self.icon.show();APP.processEvents()
    def tearDown(self):
        self.icon.close();self.icon.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def frame(self):return self.icon.motion.sample(self.icon._motion_now())
    def advance(self,seconds):
        self.now+=seconds;self.icon._tick();return self.frame()
    def busy(self):
        self.icon.observe(dict(state='working',active=1))
        self.advance(.8)
    def assertSame(self,a,b):
        for left,right in zip(a,b):
            for x,y in zip(left,right):self.assertAlmostEqual(x,y,places=8)
    def test_busy_completion_keeps_first_frame_and_shakes_after_forming(self):
        self.busy();old=self.frame()
        self.icon.notify_complete(dict(session='a',turn='1'))
        self.assertSame(old,self.frame());self.assertFalse(self.icon.shaking())
        middle=self.advance(.24);self.assertNotEqual(old,middle)
        self.assertFalse(self.icon.shaking())
        self.advance(.25);self.assertTrue(self.icon.shaking())
        self.advance(1.3)
        self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())
        self.assertTrue(self.icon.unread)
    def test_confirm_during_morph_continues_from_current_shape(self):
        self.busy();self.icon.notify_complete(dict(session='a',turn='1'))
        self.advance(.18);old=self.frame();self.icon.acknowledge()
        self.assertSame(old,self.frame())
        self.advance(.5)
        self.assertEqual(self.icon.visual(),'complete')
        self.assertEqual(self.frame()[2].opacity,1)
        self.assertEqual(self.frame()[2].mint,1)
        self.assertLess(self.frame()[0].angle,0);self.assertGreater(self.frame()[1].angle,0)
    def test_checkmark_has_time_to_show_before_other_task_resumes(self):
        self.icon.observe(dict(state='working',active=2));self.advance(.8)
        self.icon.notify_complete(dict(session='a',turn='1'));self.advance(2.)
        self.icon.acknowledge();self.advance(.5)
        self.assertEqual(self.icon.visual(),'complete')
        old=self.advance(.49)
        self.advance(.02)
        self.assertEqual(self.icon.visual(),'busy')
        # Retarget begins at the settled checkmark, rather than a new orbit.
        self.assertSame(old,self.frame())
        self.advance(.5);self.assertTrue(self.icon.timer.isActive())
    def test_wait_count_survives_other_busy_session_and_resumes(self):
        self.busy();old=self.frame()
        self.icon.observe(dict(state='working',active=2,waiting=1))
        self.assertEqual(self.icon.visual(),'waiting');self.assertSame(old,self.frame())
        self.advance(.6);dots=self.frame()
        self.assertTrue(all(p.y==8 and p.hole==0 for p in dots))
        radius=dots[0].radius;self.advance(.8)
        self.assertNotEqual(self.frame()[0].radius,radius)
        old=self.frame();self.icon.observe(dict(state='working',active=2,waiting=0))
        self.assertSame(old,self.frame());self.assertEqual(self.icon.visual(),'busy')
    def test_waiting_and_paused_do_not_clear_unread(self):
        self.icon.notify_complete(dict(session='a',turn='1'));self.advance(2.)
        for event in (dict(state='waiting',active=1,waiting=1),dict(state='interrupted',active=0,waiting=0)):
            self.icon.observe(event)
            self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())
    def test_interrupted_becomes_static_pause_then_resumes(self):
        self.busy();old=self.frame()
        self.icon.observe(dict(state='interrupted',active=0))
        self.assertEqual(self.icon.visual(),'paused');self.assertSame(old,self.frame())
        self.advance(.5);parts=self.frame()
        self.assertEqual(parts[0].length,parts[1].length)
        self.assertEqual(parts[2].opacity,1);self.assertEqual(parts[2].mint,1)
        self.assertFalse(self.icon.timer.isActive())
        self.icon.observe(dict(state='working',active=1))
        self.assertSame(parts,self.frame());self.assertTrue(self.icon.timer.isActive())
    def test_interrupting_one_task_keeps_other_task_running(self):
        self.icon.observe(dict(state='interrupted',active=1))
        self.assertEqual(self.icon.visual(),'busy')
    def test_repeated_semantic_updates_do_not_restart_motion(self):
        self.busy();self.icon.observe(dict(state='waiting',active=1,waiting=1))
        start=self.icon.motion.started;since=self.icon.motion.since
        for _ in range(12):
            self.advance(.03);self.icon.observe(dict(state='working',active=2,waiting=1))
        self.assertEqual(self.icon.motion.started,start);self.assertEqual(self.icon.motion.since,since)
    def test_short_hide_show_retains_snapshot_pose(self):
        self.busy()
        self.icon.observe(dict(state='waiting',active=1,waiting=1));self.advance(.12)
        old=self.frame();self.icon.hide();self.now+=.4
        self.assertFalse(self.icon.timer.isActive())
        self.assertSame(old,self.frame())
        self.icon.show();self.assertSame(old,self.frame())
        self.assertTrue(self.icon.timer.isActive());self.advance(.2)
        self.assertNotEqual(old,self.frame())
    def test_hidden_new_state_is_settled_and_old_attention_does_not_replay(self):
        self.busy();self.icon.hide()
        self.icon.notify_complete(dict(session='a',turn='1'))
        self.assertFalse(self.icon.timer.isActive())
        self.now+=4;self.icon.show()
        self.assertEqual(self.icon.visual(),'attention')
        self.assertFalse(self.icon.timer.isActive());self.assertFalse(self.icon.shaking())
    def test_rapid_retargeting_is_continuous_and_bounded(self):
        motion=GlyphMotion();now=0.
        for state in ('busy','waiting','busy','attention','complete','paused','busy','warning')*4:
            old=motion.sample(now);motion.set_state(state,now)
            self.assertSame(old,motion.sample(now))
            for _ in range(5):
                now+=.01
                for part in motion.sample(now):
                    self.assertTrue(all(math.isfinite(v) for v in part))
                    a=math.radians(part.angle)
                    dx=abs(math.sin(a))*part.length+part.radius
                    dy=abs(math.cos(a))*part.length+part.radius
                    self.assertGreaterEqual(part.x-dx,.39);self.assertLessEqual(part.x+dx,15.61)
                    self.assertGreaterEqual(part.y-dy,.39);self.assertLessEqual(part.y+dy,15.61)
                    self.assertGreaterEqual(part.opacity,0);self.assertLessEqual(part.opacity,1)
                    for channel in (part.mint,part.bond,part.warm):
                        self.assertGreaterEqual(channel,0);self.assertLessEqual(channel,1)
    def test_ticks_do_not_emit_semantic_updates_or_change_size(self):
        self.busy();changes=[];self.icon.changed.connect(lambda:changes.append(1))
        geometry=self.icon.geometry()
        for _ in range(60):self.advance(.033);self.icon.grab()
        self.assertEqual(changes,[]);self.assertEqual(self.icon.geometry(),geometry)

if __name__=='__main__':unittest.main()
