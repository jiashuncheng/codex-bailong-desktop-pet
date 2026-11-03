import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,copy
from PySide6.QtCore import QRect,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import sample

APP=QApplication.instance() or QApplication([])

class ReportTransitionTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(100,550);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample())
    def tearDown(self):
        self.r.animation.stop();self.b.close();self.b.deleteLater();APP.processEvents()
    def finish(self):self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def assert_frozen_frame(self):
        r=self.r;rect=QRect(r.geometry());heights=[]
        for ms in range(0,r.animation.duration(),16):
            r.animation.setCurrentTime(ms)
            self.assertEqual(r.geometry(),rect);self.assertTrue(r.surface.isHidden())
            visible=r.visible_height();heights.append(visible)
            if r.fraction>0:self.assertTrue(r.rect().contains(r.visual_rect().toAlignedRect()))
            image=r.grab().toImage();ratio=image.devicePixelRatio()
            self.assertEqual(image.pixelColor(0,0).alpha(),0)
            if r.fraction>.09:
                point=r.visual_rect().center()
                self.assertGreaterEqual(image.pixelColor(round(point.x()*ratio),round(point.y()*ratio)).alpha(),250)
        self.assertTrue(all(a<=b for a,b in zip(heights,heights[1:])), 'opening does not recoil')
        self.assertLessEqual(max(heights),r.surface.height());self.assertGreaterEqual(heights[-1],r.surface.height()-1)
    def test_open_and_close_change_only_painted_clip_not_native_geometry(self):
        self.r.open();self.assert_frozen_frame();self.finish()
        self.assertFalse(self.r._animating);self.assertIsNone(self.r._frame);self.assertTrue(self.r.surface.isVisible())
        self.assertFalse(self.r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertFalse(self.r.windowHandle().flags()&Qt.WindowType.WindowTransparentForInput)
        rect=QRect(self.r.geometry());self.r.dismiss();heights=[]
        for ms in range(0,self.r.animation.duration(),8):
            self.r.animation.setCurrentTime(ms)
            self.assertEqual(self.r.geometry(),rect);self.assertTrue(self.r.surface.isHidden())
            heights.append(self.r.visible_height())
        tail=heights[6:]
        self.assertTrue(all(b<=a for a,b in zip(tail,tail[1:])), 'closing tail never grows back')
        self.finish();self.assertFalse(self.r.isVisible());self.assertIsNone(self.r._frame)
    def test_closing_report_keeps_content_until_card_is_small(self):
        self.r.open();self.finish();self.r.dismiss()
        self.r.animation.setCurrentTime(self.r.animation.duration()//2)
        image=self.r.grab().toImage();rect=self.r.visual_rect().toAlignedRect()
        dark=sum(image.pixelColor(x,y).red()<150 for y in range(max(0,rect.top()+4),min(image.height(),rect.bottom()-4),2)
                 for x in range(max(0,rect.left()+4),min(image.width(),rect.right()-4),2))
        self.assertGreater(dark,20,'report content vanished before its closing card shrank')
    def test_dismiss_rebound_can_be_reopened_without_a_flash_or_jump(self):
        r=self.r;r.open();self.finish();r.dismiss();r.animation.setCurrentTime(round(r.animation.duration()*.75))
        fraction=r.fraction;frame=r._frame.cacheKey();rect=QRect(r.geometry())
        r.open();self.assertAlmostEqual(r.fraction,fraction);self.assertEqual(r._frame.cacheKey(),frame)
        self.assertEqual(r.geometry(),rect);self.finish();self.assertTrue(r.surface.isVisible());self.assertEqual(r.fraction,1.)
    def test_refresh_during_animation_keeps_one_frame_then_applies_latest(self):
        self.r.open();self.r.animation.setCurrentTime(90);key=self.r._frame.cacheKey();rect=QRect(self.r.geometry())
        latest=copy.deepcopy(sample());latest['report']['messages']=456
        self.r.set_snapshot(latest);self.r.set_page('models')
        self.assertEqual(self.r._frame.cacheKey(),key);self.assertEqual(self.r.geometry(),rect)
        self.assertTrue(self.r._pending_rebuild);self.finish()
        self.assertEqual(self.r.report['messages'],456);self.assertEqual(self.r.page,'models');self.assertTrue(self.r.surface.isVisible())
    def test_rapid_reversal_preserves_progress_frame_and_window(self):
        r=self.r;r.open();r.animation.setCurrentTime(90);fraction=r.fraction;frame=r._frame.cacheKey();rect=QRect(r.geometry())
        r.dismiss();self.assertAlmostEqual(r.fraction,fraction);r.animation.setCurrentTime(10)
        fraction=r.fraction;r.open();self.assertAlmostEqual(r.fraction,fraction)
        self.assertEqual(r._frame.cacheKey(),frame);self.assertEqual(r.geometry(),rect)
        self.finish();self.assertTrue(r.isVisible());self.assertEqual(r.fraction,1.)
    def test_hiding_owner_cancels_reveal_and_releases_image(self):
        self.r.open();self.r.animation.setCurrentTime(100);self.b.hide()
        self.assertFalse(self.r.isVisible());self.assertFalse(self.r.requested);self.assertIsNone(self.r._frame)
        self.assertFalse(self.r._animating)
    def test_terminal_frame_merges_into_owner_and_hidden_buffer_is_clear(self):
        r=self.r;r.open();self.finish();r.dismiss()
        r.animation.setCurrentTime(r.animation.duration()-1)
        rect=r.visual_rect()
        self.assertLess(rect.width(),3);self.assertLess(rect.height(),.1)
        self.assertAlmostEqual(rect.bottom()+r.y(),self.b.y()+1,delta=.01)
        self.finish()
        self.assertTrue(r.surface.isHidden())
        image=r.grab().toImage()
        self.assertTrue(all(image.pixelColor(x,y).alpha()==0 for x in range(image.width()) for y in range(image.height())))
    def test_real_timer_close_stays_hidden_and_clear_on_later_event_turns(self):
        r=self.r;r.open();self.finish();r.dismiss()
        QTest.qWait(r.animation.duration()+120)
        for _ in range(3):
            APP.processEvents();self.assertFalse(r.isVisible());self.assertTrue(r.surface.isHidden())
            self.assertIsNone(r._frame);self.assertEqual(r.grab().toImage().pixelColor(r.rect().center()).alpha(),0)
    def test_closing_canvas_does_not_follow_temporary_owner_canvas(self):
        r=self.r;r.open();self.finish();r.dismiss();rect=QRect(r.geometry())
        self.b.move(self.b.x()-30,self.b.y()-100);APP.processEvents()
        self.assertEqual(r.geometry(),rect)

if __name__=='__main__':unittest.main()
