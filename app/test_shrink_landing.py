"""The native resize itself must be covered, not just its endpoint screenshot."""
import os,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import QObject,QEvent,QRect,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from compact_bubble import CompactBubble
from test_panel_transition import APP

def wait_for(predicate,timeout=1000):
    end=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    APP.processEvents();return predicate()

class ShrinkLandingTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(10000,10000);self.b.show();APP.processEvents()
        self.b.status_indicator.clock=lambda:0.
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def expand(self):
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
    def test_both_shrinks_publish_independent_surface_before_native_resize(self):
        class NativeEvents(QObject):
            def __init__(self,transition):super().__init__();self.t=transition;self.checks=[]
            def eventFilter(self,obj,event):
                if event.type()==QEvent.Type.Resize:
                    g=self.t.landing
                    self.checks.append((g.isWindow(),g.isVisible(),g.image is not None,g.paints,g.geometry()==self.t.target_rect))
                return False
        b=self.b;self.expand();t=b.size_transition;rec=NativeEvents(t);b.installEventFilter(rec)
        for action in (b.toggle_details,lambda:b.set_mode('mini')):
            action();APP.processEvents();rec.checks=[];target=QRect(t.target_rect);handle=int(b.winId());t.complete()
            self.assertTrue(rec.checks);self.assertTrue(all(all(row[:3]) and row[3]>0 and row[4] for row in rec.checks),rec.checks)
            self.assertEqual(b.geometry(),target);self.assertEqual(int(b.winId()),handle)
            self.assertTrue(t.landing.isVisible());self.assertTrue(t.landing_timer.isActive());self.assertTrue(b.content.isVisible())
            self.assertTrue(wait_for(lambda:not t.landing.isVisible()));self.assertIsNone(t.landing.image);self.assertFalse(t.landing_timer.isActive())
    def test_guard_is_mouse_transparent_and_does_not_accept_focus(self):
        self.expand();self.b.toggle_details();t=self.b.size_transition;t.complete();g=t.landing
        self.assertTrue(g.windowFlags()&Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(g.windowFlags()&Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(g.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertEqual(g.focusPolicy(),Qt.FocusPolicy.NoFocus)
    def test_retiring_surface_flushes_live_window_before_hiding(self):
        self.b.set_mode('mini');t=self.b.size_transition;t.complete();calls=[]
        repaint=self.b.repaint;release=t.landing.release
        with patch.object(self.b,'repaint',side_effect=lambda:(calls.append(('paint',t.landing.isVisible())),repaint())),patch.object(t.landing,'release',side_effect=lambda:(calls.append(('hide',self.b.content.isVisible())),release())):
            t.release_landing()
        self.assertEqual(calls,[('paint',True),('hide',True)])
        self.assertIsNone(t.landing.image);self.assertFalse(t.landing_timer.isActive())
    def test_rapid_next_navigation_retires_old_guard_and_old_timer(self):
        b=self.b;self.expand();b.toggle_details();t=b.size_transition;t.complete();self.assertTrue(t.landing.isVisible())
        b.set_mode('mini');self.assertTrue(t.running);self.assertIsNone(t.landing.image);self.assertFalse(t.landing_timer.isActive())
        t.complete();image=t.landing.image;self.assertIsNotNone(image)
        b.set_mode('auto');self.assertTrue(t.running);QTest.qWait(70)
        self.assertTrue(t.running);self.assertFalse(t.landing.isVisible());t.complete();self.assertFalse(b.is_island())
    def test_hiding_during_landing_never_leaves_a_floating_surface(self):
        self.b.set_mode('mini');t=self.b.size_transition;t.complete();self.assertTrue(t.landing.isVisible())
        self.b.hide();QTest.qWait(70)
        self.assertFalse(t.landing.isVisible());self.assertIsNone(t.landing.image);self.assertFalse(t.landing_timer.isActive())
        self.b.show();APP.processEvents();self.assertTrue(self.b.content.isVisible())
    def test_expansion_has_no_additional_landing_window(self):
        self.expand();t=self.b.size_transition
        self.assertFalse(t.landing.isVisible());self.assertIsNone(t.landing.image);self.assertFalse(t.landing_timer.isActive())
    def test_shrinks_keep_quota_and_chart_values_instead_of_revealing_again(self):
        from quota_summary import QuotaSummary
        from island_widgets import QuotaSatellite
        from token_charts import TokenPlot
        b=self.b;b.windows=[dict(name='一周',remaining=73)];b.redraw();self.expand()
        card=next(w for w in b.findChildren(QuotaSummary) if w.isVisible())
        card.animation.setCurrentTime(card.animation.duration());b.toggle_details();t=b.size_transition
        normal=next(w for w in b.content.findChildren(QuotaSummary) if w.isVisibleTo(b.content))
        plot=b.deck.content.plot
        self.assertEqual(normal.values['quota:一周'],.73);self.assertEqual(plot.reveal.progress,1.);self.assertFalse(plot.reveal.pending)
        t.complete();QTest.qWait(70);self.assertEqual(normal.values['quota:一周'],.73)
        b.set_mode('mini');satellite=b.island.parentWidget().findChild(QuotaSatellite)
        self.assertEqual(satellite.reveal.progress,0.);self.assertTrue(satellite.reveal.pending)
        t.complete();QTest.qWait(700);self.assertEqual(satellite.reveal.progress,1.)
    def test_shrink_content_has_no_empty_interval_between_both_views(self):
        b=self.b;self.expand()
        for action in (b.toggle_details,lambda:b.set_mode('mini')):
            action();m=b.size_transition.morph
            self.assertTrue(m.shrinking)
            for i in range(1001):
                old,new=m.content_opacities(i/1000)
                self.assertAlmostEqual(old+new,1.);self.assertTrue(0<=old<=1 and 0<=new<=1)
            b.size_transition.complete();APP.processEvents()

if __name__=='__main__':unittest.main()
