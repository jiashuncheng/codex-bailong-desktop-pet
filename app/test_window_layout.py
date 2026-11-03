"""Character avoidance uses the same target before and after a morph."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtCore import QRect,QRectF,QSize,QEvent
from PySide6.QtWidgets import QApplication,QWidget
from panel_placement import avoid_character,occupied_rect,morph_rect,morph_route
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])


class PlacementTests(unittest.TestCase):
    def test_open_and_close_paths_do_not_cross_the_character(self):
        pet=QRect(1147,672,179,179)
        a=QRectF(1056,233,360,431);z=QRectF(771,520,360,431)
        self.assertTrue(any(morph_rect(a,z,i/100).intersects(QRectF(pet)) for i in range(101)))
        for start,end in ((a,z),(z,a)):
            route=morph_route(start,end,pet);self.assertIsNotNone(route)
            self.assertEqual(morph_rect(start,end,0,route),start)
            self.assertEqual(morph_rect(start,end,1,route),end)
            for i in range(301):self.assertFalse(morph_rect(start,end,i/300,route).intersects(QRectF(pet)))
    def test_report_and_expanded_card_move_to_the_side_as_one_group(self):
        area=QRect(0,33,1470,918);pet=QRect(1147,672,179,179)
        target=avoid_character(QRect(1056,520,360,431),pet,area,487,360)
        self.assertFalse(occupied_rect(target,487,8).intersects(pet.adjusted(-8,-8,8,8)))
        self.assertTrue(area.contains(occupied_rect(target,487,8)))
    def test_edges_negative_monitor_origins_and_scales(self):
        for area in (QRect(0,0,1470,900),QRect(-1920,-120,1920,1080),QRect(0,0,800,600)):
            for corner in ('left','right'):
                pet=QRect(area.left()+20 if corner=='left' else area.right()-199,area.bottom()-199,179,179)
                for size in (QSize(228,174),QSize(360,431),QSize(335,255)):
                    for reserve in (0,min(487,area.height()-size.height())):
                        width=max(268,size.width()) if reserve else 0
                        target=avoid_character(QRect(pet.x(),pet.y()-size.height()-8,size.width(),size.height()),pet,area,reserve,width)
                        overhang=max(0,(width-size.width()+1)//2+8) if reserve else 0
                        whole=occupied_rect(target,reserve,overhang)
                        self.assertTrue(area.contains(whole),(area,pet,target))
                        self.assertFalse(whole.intersects(pet),(area,pet,target))
                        self.assertEqual(target.size(),size)
    def test_safe_original_position_and_no_character_do_not_drift(self):
        area=QRect(0,0,1470,900);pet=QRect(1147,672,179,179);card=QRect(1122,490,228,174)
        self.assertEqual(avoid_character(card,pet,area),card)
        self.assertEqual(avoid_character(card,None,area),card)


class GeometryContractTests(unittest.TestCase):
    def setUp(self):
        self.pet=QWidget();self.pet.settings=dict(character_visible=True,panel_detached=False)
        self.pet.setGeometry(1147,672,179,179);self.pet.show()
        self.b=CompactBubble(self.pet);self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.pet.close()
        self.b.deleteLater();self.pet.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_transition_target_and_final_placement_are_identical(self):
        from desktop import DesktopPet
        area=SimpleNamespace(availableGeometry=lambda:QRect(0,33,1470,918))
        report=SimpleNamespace(requested=True,_host_closing=False,GAP=6,
            reserved_height=lambda size:481,panel_width=lambda rect:360)
        b=self.b;b.expanded=True;b.content.setFixedSize(360,431);b.setFixedSize(360,431);b.report=report
        b.size_transition.complete();b.size_transition.release_landing()
        owner=SimpleNamespace(_visibility_ready=True,enhanced_ready=True,bubble=b,
            settings=self.pet.settings,_materials_missing=False,window_layers=Mock(),card_surface_visible=lambda:True)
        with patch('compact_bubble.QApplication.screenAt',return_value=area):
            before=b.content_geometry(QSize(360,431))
            DesktopPet.position_bubble(owner)
            self.assertEqual(b.geometry(),before)
            self.assertFalse(before.intersects(self.pet.frameGeometry()))
        b.report=None
    def test_pin_toggle_preserves_an_open_report_and_updates_all_windows(self):
        from window_layers import WindowLayers
        from daily_report import DailyReport
        from PySide6.QtCore import Qt
        pet=self.pet;pet.bubble=self.b;pet.settings.update(on_top=True,mouse_through=False)
        layers=WindowLayers(pet);r=DailyReport(self.b);self.b.report=r
        r.open();self.b.size_transition.complete();self.b.size_transition.release_landing()
        r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        try:
            for top in (False,True):
                pet.settings['on_top']=top;layers.apply_flags();APP.processEvents()
                self.assertTrue(r.requested);self.assertTrue(r.isVisible())
                for w in (pet,self.b,r):self.assertEqual(bool(w.windowFlags()&Qt.WindowType.WindowStaysOnTopHint),top)
        finally:layers.shutdown();r.close();self.b.report=None
