"""Exercise resolved glyphs and constrained controls, not requested font names."""
import struct
import unittest
from PySide6.QtGui import QFontMetricsF,QTextLayout
from PySide6.QtWidgets import QApplication,QToolButton
from typography import install_ui_font,ui_font,LATIN_FAMILY,CHINESE_FAMILY

APP=QApplication.instance() or QApplication([])
install_ui_font(APP)

def physical_faces(text,font):
    layout=QTextLayout(text,font);layout.beginLayout();line=layout.createLine();line.setLineWidth(1000);layout.endLayout()
    faces=[]
    for run in layout.glyphRuns():
        raw=run.rawFont();os2=bytes(raw.fontTable('OS/2'))
        faces.append((raw.familyName(),struct.unpack('>H',os2[4:6])[0]))
        if 0 in run.glyphIndexes():raise AssertionError('missing glyph in '+text)
    return faces

class TypographyTests(unittest.TestCase):
    def tearDown(self):
        for w in APP.topLevelWidgets():w.close();w.deleteLater()
        APP.processEvents()
    def test_mixed_date_uses_actual_medium_faces_without_synthesized_bold(self):
        self.assertEqual(set(physical_faces('最晚 10/24 01:00',ui_font(10,True))),
                         {(LATIN_FAMILY,500),(CHINESE_FAMILY,500)})
        self.assertEqual(physical_faces('222.49M',ui_font(12,True)),[(LATIN_FAMILY,500)])
        self.assertEqual(physical_faces('73%',ui_font(28,True)),[(LATIN_FAMILY,600)])
    def test_header_and_deck_labels_share_face_and_fit_without_clipping(self):
        from compact_bubble import CompactBubble
        from dashboard_cards import CardDeck
        bubble=CompactBubble();bubble.show();APP.processEvents();bubble.size_transition.complete();APP.processEvents()
        deck=CardDeck('tokens',{},None,False,False);deck.resize(115,102);deck.show();APP.processEvents()
        title=bubble.findChild(QToolButton,'open_codex');token=deck.tabs.buttons['tokens']
        self.assertEqual(physical_faces('Codex',title.font()),physical_faces('Token',token.font()))
        self.assertEqual(title.font().pixelSize(),token.font().pixelSize())
        for button in deck.tabs.buttons.values():
            metrics=QFontMetricsF(button.font())
            self.assertLessEqual(metrics.horizontalAdvance(button.text())+2,button.width())
            self.assertLessEqual(metrics.height()+2,button.height())

if __name__=='__main__':unittest.main()
