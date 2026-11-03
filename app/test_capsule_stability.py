"""A timer tick or a metadata update must not impersonate a new session."""
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QEvent,QAbstractAnimation
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])


class CapsuleStabilityTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents()
        self.b.conversation_timer.stop()

    def seed(self,count):
        self.b.roster.items.clear()
        for i in range(count):
            self.b.roster.observe(dict(session=str(i),title='任务 '+str(i),state='thinking',source_label='mac'))
        self.b.set_mode('mini');self.b.size_transition.complete();self.b.size_transition.release_landing();APP.processEvents()
        self.b.island.animation.stop();self.b.island._caption_frame(1.)

    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_empty_single_and_two_sessions_ignore_timer_and_manual_cycle(self):
        for count in (0,1,2):
            with self.subTest(count=count):
                self.seed(count);island=self.b.island;before=island.text.grab().toImage();page=self.b.roster.page
                with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)),patch.object(self.b,'refresh_status',wraps=self.b.refresh_status) as refresh:
                    for _ in range(8):
                        self.b._auto_cycle_conversations();self.b.cycle_conversations()
                    refresh.assert_not_called()
                self.assertEqual(page,self.b.roster.page)
                self.assertEqual(before,island.text.grab().toImage())
                self.assertEqual(island.animation.state(),QAbstractAnimation.State.Stopped)

    def test_rename_and_source_update_same_session_in_place(self):
        self.seed(1);island=self.b.island
        for change in ('title','source'):
            with self.subTest(change=change),patch('island_widgets.play_animation') as start:
                if change=='title':self.b.roster.update_names({'0':'新的会话标题'})
                else:self.b.roster.update_sources({'0':dict(source_kind='local',source_label='本机')})
                self.b.refresh_status();start.assert_not_called()
                self.assertEqual(island.animation.state(),QAbstractAnimation.State.Stopped)
                self.assertEqual(island.text.property('captionProgress'),1.)
                self.assertEqual(island.text.source_rows[0]['session'],'0')
        self.assertIn('新的会话标题',island.accessibleName());self.assertIn('本机',island.accessibleName())

    def test_distinct_sessions_with_same_title_use_actual_identity(self):
        self.seed(3)
        self.b.roster.update_names({str(i):'同名会话' for i in range(3)})
        self.b.refresh_status();island=self.b.island;island.animation.stop();island._caption_frame(1.)
        before=[row['session'] for row in island.text.source_rows]
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            self.b._auto_cycle_conversations()
        after=[row['session'] for row in island.text.source_rows]
        self.assertEqual(sum(a!=b for a,b in zip(before,after)),1)
        self.assertEqual(island.animation.state(),QAbstractAnimation.State.Running)

    def test_repeated_poll_updates_do_not_move_the_only_visible_session(self):
        self.seed(1);island=self.b.island;before=island.text.grab().toImage()
        with patch('island_widgets.play_animation') as start:
            for i in range(12):
                self.b.roster.observe(dict(session='0',title='任务 0',state='thinking',source_label='mac',display='操作 '+str(i)))
                self.b.refresh_status()
            start.assert_not_called()
        self.assertEqual(before,island.text.grab().toImage())

    def test_unchanged_caption_never_reapplies_font_or_width(self):
        self.seed(1);island=self.b.island;rows=island.text.source_rows
        with patch.object(island.text,'setFont') as font,patch.object(island.text,'setFixedWidth') as width:
            for _ in range(8):self.b.refresh_status()
            font.assert_not_called();width.assert_not_called()
        self.assertIs(island.text.source_rows,rows)

    def test_case_only_local_and_shared_source_updates_keep_pixels_and_fonts(self):
        self.seed(1);island=self.b.island;rows=island.text.source_rows;before=island.text.grab().toImage()
        with patch.object(island.text,'setFont') as font,patch('island_widgets.play_animation') as start:
            for label in ('Mac','mac','MAC','Mac','mac'):
                self.b.roster.observe(dict(session='0',state='thinking',source_label=label))
                self.b.refresh_status()
                self.assertEqual(self.b.roster.items['0']['source_label'],label)
                self.assertEqual(island.text.source_rows[0]['source'],'mac')
                self.assertEqual(before,island.text.grab().toImage())
            font.assert_not_called();start.assert_not_called()
        self.assertIs(island.text.source_rows,rows)

    def test_real_rotation_keeps_other_row_pixels_at_every_progress(self):
        self.seed(3);island=self.b.island;before=island.text.grab().toImage()
        stable=before.copy(0,before.height()//2,before.width(),before.height()-before.height()//2)
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):
            self.b._auto_cycle_conversations()
        island.animation.pause()
        for progress in (0.,.25,.5,.75,1.):
            island._caption_frame(progress);image=island.text.grab().toImage()
            self.assertEqual(stable,image.copy(0,image.height()//2,image.width(),image.height()-image.height()//2))


if __name__=='__main__':unittest.main()
