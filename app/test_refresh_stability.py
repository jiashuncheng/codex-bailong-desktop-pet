"""Accounting pushes must preserve visible task surfaces and their animation clocks."""
import copy,time,unittest
from datetime import datetime
from unittest.mock import patch
from PySide6.QtCore import QAbstractAnimation,QEvent
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from island_widgets import QuotaSatellite

APP=QApplication.instance() or QApplication([])
def snapshot(total=100,checked=1):
    today=datetime.now().strftime('%Y-%m-%d')
    return dict(scope='all',all_total=total,total=total,month=today[:7],days={today:total},history_days={today:total},checked=checked,report=dict(hours=[0]*24))

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.token_snapshot=snapshot();self.b.windows=[dict(name='一周',remaining=70,resetsAt=time.time()+3600)]
        self.b.redraw();self.b.show();self.finish()
    def finish(self):
        self.b.size_transition.complete();self.b.size_transition.release_landing();APP.processEvents()
    def tearDown(self):
        self.finish();self.b.close();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def mini(self):
        self.b.set_mode('mini');self.finish();self.b.conversation_timer.stop()
        self.b.status_indicator.session_entries=[dict(session='one',source_label='win',title='jsc-1',state='working'),dict(session='two',source_label='gpu228',title='jsc-2',state='working')]
        self.b.status_indicator.session_states=['working','working'];self.b.status_indicator.session_summary='执行/执行';self.b.island.refresh()
        return self.b.island
    def test_capsule_token_updates_preserve_island_rows_and_pixels(self):
        island=self.mini();island.animation.stop();island._caption_frame(1.)
        before=island.text.grab().toImage();rows=island.text.source_rows
        with patch.object(self.b,'redraw',wraps=self.b.redraw) as rebuild:
            for n in range(20):self.b.set_token_snapshot(snapshot(200+n,n));island.refresh()
            rebuild.assert_not_called()
        self.assertIs(self.b.island,island);self.assertIs(island.text.source_rows,rows);self.assertEqual(before,island.text.grab().toImage())
    def test_duplicate_refresh_does_not_end_rotation_and_state_change_has_no_fade(self):
        island=self.mini();entries=self.b.status_indicator.session_entries
        entries[0]=dict(entries[0],session='three',title='jsc-3');island.refresh();island.animation.setCurrentTime(75)
        elapsed=island.animation.currentTime();progress=island.text.property('captionProgress');island.refresh()
        self.assertEqual(island.animation.currentTime(),elapsed);self.assertEqual(island.text.property('captionProgress'),progress)
        island.animation.stop();island._caption_frame(1.);entries[0]['state']='thinking';self.b.status_indicator.session_summary='思考/执行';island.refresh()
        self.assertEqual(island.animation.state(),QAbstractAnimation.State.Stopped);self.assertEqual(island.text.source_rows[0]['status'],'思考')
    def test_quota_updates_preserve_capsule_and_its_caption(self):
        island=self.mini();quota=self.b.content.findChild(QuotaSatellite);before=island.text.grab().toImage()
        self.b.set_quota_data([dict(name='一周',remaining=69,resetsAt=time.time()+3600)],'已更新')
        self.assertIs(self.b.island,island);self.assertIs(self.b.content.findChild(QuotaSatellite),quota)
        self.assertEqual(quota.value_text(),'69%');self.assertEqual(before,island.text.grab().toImage())
    def test_normal_and_expanded_accounting_updates_reuse_all_surfaces(self):
        for expanded in (False,True):
            if expanded:self.b.toggle_details();self.finish()
            b=self.b;deck=b.deck;today=b.today_tokens_card;quota=b.quota_summary_card;view=b.status_view;details=b.details_tabs
            card=deck.pages.get('tokens');card.plot.reveal.animation.stop();card.plot.reveal.pending=False
            new=snapshot(999 if expanded else 500,2)
            with patch.object(b,'redraw',wraps=b.redraw) as rebuild:b.set_token_snapshot(new);rebuild.assert_not_called()
            self.assertIs(b.deck,deck);self.assertIs(b.today_tokens_card,today);self.assertIs(b.quota_summary_card,quota);self.assertIs(b.status_view,view);self.assertIs(b.details_tabs,details)
            self.assertEqual(card.plot.snapshot['all_total'],new['all_total'])
            self.assertIn(f"{new['all_total']:,}",today.data['description'])
            if details:self.assertIn('999',details._token_total.accessibleDescription())
    def test_unchanged_accounting_metadata_does_not_touch_chart(self):
        plot=self.b.deck.pages['tokens'].plot
        with patch.object(plot,'set_data') as update:
            self.assertFalse(self.b.set_token_snapshot(dict(snapshot(),checked=2,sync_checked=3,usage_revision=99,devices=[dict(last_seen=3)])))
            update.assert_not_called()
    def test_chart_entry_coalesces_to_latest_without_restarting(self):
        card=self.b.deck.pages['tokens'];card.plot.begin_reveal();card.plot.start_reveal();card.plot.reveal.animation.setCurrentTime(100)
        initial=card.plot.snapshot['all_total'];elapsed=card.plot.reveal.animation.currentTime()
        card.set_snapshot(snapshot(200));card.set_snapshot(snapshot(300))
        self.assertEqual(card.plot.snapshot['all_total'],initial);self.assertEqual(card.plot.reveal.animation.currentTime(),elapsed)
        card.plot.reveal.animation.setCurrentTime(card.plot.reveal.animation.duration());APP.processEvents()
        self.assertEqual(card.plot.snapshot['all_total'],300)

if __name__=='__main__':unittest.main()
