"""Provenance survives log reduction, roster updates and compact rotation."""
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QEvent
from PySide6.QtWidgets import QApplication
from conversation_sources import metadata_source,session_source,display_source,source_title
from enhanced_core import ActivityReducer
from conversation_roster import ConversationRoster
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])

class SourceTests(unittest.TestCase):
    def test_desktop_terminal_and_verified_bridge_metadata(self):
        cases=[
            (dict(originator='Codex Desktop',source='cli'),('local','本机')),
            (dict(originator='codex-tui',source='cli'),('terminal','终端')),
            (dict(originator='BailongSSHBridge',source='bailong_ssh_bridge',remote_host='gpu228'),('ssh','gpu228')),
            (dict(originator='Codex Desktop',remote_host='gpu228',title='[gpu228] test'),('local','本机')),
            (dict(originator='BailongSSHBridge',source='bailong_ssh_bridge',remote_host='http://user:secret@host'),('ssh','SSH')),
        ]
        for metadata,expected in cases:self.assertEqual(metadata_source(metadata),expected)
    def test_short_alias_is_display_only_and_existing_title_prefix_is_not_duplicated(self):
        self.assertEqual(display_source('gpu228'),'228')
        self.assertEqual(display_source('win'),'win')
        self.assertEqual(source_title('[gpu228] jsc-15','gpu228'),'[228] jsc-15')
        self.assertEqual(source_title('[228] jsc-15','gpu228'),'[228] jsc-15')
        self.assertEqual(source_title('普通名称',''),'普通名称')

    def test_reducer_provenance_and_wsl_mapping(self):
        reducer=ActivityReducer()
        reducer.apply('a',dict(type='session_meta',payload=dict(id='a',originator='BailongSSHBridge',source='bailong_ssh_bridge',remote_host='gpu228')),historical=True)
        reducer.apply('a',dict(type='session_meta',payload=dict(id='someone-else',originator='Codex Desktop')),historical=True)
        self.assertEqual(session_source(reducer.sessions['a'],True),dict(source_kind='ssh',source_label='gpu228'))
        self.assertEqual(session_source(None,True),dict(source_kind='wsl',source_label='WSL'))
    def test_roster_preserves_source_through_rename_and_status_updates(self):
        roster=ConversationRoster();roster.observe(dict(session='a',state='working',source_kind='ssh',source_label='gpu228'))
        roster.update_names({'a':'renamed'});roster.observe(dict(session='a',state='responding'))
        self.assertEqual(roster.items['a']['source_label'],'gpu228')
        self.assertEqual(roster.items['a']['title'],'renamed')
    def test_restored_completion_gets_source_before_any_new_status_event(self):
        roster=ConversationRoster();self.assertTrue(roster.update_sources({'restored':dict(source_kind='ssh',source_label='gpu228')}))
        selected,_=roster.selection([('restored','old')])
        self.assertEqual(selected[0]['source_label'],'gpu228');self.assertEqual(selected[0]['state'],'complete')

class CapsuleSourceUiTests(unittest.TestCase):
    def setUp(self):self.b=CompactBubble();self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def seed(self):
        for sid,label,kind,state in [('a','本机','local','working'),('b','gpu228','ssh','responding'),('c','终端','terminal','thinking')]:
            self.b.roster.observe(dict(session=sid,title='Synthetic task '+sid,state=state,source_label=label,source_kind=kind))
        self.b.set_mode('mini');self.b.size_transition.complete();APP.processEvents()
    def test_rows_match_sessions_during_rotation_without_resizing(self):
        self.seed();size=self.b.size()
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            for _ in range(4):
                selected,_=self.b.roster.selection(self.b.status_indicator.unread)
                self.assertEqual([r['full_source'] for r in self.b.island.text.source_rows],[v['source_label'] for v in selected])
                self.assertEqual(self.b.size(),size);self.assertEqual(len(self.b.island.text.source_rows),2)
                self.b._auto_cycle_conversations()
    def test_source_is_accessible_and_long_host_is_elided_without_changing_geometry(self):
        self.seed();size=self.b.size();host='a-very-long-ssh-host-name'
        self.b.roster.observe(dict(session='a',state='working',source_label=host,source_kind='ssh'))
        self.b.refresh_status()
        self.assertIn(host,self.b.island.accessibleName());self.assertEqual(self.b.size(),size)
        self.assertNotEqual(self.b.island.text.source_rows[0]['source'],host)
    def test_offline_row_keeps_name_without_running_color_then_resumes(self):
        self.b.roster.observe(dict(session='remote',state='offline',title='[gpu228] jsc-15',display='连接中断，重连中 · 上次：正在运行命令',source_kind='ssh',source_label='gpu228'))
        self.b.set_mode('mini');self.b.size_transition.complete();APP.processEvents();self.b.refresh_status()
        rows=self.b.island.text.source_rows
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'重连中');self.assertFalse(rows[0]['running'])
        self.assertIn('jsc-15',self.b.island.accessibleName());self.assertIn('重连中',self.b.island.accessibleName())
        self.b.roster.observe(dict(session='remote',state='working',display='正在运行命令'))
        self.b.refresh_status();self.assertTrue(self.b.island.text.source_rows[0]['running'])

    def test_source_stays_visible_from_capsule_to_normal_and_expanded_card(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        b=self.b
        b.roster.observe(dict(session='remote',state='working',title='jsc-15',display='正在运行命令',source_kind='ssh',source_label='gpu228'))
        b.roster.observe(dict(session='local',state='working',title='本机任务',display='正在编辑文件',source_kind='local',source_label='win'))
        b.set_mode('mini');b.size_transition.complete();APP.processEvents()
        self.assertEqual(b.island.text.source_rows[0]['source'],'228')
        b.set_mode('auto');b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
        self.assertTrue(b.status_view.rows['remote'].short_title.startswith('[228] '))
        b.toggle_details();b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
        row=b.status_view.rows['remote'];self.assertTrue(row.expanded_row)
        self.assertEqual(row.short_title,'[228] jsc-15')
        self.assertIn('[win]',b.status_view.rows['local'].short_title)
        self.assertIn('[228] jsc-15',row.accessibleName())
        opened=[];b.conversationRequested.connect(opened.append)
        QTest.mouseClick(row,Qt.MouseButton.LeftButton,pos=QPoint(20,12));APP.processEvents()
        self.assertEqual(opened,['remote'])
        self.assertEqual(b.roster.items['remote']['source_label'],'gpu228')
        self.assertEqual(b.roster.items['remote']['title'],'jsc-15')

    def test_expanded_platform_is_never_elided_with_a_long_chat_name(self):
        from compact_bubble import StatusScroller
        from PySide6.QtGui import QFontMetrics
        for source,label in [('mac','mac'),('win','win'),('wsl','wsl'),('gpu228','228')]:
            for width in (136,188,330):
                view=StatusScroller(width);view.show();APP.processEvents()
                title='一个很长的会话名称用于验证平台完整显示'*10
                view.set_conversations([('session','正在处理任务')],full=True,metadata={'session':dict(title=title,state='working',source_label=source)})
                row=view.rows['session'];prefix='['+label+'] '
                self.assertTrue(row.short_title.startswith(prefix),(source,width,row.short_title))
                self.assertLessEqual(row.title_width,max(40,row.width()-76))
                self.assertLessEqual(QFontMetrics(row.font()).horizontalAdvance(row.short_title),row.transition_regions()['title'].width())
                self.assertEqual(row.conversation_title,title)
                view.close();view.deleteLater();APP.processEvents()

    def test_single_row_and_idle_fallback_keep_fixed_height(self):
        self.b.roster.observe(dict(session='a',state='working',source_label='本机',source_kind='local'))
        self.b.set_mode('mini');self.b.size_transition.complete();APP.processEvents()
        self.assertEqual(len(self.b.island.text.source_rows),1);self.assertEqual(self.b.island.height(),40)
        self.b.roster.observe(dict(session='a',state='idle'));self.b.refresh_status()
        self.assertFalse(self.b.island.text.source_rows);self.assertEqual(self.b.island.height(),40)

if __name__=='__main__':unittest.main()
