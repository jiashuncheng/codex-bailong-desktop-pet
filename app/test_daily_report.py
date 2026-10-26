import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,sqlite3,tempfile,unittest,time
from contextlib import closing
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from PySide6.QtCore import Qt,QEvent,QPoint,QPointF,QAbstractAnimation
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication,QToolButton,QToolTip,QLabel
from token_calendar import TokenUsageIndex
from token_analytics import model_series,token_analogy,UNKNOWN
from compact_bubble import CompactBubble
from daily_report import DailyReport,ModelRow
from PySide6.QtTest import QTest

APP=QApplication.instance() or QApplication([])

def event(day,hour,kind,payload):
    return dict(timestamp=datetime(2026,10,day,hour).astimezone().isoformat(),type=kind,payload=payload)
def count(day,hour,total,a,b):return event(day,hour,'event_msg',dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=a,output_tokens=b))))

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);(self.home/'sessions').mkdir();self.path=self.home/'sessions/rollout-test.jsonl'
        self.index=TokenUsageIndex(self.home/'usage.sqlite3',self.home);self.now=datetime(2026,10,18,12).timestamp()
    def tearDown(self):self.tmp.cleanup()
    def write(self,rows,mode='w'):
        with self.path.open(mode,encoding='utf-8') as f:
            for r in rows:f.write(json.dumps(r)+'\n')
    def fixture(self):return [
        event(16,10,'session_meta',dict(id='s')),
        event(16,10,'turn_context',dict(model='model-A')),count(16,10,100,80,20),
        event(17,3,'event_msg',dict(type='task_started',turn_id='t')),
        event(17,3,'event_msg',dict(type='user_message',message='hello')),
        event(17,3,'response_item',dict(type='message',role='user',content=[dict(text='environment context')])),
        event(17,3,'event_msg',dict(type='agent_message',message='public reply')),
        event(17,3,'response_item',dict(type='message',role='assistant',content=[dict(text='public reply\n')])),
        count(17,3,300,240,60),event(17,8,'turn_context',dict(model='model-B')),count(17,8,600,480,120),
        count(18,9,700,560,140)]
    def test_scopes_models_messages_and_hourly_deltas(self):
        self.write(self.fixture());s=self.index.poll(self.now);r=s['report']
        self.assertEqual(s['all_total'],700);self.assertEqual(r['sessions'],1);self.assertEqual(r['active_days'],3)
        self.assertEqual(r['all_total'],700);self.assertEqual(r['favorite_model'],'model-B')
        self.assertEqual(r['messages'],2);self.assertEqual(r['yesterday_total'],500);self.assertEqual(r['peak_hour'],8)
        self.assertEqual(len(r['hours']),24);self.assertEqual(r['hours'][3],200);self.assertEqual(r['hours'][8],300)
        series=model_series(r,'7d');self.assertEqual(series['total'],600)
        self.assertEqual({m['model']:m['total'] for m in series['models']},{'model-A':300,'model-B':300})
        self.assertTrue(all(m['known'] and m['input']+m['output']==m['total'] for m in series['models']))
        self.assertEqual(series['end'],'2026-10-17');self.assertEqual(len(series['bins']),7)
    def test_restart_and_model_change_after_incremental_offset(self):
        self.write(self.fixture()[:3]);self.index.poll(self.now)
        self.write([event(17,8,'turn_context',dict(model='model-B')),count(17,8,400,320,80)],'a')
        r=TokenUsageIndex(self.index.path,self.home).poll(self.now)['report']
        self.assertEqual({x['model']:x['total'] for x in model_series(r,'all')['models']},{'model-A':100,'model-B':300})
        self.assertEqual(self.index.poll(self.now)['report'],r)
    def test_migration_keeps_old_totals_including_deleted_logs(self):
        with closing(sqlite3.connect(self.index.path)) as db,db:
            db.execute('CREATE TABLE files (path TEXT PRIMARY KEY,offset INTEGER,highwater INTEGER)')
            db.execute('CREATE TABLE usage (fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER)')
            db.execute('INSERT INTO usage VALUES (?,?,?)',('deleted-history',datetime(2026,10,1).timestamp(),50))
        self.write(self.fixture());r=self.index.poll(self.now)['report']
        self.assertEqual(r['all_total'],750);self.assertTrue(r['metadata_incomplete'])
        self.assertEqual(next(m for m in model_series(r,'all')['models'] if m['model']==UNKNOWN)['total'],50)
        with closing(sqlite3.connect(self.index.path)) as db,db:
            text='\n'.join(db.iterdump());self.assertNotIn('public reply',text);self.assertNotIn('environment context',text)
    def test_time_ranges_and_analogy_change_with_actual_totals(self):
        self.write(self.fixture());r=self.index.poll(self.now)['report']
        self.assertEqual(len(model_series(r,'30d')['bins']),30)
        self.assertNotEqual(token_analogy(100000),token_analogy(200000))
        from book_reference import catalog
        size=catalog()['books'][0]['tokens']
        self.assertIn('1.0',token_analogy(size));self.assertIn('2.0',token_analogy(size*2))
    def test_midnight_rollover_summarizes_previous_calendar_day(self):
        self.write(self.fixture());r=self.index.poll(datetime(2026,10,19,0,1).timestamp())['report']
        self.assertEqual(r['day'],'2026-10-18');self.assertEqual(r['yesterday_total'],100)

def sample():
    return dict(report=dict(day='2026-10-17',sessions=185,messages=123,all_total=2200000000,active_days=6,peak_hour=15,favorite_model='gpt-6.1-sol',yesterday_total=156000,
         hours=[0,0,0,12000,0,0,0,0,0,4000,12000,0,16000,12000,10000,58000,8000,8000,0,0,0,0,8000,0],
         daily_models=[dict(day=f'2026-10-{day:02}',model=m,total=value,input=round(value*.8),output=round(value*.2),known=True)
             for day,value in [(12,1200),(13,30000),(14,12000),(15,56000),(16,78000),(17,30000)] for m in ('gpt-6.1-sol','gpt-6-sol')]))

class ReportUiTests(unittest.TestCase):
    def test_cycle_to_overview_measures_complete_body_before_resize(self):
        self.r.open();self.complete()
        for width in (268,420,560):
            self.b.setFixedWidth(width);self.r.sync_geometry();initial=self.r.surface.size()
            for page in ('cycle','overview','models','overview','cycle','overview'):
                self.r.set_page(page)
                self.assertEqual(self.r.surface.size(),initial,(width,page))
                APP.processEvents()
                self.assertEqual(self.r.surface.size(),initial,(width,page))
    def setUp(self):
        self.b=CompactBubble();self.b.move(100,650);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample())
    def tearDown(self):
        self.r.animation.stop();self.r.close();self.b.close();self.b.deleteLater();APP.processEvents()
    def complete(self):self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def test_hidden_until_manual_open_then_animated_above_and_same_width(self):
        self.assertFalse(self.r.isVisible());self.assertFalse(self.r.requested)
        self.r.open();self.r.animation.setCurrentTime(80);middle=self.r.visible_height()
        self.assertEqual(self.r.content_geometry().width(),self.b.width());self.assertEqual(self.r.content_geometry().x(),self.b.x())
        self.assertEqual(self.r.content_geometry().bottom()+1,self.b.y()-6)
        self.assertGreater(middle,1);self.complete();self.assertGreater(self.r.visible_height(),middle)
        self.r.dismiss();self.r.animation.setCurrentTime(130);self.assertTrue(self.r.isVisible());self.complete();self.assertFalse(self.r.isVisible())
    def test_overview_has_no_range_filter_model_page_filters_totals(self):
        self.r.open();self.complete()
        self.assertFalse([b for b in self.r.findChildren(QToolButton) if b.objectName().startswith('report_range_') and not b.isHidden()])
        self.r.set_page('models');APP.processEvents()
        nav=self.r.period_control.parentWidget()
        for widget in [*self.r.page_buttons.values(),self.r.period_control]:
            self.assertTrue(nav.rect().contains(widget.geometry()),widget.objectName())
        self.assertEqual(len([b for b in self.r.findChildren(QToolButton) if b.objectName().startswith('report_range_') and not b.isHidden()]),3)
        model=self.r.findChildren(ModelRow)[-1];model.click();self.assertEqual(self.r.selected_model,model.item['model'])
        self.r.set_period('7d');self.assertEqual(len(self.r.plot.series['bins']),7);self.r.set_period('30d');self.assertEqual(len(self.r.plot.series['bins']),30)
    def test_cycle_page_shows_local_usage_and_gated_estimate(self):
        self.r.open();self.complete()
        self.r.set_page('cycle');APP.processEvents()
        self.assertEqual(self.r.page_buttons['cycle'].text(),'额度对比')
        self.assertEqual(self.r.layout.itemAt(0).widget().findChildren(QLabel)[0].text(),'数据面板')
        self.assertEqual(self.r.day_label.text(),'')
        self.assertTrue(self.r.period_control.isHidden())
        self.assertEqual(self.r.cycle_view.estimate.text(),'—')
        item=dict(id='test',start=1760000000,end=1760050000,through=1760050000,reset_at=1760600000,
            kind='natural',closed=False,remaining=75,used=150000,estimated_total=600000,
            per_percent=6000,complete=True,fresh=True,records=3,drop=25,comparison_reason='尚无可比历史',change=None)
        data=sample();data['quota_history']=dict(cycles=[item])
        self.r.set_snapshot(data)
        self.assertEqual(self.r.cycle_view.used.text(),'150.0K')
        self.assertEqual(self.r.cycle_view.estimate.text(),'600.0K')
        self.assertIn('75%',self.r.cycle_view.detail.text())
        APP.processEvents()
        self.assertEqual(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.r.cycle_view.note.isHidden() or self.r.cycle_view.rules.isHidden())
        self.assertTrue(self.r.cycle_view.rules_button.isVisible())
        data=dict(data,quota_history=dict(cycles=[dict(item,estimated_total=None,complete=False)]))
        self.r.set_snapshot(data)
        self.assertEqual(self.r.cycle_view.estimate.text(),'—')
        self.assertIn('受限',self.r.cycle_view.quality.text())
    def test_overview_fully_fits_and_model_scroll_is_only_for_overflow(self):
        self.r.open();self.complete();APP.processEvents()
        area=self.r.scroll
        self.assertEqual(area.verticalScrollBar().maximum(),0)
        self.assertFalse(area.verticalScrollBar().isVisible())
        self.assertTrue(area.viewport().rect().contains(self.r.note_label.mapTo(area.viewport(),self.r.note_label.rect().bottomRight())))
        height=self.r.height()
        self.r.set_page('models');APP.processEvents()
        self.assertEqual(self.r.height(),height)
        self.assertFalse(self.r.scroll.verticalScrollBar().isVisible())
        data=sample()
        data['report']['daily_models']=[dict(day='2026-10-17',model='model-'+str(i),total=1000,input=800,output=200,known=True) for i in range(12)]
        self.r.set_snapshot(data);QTest.qWait(20)
        self.assertGreater(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.r.scroll.verticalScrollBar().isVisible())
        self.r.set_page('overview');APP.processEvents()
        self.assertEqual(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertFalse(self.r.scroll.verticalScrollBar().isVisible())
    def test_page_changes_keep_chrome_and_only_fade_body(self):
        self.r.open();self.complete();APP.processEvents()
        title=self.r.header_title;nav=self.r.page_buttons['models'].parentWidget()
        header_geometry=title.parentWidget().geometry();nav_geometry=nav.geometry()
        with patch('settings_controls.motion_enabled',return_value=True):
            for page in ('models','cycle','overview'):
                self.r.set_page(page);APP.processEvents()
                self.assertIs(self.r.header_title,title)
                self.assertIs(self.r.page_buttons['models'].parentWidget(),nav)
                self.assertEqual(title.parentWidget().geometry(),header_geometry)
                self.assertEqual(nav.geometry(),nav_geometry)
                self.assertTrue(self.r.page_fade.geometry().top()>=nav.geometry().bottom())
            self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration())
            self.assertFalse(self.r.page_fade.isVisible())
    def test_native_tooltips_suppressed_but_inline_hover_still_works(self):
        self.b.redraw();APP.processEvents();button=self.b.findChild(QToolButton,'bubble_report')
        with patch.object(QToolTip,'showText') as show:
            APP.sendEvent(button,QHelpEvent(QEvent.Type.ToolTip,QPoint(3,3),button.mapToGlobal(QPoint(3,3))))
            show.assert_not_called()
        self.assertFalse(QToolTip.isVisible())
        from quota_summary import QuotaSummary
        quota=next(w for w in self.b.findChildren(QuotaSummary) if w.isVisible());point=quota.row_rect(0).center().toPoint()
        with patch.object(QToolTip,'showText') as show:
            APP.sendEvent(quota,QHelpEvent(QEvent.Type.ToolTip,point,quota.mapToGlobal(point)))
            show.assert_not_called()
        self.r.open();self.complete();self.r.plot.grab();values=[];self.r.plot.hoverText.connect(values.append)
        self.assertEqual(len(self.r.plot.hits),24)
        self.assertEqual(self.r.report['hours'],sample()['report']['hours'])
    def test_refresh_never_opens_report_and_resize_remains_aligned(self):
        self.r.set_snapshot(sample());self.assertFalse(self.r.isVisible())
        self.r.open();self.complete();self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
        self.assertEqual(self.r.content_geometry().width(),self.b.width());self.assertEqual(self.r.content_geometry().x(),self.b.x())
        self.b.hide();self.assertFalse(self.r.isVisible());self.assertFalse(self.r.requested)
    def test_large_y_axis_values_have_full_font_height_and_width(self):
        data=sample();data['report']['hours'][15]=17270000
        self.r.set_snapshot(data);self.r.open();self.complete();plot=self.r.plot
        plot.grab();chart=plot.chart_rect();fm=plot._axis_metrics
        self.assertIn('17.27M',plot._axis_labels)
        for text in plot._axis_labels:
            self.assertGreaterEqual(chart.left()-6-fm.horizontalAdvance(text),1)
        self.assertGreaterEqual(chart.top()-fm.height()/2,1)
        self.assertLess(chart.bottom()+fm.height()/2,plot.height())

class BackgroundTests(unittest.TestCase):
    def test_index_rebuild_does_not_block_status_monitor_and_cancels_on_exit(self):
        from enhanced import ActivityThread
        with tempfile.TemporaryDirectory() as folder,patch('enhanced.STATE_DIR',Path(folder)):
            worker=ActivityThread(home=folder);events=[];worker.event.connect(events.append)
            def slow_index(now=None,stop=lambda:False):
                deadline=time.monotonic()+5
                while not stop() and time.monotonic()<deadline:time.sleep(.01)
                return {}
            with patch.object(worker.token_index,'poll',side_effect=slow_index),patch.object(worker.tail,'poll',return_value=[dict(kind='status',state='working')]):
                worker.start()
                try:
                    deadline=time.monotonic()+2.6
                    while len([e for e in events if e['kind']=='status'])<2 and time.monotonic()<deadline:
                        APP.processEvents();time.sleep(.03)  # Give Python QThread workers the GIL, as app.exec() does.
                    self.assertGreaterEqual(len([e for e in events if e['kind']=='status']),2)
                    self.assertTrue(worker.token_reader.is_alive())
                finally:worker.stop.set();self.assertTrue(worker.wait(2000))
                self.assertFalse(worker.token_reader.is_alive())

if __name__=='__main__':unittest.main()
