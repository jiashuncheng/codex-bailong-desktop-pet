"""Geometry, native input mapping and mode handoffs of scaled status panels."""
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QRect
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QToolButton,QWidget
from compact_bubble import CompactBubble
from surface_morph import SurfaceState,complete_frame

APP=QApplication.instance() or QApplication([])

class PanelScaleTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def finish(self):
        self.b.size_transition.complete();self.b.size_transition.release_landing();APP.processEvents()
    def click(self,widget):
        host=self.b.scale_host
        point=host.mapFromGlobal(widget.mapToGlobal(widget.rect().center()))
        QTest.mouseClick(host.viewport(),Qt.MouseButton.LeftButton,pos=point);APP.processEvents()
    def test_normal_and_capsule_scale_geometry_and_return_to_original_without_drift(self):
        b=self.b
        for mode,base_width in [('auto',268),('mini',246),('minimal',54)]:
            b.set_mode(mode);self.finish()
            for role,panel in ((.4,.8),(.7,.85),(1.,1.),(1.5,1.25),(2.,1.5),(2.5,1.5),(1.,1.)):
                b.set_role_scale(role);self.finish()
                self.assertAlmostEqual(b.width(),base_width*panel,delta=1)
                self.assertEqual(b.size(),b.visual_size())
                self.assertTrue(b.content.isVisible())
                image=complete_frame(b);self.assertAlmostEqual(image.deviceIndependentSize().width(),b.width(),delta=1)
                b.grab() # Exercise the actual scene renderer too.
    def test_scaled_capsule_click_opens_unscaled_details_and_scales_on_return(self):
        b=self.b;b.set_role_scale(2);b.set_mode('mini');self.finish()
        self.assertEqual(b.width(),369)
        self.click(b.island);self.finish()
        self.assertFalse(b.is_island());self.assertEqual(b.width(),402)
        details=b.content.findChild(QToolButton,'bubble_details')
        self.assertIsNotNone(details);self.click(details);self.finish()
        self.assertTrue(b.expanded);self.assertEqual(b.ui_scale,1.)
        self.assertEqual(b.width(),360)
        b.toggle_details();self.finish();self.assertEqual(b.width(),402)
    def test_scaled_button_uses_transformed_hitbox(self):
        b=self.b;b.set_role_scale(1.5);b.set_mode('mini');self.finish()
        clicks=[];b.shortcutRequested.connect(lambda:clicks.append(True))
        self.click(b.shortcut_button);self.assertEqual(clicks,[True]);self.assertTrue(b.is_island())
    def test_capture_keeps_scaled_glyph_and_separate_satellites(self):
        b=self.b;b.set_role_scale(2);b.set_mode('mini');self.finish()
        capture=SurfaceState.capture(b)
        self.assertEqual(capture.rect.width(),234);self.assertEqual(capture.icon_rect.width(),24)
        self.assertEqual(len(capture.satellites),2)
        self.assertEqual(capture.satellites[0][0].width(),60)
        b.set_mode('auto');self.finish()
        self.assertEqual(SurfaceState.capture(b).rect.width(),402)
    def test_hover_mapping_still_pauses_rotation(self):
        b=self.b
        for sid in ('a','b','c'):b.roster.observe(dict(session=sid,state='working'))
        b.set_role_scale(2);b.set_mode('mini');self.finish();page=b.roster.page
        center=b.island.mapToGlobal(b.island.rect().center())
        with patch('PySide6.QtGui.QCursor.pos',return_value=center):b._auto_cycle_conversations()
        self.assertEqual(b.roster.page,page)
        with patch('PySide6.QtGui.QCursor.pos',return_value=QPoint(-10000,-10000)):b._auto_cycle_conversations()
        self.assertNotEqual(b.roster.page,page)
    def test_hide_pauses_embedded_animation_and_show_restores_it(self):
        b=self.b;b.set_role_scale(2);b.set_mode('mini');self.finish()
        b.status_indicator.observe(dict(state='working',active=1));self.assertTrue(b.status_indicator.timer.isActive())
        b.hide();APP.processEvents();self.assertFalse(b.status_indicator.timer.isActive())
        b.show();APP.processEvents();self.assertTrue(b.status_indicator.timer.isActive())
    def test_scaled_capsule_keeps_transparent_outside_corners(self):
        b=self.b;b.set_role_scale(1.6);b.set_mode('mini');self.finish()
        image=b.grab().toImage();self.assertEqual(image.pixelColor(0,0).alpha(),0)
    def test_return_from_editor_keeps_scaled_content_painting(self):
        b=self.b
        for role in (.7,1.6,1.):
            b.set_role_scale(role);self.finish()
            for mode in ('auto','mini','minimal'):
                with self.subTest(role=role,mode=mode):
                    b.set_mode(mode);self.finish()
                    b.show_page('settings',QWidget());self.finish()
                    self.assertEqual(b.ui_scale,1.)
                    self.assertTrue(b.content.updatesEnabled())
                    b.return_to_status();self.finish()
                    self.assertTrue(b.content.updatesEnabled())
                    self.assertTrue(b.content.isVisible())
                    # A background alone is opaque too. Require the restored
                    # live content to paint actual non-transparent pixels.
                    frame=b.content.grab().toImage()
                    self.assertTrue(any(frame.pixelColor(x,y).alpha()>0
                        for y in range(0,frame.height(),4) for x in range(0,frame.width(),4)))
    def test_shell_update_gate_reaches_embedded_content(self):
        b=self.b;b.set_role_scale(.7);self.finish()
        b.setUpdatesEnabled(False)
        try:self.assertFalse(b.content.updatesEnabled())
        finally:b.setUpdatesEnabled(True)
        self.assertTrue(b.content.updatesEnabled())
    def test_scaling_status_does_not_take_focus_from_another_window(self):
        other=QWidget();other.show();QApplication.setActiveWindow(other);APP.processEvents()
        try:
            self.b.set_role_scale(1.6);APP.processEvents();self.assertIs(APP.activeWindow(),other)
        finally:other.close();other.deleteLater()
    def test_scaled_conversation_name_still_opens_matching_session(self):
        b=self.b;b.roster.observe(dict(session='a',state='working',title='正在执行的测试'))
        b.set_role_scale(1.5);self.finish();row=b.status_view.rows['a'];opened=[]
        b.conversationRequested.connect(opened.append)
        host=b.scale_host;point=host.mapFromGlobal(row.mapToGlobal(QPoint(3,row.line_height//2)))
        QTest.mouseClick(host.viewport(),Qt.MouseButton.LeftButton,pos=point);APP.processEvents()
        self.assertEqual(opened,['a']);self.assertFalse(b.expanded)
    def test_detached_scaled_capsule_drag_uses_screen_pixels_and_does_not_expand(self):
        class Owner:
            settings=dict(panel_detached=True,character_visible=True)
            enhanced_ready=False
            def __init__(self):self.moves=[];self.saved=0
            def isVisible(self):return True
            def card_geometry(self,size):return QRect(100,100,size.width(),size.height())
            def move_card(self,point):self.moves.append(point)
            def save_settings(self):self.saved+=1
        b=self.b;owner=Owner();b._owner=owner;b.set_role_scale(1.5);b.set_mode('mini');self.finish()
        host=b.scale_host;point=host.mapFromGlobal(b.island.mapToGlobal(b.island.rect().center()));start=b.pos()
        QTest.mousePress(host.viewport(),Qt.MouseButton.LeftButton,pos=point)
        end=point+QPoint(30,15)
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(host.viewport().mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        APP.sendEvent(host.viewport(),event)
        QTest.mouseRelease(host.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.assertTrue(owner.moves);self.assertEqual(owner.moves[-1],start+QPoint(30,15))
        self.assertEqual(owner.saved,1);self.assertTrue(b.is_island())
        b._owner=None

if __name__=='__main__':unittest.main()
