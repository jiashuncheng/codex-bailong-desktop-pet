"""Small, deterministic checks for the Windows tray quota affordance."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QImage
from PySide6.QtCore import QSize

from enhanced import EnhancedPet

APP=QApplication.instance() or QApplication([])


class TrayQuotaTests(unittest.TestCase):
    def setUp(self):
        self.pet=EnhancedPet.__new__(EnhancedPet)
        self.pet._tray_base_icon=QIcon(str(Path(__file__).parent/'branding'/'bailong.ico'))
        self.pet.quota_windows=[]

    def test_five_hour_window_has_priority_over_week(self):
        self.pet.quota_windows=[
            {'name':'一周','remaining':82,'resetsAt':None},
            {'name':'5小时','remaining':64,'resetsAt':None},
        ]
        window,value,valid=self.pet._tray_window()
        self.assertEqual(window['name'],'5小时')
        self.assertEqual(value,64)
        self.assertTrue(valid)

    def test_zero_five_hour_window_falls_back_to_week(self):
        self.pet.quota_windows=[
            {'name':'5小时','remaining':0,'resetsAt':None},
            {'name':'一周','remaining':71,'resetsAt':None},
        ]
        window,value,valid=self.pet._tray_window()
        self.assertEqual(window['name'],'一周')
        self.assertEqual(value,71)
        self.assertTrue(valid)

    def test_unknown_quota_still_produces_a_visible_icon_and_tooltip(self):
        window,value,valid=self.pet._tray_window()
        self.assertFalse(valid)
        self.assertIsNone(value)
        icon=self.pet._tray_quota_icon(window,value,valid)
        self.assertFalse(icon.isNull())
        self.assertIn('未知',self.pet._tray_quota_text(window,value,valid))

    def test_tray_icon_is_a_number_free_circle(self):
        icon=self.pet._tray_quota_icon({'name':'5小时','remaining':70},70,True)
        image=icon.pixmap(QSize(64,64)).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        # The corners stay transparent, so Windows does not turn the icon into
        # a square tile; the center is the circular island background, not text.
        self.assertEqual(image.pixelColor(0,0).alpha(),0)
        self.assertLessEqual(max(abs(a-b) for a,b in zip(image.pixelColor(32,32).getRgb()[:3],(48,42,60))),1)

    def test_zero_quota_keeps_a_full_track_without_a_false_coloured_cap(self):
        from PySide6.QtGui import QColor
        from ui_theme import TRAY_TRACK
        icon=self.pet._tray_quota_icon({'name':'一周','remaining':0},0,True)
        image=icon.pixmap(QSize(64,64)).toImage()
        for x,y in ((32,7),(32,57),(7,32),(57,32)):
            self.assertEqual(image.pixelColor(x,y).name(),QColor(TRAY_TRACK).name())

    def test_remaining_is_bright_and_consumed_track_is_dark(self):
        from ui_theme import TRAY_TRACK,TRAY_WEEK,contrast
        self.assertGreater(contrast(TRAY_TRACK,TRAY_WEEK),4.5)
        image=self.pet._tray_quota_icon({'name':'一周'},25,True).pixmap(QSize(64,64)).toImage()
        self.assertEqual(image.pixelColor(50,14).name(),TRAY_WEEK)
        self.assertEqual(image.pixelColor(14,50).name(),TRAY_TRACK)

    def test_bright_arc_shrinks_as_remaining_drops(self):
        from ui_theme import TRAY_WEEK
        from PySide6.QtGui import QColor
        counts=[]
        for value in (25,50,75,100):
            image=self.pet._tray_quota_icon({'name':'一周'},value,True).pixmap(QSize(64,64)).toImage()
            counts.append(sum(image.pixelColor(x,y).name()==QColor(TRAY_WEEK).name()
                              for y in range(64) for x in range(64)))
        self.assertTrue(all(a<b for a,b in zip(counts,counts[1:])))


if __name__=='__main__':
    unittest.main()
