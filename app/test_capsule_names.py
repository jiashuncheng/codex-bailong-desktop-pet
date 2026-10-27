"""Names fit within the unchanged capsule and never move its status glyph."""
import unittest
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from capsule_names import short_session_name

APP=QApplication.instance() or QApplication([])

class NameTests(unittest.TestCase):
    def test_remote_prefix_is_removed_and_jsc_identifier_keeps_its_number(self):
        self.assertEqual(short_session_name('[gpu228] jsc-1','gpu228'),'jsc-1')
        self.assertEqual(short_session_name('[gpu228] jsc-12：很长的科研任务','gpu228'),'jsc-12')
        self.assertEqual(short_session_name('讨论 jsc-2 的实验','本机'),'jsc-2')
        self.assertEqual(short_session_name('普通  会话','本机'),'普通 会话')
        self.assertEqual(short_session_name('','本机'),'会话')

class NameUiTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.set_mode('mini');self.b.size_transition.complete();self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def update(self,titles,states=None,extra=3):
        states=states or ['working']*len(titles)
        entries=[dict(source_label='gpu228',title=title,state=state) for title,state in zip(titles,states)]
        icon=self.b.status_indicator;icon.session_entries=entries;icon.session_states=states
        icon.session_summary='/'.join('待操作' if s=='waiting' else '执行' for s in states)+(f' +{extra}' if extra else '')
        self.b.island.refresh();APP.processEvents();return self.b.island.text
    def test_two_same_host_tasks_show_distinct_short_names_without_resizing(self):
        b=self.b;size=b.size();icon_rect=b.status_indicator.geometry();text=self.update(['[gpu228] jsc-1','[gpu228] jsc-2'])
        self.assertEqual([r['name'] for r in text.source_rows],['jsc-1','jsc-2'])
        self.assertEqual([r['source'] for r in text.source_rows],['gpu228','gpu228'])
        self.assertEqual(b.size(),size);self.assertEqual(b.status_indicator.geometry(),icon_rect)
        self.assertEqual(b.island.width(),156);self.assertEqual(b.content.width(),246)
    def test_long_names_and_counts_are_bounded_and_full_titles_remain_accessible(self):
        size=self.b.size();icon_rect=self.b.status_indicator.geometry()
        titles=['[gpu228] 很长的科研项目会话名称用于边界检查一','[gpu228] 很长的科研项目会话名称用于边界检查二']
        for extra in (0,3,99,999):
            text=self.update(titles,['waiting','complete'],extra)
            metrics=QFontMetrics(text.row_font);c=text.row_columns
            self.assertLessEqual(c['count_x']+c['count_width'],text.width())
            self.assertLess(c['source_width'],c['name_x']);self.assertLess(c['name_x']+c['name_width'],c['status_x'])
            for row in text.source_rows:
                self.assertLessEqual(metrics.horizontalAdvance(row['name']),c['name_width'])
                self.assertLessEqual(metrics.horizontalAdvance(row['source']),c['source_width']-2)
                self.assertNotEqual(row['name'],row['full_name'])
            for title in titles:self.assertIn(title,self.b.island.accessibleName())
            self.assertEqual(self.b.size(),size);self.assertEqual(self.b.status_indicator.geometry(),icon_rect)
            self.b.grab()
    def test_numbered_identifiers_stay_distinct_at_current_readable_scale(self):
        self.b.set_role_scale(.7);self.b.size_transition.complete()
        text=self.update(['[gpu228] jsc-10','[gpu228] jsc-11'])
        self.assertEqual([r['name'] for r in text.source_rows],['jsc-10','jsc-11'])
        self.assertEqual(self.b.ui_scale,.85)

if __name__=='__main__':unittest.main()
