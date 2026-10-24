import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from book_reference import catalog,analogy
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtCore import Qt
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import sample
APP=QApplication.instance() or QApplication([])

class BookReferenceTests(unittest.TestCase):
    def test_catalogue_contains_distinct_sourced_editions_and_individual_counts(self):
        c=catalog();books=c['books'];self.assertGreaterEqual(len(books),25)
        self.assertEqual(len({b['id'] for b in books}),len(books))
        self.assertEqual(len({b['tokens'] for b in books}),len(books))
        self.assertEqual(c['tokenizer'],'o200k_base')
        for b in books:
            self.assertTrue(b['originalTitle']);self.assertTrue(b['author'])
            self.assertTrue(b['source'].startswith('https://www.gutenberg.org/ebooks/'))
            self.assertEqual(len(b['bodySha256']),64);self.assertGreater(b['tokens'],15000)
        self.assertLess(next(b['tokens'] for b in books if b['id']==11),next(b['tokens'] for b in books if b['id']==2600))
    def test_every_book_uses_its_own_reference_count_and_changes_with_total(self):
        for i,b in enumerate(catalog()['books']):
            self.assertEqual(analogy(b['tokens'],i)['quantity'],'1.0')
            self.assertEqual(analogy(b['tokens']*2,i)['quantity'],'2.0')
            self.assertIn(f"{b['tokens']:,}",analogy(0,i)['estimate'])
    def test_switch_book_keeps_plot_and_compact_layout_and_survives_refresh(self):
        b=CompactBubble();b.move(100,650);b.show();APP.processEvents()
        r=DailyReport(b);b.report=r;r.set_snapshot(sample());r.open();r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        try:
            old=r.book_index;plot=r.plot;label=r.analogy.text();height=r.height()
            r.findChild(QToolButton,'report_next_book').click();APP.processEvents()
            self.assertEqual(r.book_index,(old+1)%len(catalog()['books']));self.assertNotEqual(r.analogy.text(),label)
            self.assertIs(r.plot,plot);self.assertEqual(r.height(),height)
            self.assertEqual(r.scroll.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertEqual(r.scroll.verticalScrollBar().maximum(),0)
            fresh=sample();fresh['report']['all_total']*=2;r.set_snapshot(fresh)
            self.assertEqual(r.book_index,(old+1)%len(catalog()['books']));self.assertIs(r.plot,plot)
            self.assertGreaterEqual(r.note_label.font().pixelSize(),11)
            self.assertLess(r.note_label.font().pixelSize(),r.hour_total.font().pixelSize())
            self.assertTrue(r.scroll.viewport().rect().contains(r.note_label.mapTo(r.scroll.viewport(),r.note_label.rect().bottomRight())))
        finally:r.close();b.close();b.deleteLater();APP.processEvents()
    def test_reopening_randomizes_book_without_repeating_previous_and_reversal_does_not(self):
        from unittest.mock import patch
        b=CompactBubble();b.show();r=DailyReport(b);b.report=r;r.set_snapshot(sample())
        try:
            with patch('daily_report.random.randrange',return_value=3) as choose:
                r.open();first=r.book_index;self.assertEqual(first,3)
                r.animation.setCurrentTime(90);r.dismiss();r.open();self.assertEqual(r.book_index,first);self.assertEqual(choose.call_count,1)
                r.animation.setCurrentTime(r.animation.duration());r.dismiss();r.animation.setCurrentTime(r.animation.duration())
                r.open();self.assertNotEqual(r.book_index,first);self.assertEqual(choose.call_count,2)
        finally:r.close();b.close();b.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
