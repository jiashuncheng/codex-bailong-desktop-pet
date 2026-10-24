"""Real chart layers/navigation: bounded work, stable layout and readable text."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy,time,unittest
from unittest.mock import patch
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QLabel
from test_daily_report import APP,sample
from compact_bubble import CompactBubble
from daily_report import DailyReport,ReportPlot
from token_charts import TokenPlot
from quota_summary import QuotaSummary

class AnimationLoadTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.windows=[dict(name='一周',remaining=73,resetsAt=time.time()+86400)]
        self.b.token_snapshot=sample();self.b.redraw();self.b.move(100,650);self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def finish(self):self.b.size_transition.complete();APP.processEvents()
    def test_tab_slide_keeps_controls_quota_and_geometry_and_latest_selection(self):
        b=self.b;deck=b.deck;quota=b.findChild(QuotaSummary);quota.begin_reveal();quota.start_reveal();quota.animation.setCurrentTime(120)
        geom=b.geometry();plot=deck.content.plot;start=deck.tabs.pill.x()
        b.select_dashboard('reset');deck.tabs.animation.setCurrentTime(70);middle=deck.tabs.pill.x()
        self.assertGreater(middle,start);self.assertLess(middle,deck.tabs._to.x())
        b.select_dashboard('tokens');deck.tabs.animation.setCurrentTime(180)
        self.assertIs(b.deck,deck);self.assertIs(deck.content.plot,plot);self.assertIs(b.findChild(QuotaSummary),quota)
        self.assertEqual(quota.animation.currentTime(),120);self.assertEqual(b.geometry(),geom)
        self.assertEqual(deck.tabs.pill,deck.tabs._to)
        deck.hide();self.assertEqual(deck.tabs.animation.state(),QAbstractAnimation.State.Stopped)
    def test_unified_refresh_does_not_depend_on_card_selection(self):
        b=self.b;seen=[];b.refreshAllRequested.connect(lambda:seen.append('all'))
        b.set_refresh_busy(True);b.select_dashboard('reset');self.assertFalse(b.refresh_button.isEnabled())
        b.finish_refresh();b.refresh_button.click();b.select_dashboard('tokens');b.refresh_button.click()
        self.assertEqual(seen,['all']);self.assertFalse(b.refresh_button.isEnabled())
        self.assertFalse(b.token_refresh_buttons);self.assertFalse(b.reset_refresh_buttons)
    def test_range_reuses_plot_and_quota_without_rebuilding_bubble(self):
        b=self.b;deck=b.deck;plot=deck.content.plot;quota=b.findChild(QuotaSummary)
        with patch.object(b,'redraw',wraps=b.redraw) as redraw:
            b.select_token_range('day');b.select_dashboard('reset');b.show_today_tokens()
            redraw.assert_not_called()
        self.assertIs(b.deck,deck);self.assertIs(deck.content.plot,plot);self.assertIs(b.findChild(QuotaSummary),quota)
        self.assertEqual(plot.series['mode'],'line');self.assertTrue(b.today_tokens_card.selected)
    def test_chart_frames_reuse_layers_and_rebuild_on_data_or_size_change(self):
        report=sample()['report'];plots=[self.b.deck.content.plot,ReportPlot(report),ReportPlot(report,'bars')]
        try:
            for plot in plots:
                plot.resize(220,94);plot.show();APP.processEvents();plot.begin_reveal();builds=plot.layer_builds
                with patch.object(plot,'render_layers',wraps=plot.render_layers) as build:
                    plot.start_reveal()
                    for ms in range(0,621,20):plot.reveal.animation.setCurrentTime(ms);plot.grab()
                    build.assert_not_called()
                self.assertEqual(plot.layer_builds,builds)
                plot.resize(240,94);plot.grab();self.assertEqual(plot.layer_builds,builds+1)
                if isinstance(plot,ReportPlot):plot.set_data(report,plot.series,plot.selected)
                else:plot.set_data(plot.snapshot,'day')
                plot.grab();self.assertEqual(plot.layer_builds,builds+2)
        finally:
            for plot in plots[1:]:plot.close();plot.deleteLater()
    def test_quota_animation_never_rasterizes_labels_again(self):
        quota=self.b.findChild(QuotaSummary);quota.begin_reveal();builds=quota.layer_builds;quota.start_reveal()
        with patch('quota_summary.font',side_effect=AssertionError('font work on animation frame')):
            for ms in range(0,421,20):quota.animation.setCurrentTime(ms);quota.grab()
        self.assertEqual(quota.layer_builds,builds)
    def test_report_scrollbar_gutter_is_ready_before_animation_finishes(self):
        r=DailyReport(self.b);self.b.report=r;r.set_snapshot(sample());r.open()
        snapshot=(r.scroll.viewport().size(),r.plot.width())
        r.animation.setCurrentTime(r.animation.duration());landed=(r.scroll.viewport().size(),r.plot.width());APP.processEvents()
        self.assertEqual(snapshot,landed);self.assertEqual(landed,(r.scroll.viewport().size(),r.plot.width()))
        self.assertFalse(r.scroll.verticalScrollBar().isVisible())
        self.assertEqual(r.scroll.verticalScrollBar().maximum(),0)
        for label in (r.analogy_caption,r.note_label) if hasattr(r,'analogy_caption') else (r.note_label,):
            self.assertGreaterEqual(label.font().pixelSize(),11)
            self.assertLess(label.font().pixelSize(),r.hour_total.font().pixelSize())
            self.assertLessEqual(label.font().weight(),500)
    def test_landing_cache_is_ready_before_first_motion_frame(self):
        self.b.toggle_details();t=self.b.size_transition
        self.assertTrue(t.running);self.assertIsNotNone(t.morph._landing)
        cached=t.morph._landing;key=cached[1][0].cacheKey()
        t.animation.setCurrentTime(round(t.animation.duration()*.95));self.b.grab()
        self.assertIs(cached,t.morph._landing);self.assertEqual(key,t.morph._landing[1][0].cacheKey())

if __name__=='__main__':unittest.main()
