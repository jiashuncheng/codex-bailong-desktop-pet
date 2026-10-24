import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import ctypes,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ctypes import wintypes
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPixmap,QPainter
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent
from desktop import DesktopPet
from native_coordinates import client_position,message_position
APP=QApplication.instance() or QApplication([])

class CoordinatesTests(unittest.TestCase):
    def api(self,origin,size,fail=None):
        def convert(hwnd,p):
            p=ctypes.cast(p,ctypes.POINTER(wintypes.POINT)).contents
            p.x-=origin[0];p.y-=origin[1];return fail!='convert'
        def rect(hwnd,p):
            r=ctypes.cast(p,ctypes.POINTER(wintypes.RECT)).contents
            r.left=r.top=0;r.right,r.bottom=size;return fail!='rect'
        return SimpleNamespace(ScreenToClient=convert,GetClientRect=rect)
    def test_physical_client_to_logical_does_not_scale_monitor_origin(self):
        for origin in ((0,0),(-1920,-500),(2560,200)):
            for size in ((256,256),(320,320),(384,384),(512,512),(383,387)):
                result=client_position(42,origin[0]+73,origin[1]+91,256,256,self.api(origin,size))
                self.assertEqual(result,(73*256/size[0],91*256/size[1]))
    def test_failed_or_zero_client_area_delegates_instead_of_transparent(self):
        for fail in ('convert','rect'):
            self.assertIsNone(client_position(42,3,4,256,256,self.api((0,0),(320,320),fail)))
        self.assertIsNone(client_position(42,3,4,256,256,self.api((0,0),(0,320))))
    def test_signed_negative_screen_coordinates(self):
        self.assertEqual(message_position((-1200&0xffff)|((-350&0xffff)<<16)),(-1200,-350))

class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch(m+'.'+k,root/('settings.json' if k=='CONFIG' else '')) for m in ('desktop','enhanced') for k in ('CONFIG','STATE_DIR')]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.tick.stop();self.pet.motion_timer.stop()
        self.pet.apply_settings(dict(wandering=False,random_actions=False,drag_physics=False,sound=False),save=False)
        self.pet.show();APP.processEvents()
    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def drag(self):
        self.press=SimpleNamespace(button=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(200,200))
        self.move=SimpleNamespace(buttons=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(240,230))
        self.pet.mousePressEvent(self.press);self.pet.mouseMoveEvent(self.move);self.assertTrue(self.pet.dragging)
    def test_drawing_and_hit_testing_share_mirror_scale_offset_and_press_transform(self):
        p=self.pet;im=QImage(256,256,QImage.Format.Format_ARGB32);im.fill(Qt.GlobalColor.transparent)
        q=QPainter(im);q.fillRect(35,25,80,210,Qt.GlobalColor.white);q.end()
        p.frames=[QPixmap.fromImage(im)];p.index=0;p._hit_image=im;p.current=dict(renderScale=.9,renderOffset=[.04,-.02])
        for facing in (1,-1):
            p.walk_direction=facing
            for elapsed in (None,.04,.08,.16,.28,.40,.49):
                p.press_feedback=100-elapsed if elapsed is not None else 0
                with patch('desktop.time.monotonic',return_value=100):
                    target=QImage(256,256,QImage.Format.Format_ARGB32);target.fill(Qt.GlobalColor.transparent)
                    q=QPainter(target);p.draw_frame(q,QRectF(0,0,256,256));q.end()
                    for y in range(5,251,5):
                        for x in range(5,251,5):
                            neighborhood=[target.pixelColor(x+dx,y+dy).alpha() for dx,dy in ((0,0),(-2,0),(2,0),(0,-2),(0,2))]
                            if min(neighborhood)>=240:self.assertTrue(p.alpha_hit(x+.5,y+.5),(facing,elapsed,x,y))
                            elif max(neighborhood)==0:self.assertFalse(p.alpha_hit(x+.5,y+.5),(facing,elapsed,x,y))
    def test_outside_render_rectangle_never_truncates_negative_coordinate_into_first_pixel(self):
        p=self.pet;im=QImage(8,8,QImage.Format.Format_ARGB32);im.fill(Qt.GlobalColor.white)
        p.frames=[QPixmap.fromImage(im)];p._hit_image=im;p.current=dict(renderScale=.5,renderOffset=[0,0]);p.press_feedback=0
        p.walk_direction=1
        self.assertFalse(p.alpha_hit(63.9,150));self.assertTrue(p.alpha_hit(64,150))
        self.assertFalse(p.alpha_hit(-.1,150));self.assertFalse(p.alpha_hit(256,150))
    def test_capture_loss_finishes_drag_without_throw_or_false_click(self):
        self.drag();APP.sendEvent(self.pet,QEvent(QEvent.Type.UngrabMouse));APP.processEvents()
        self.assertFalse(self.pet.dragging);self.assertEqual(self.pet.gate.state,'idle')
        self.assertFalse(self.pet.throwing);self.assertFalse(self.pet.click_timer.isActive())
        self.assertEqual(self.pet.mode,'idle')
    def test_normal_release_wins_over_deferred_ungrab(self):
        self.drag();APP.sendEvent(self.pet,QEvent(QEvent.Type.UngrabMouse));self.pet.mouseReleaseEvent(self.press)
        APP.processEvents();self.assertEqual(self.pet.mode,'landing');self.assertFalse(self.pet.dragging)
    def test_late_release_after_cancellation_is_not_a_click(self):
        self.drag();self.pet.cancel_pointer();self.pet.mouseReleaseEvent(self.press)
        APP.processEvents();self.assertFalse(self.pet.click_timer.isActive());self.assertFalse(self.pet.dragging)
        self.assertFalse(self.pet.throwing)
    def test_old_ungrab_does_not_cancel_new_press(self):
        self.drag();APP.sendEvent(self.pet,QEvent(QEvent.Type.UngrabMouse));self.pet.mouseReleaseEvent(self.press)
        self.pet.mousePressEvent(self.press);APP.processEvents();self.assertTrue(self.pet._pointer_pressed)
    def test_hide_and_input_affecting_settings_cancel_drag_safely(self):
        for value in (dict(no_move=True),dict(mouse_through=True),dict(scale=1.2),dict(on_top=False)):
            self.pet.apply_settings(dict(no_move=False,mouse_through=False,scale=1,on_top=True),save=False)
            self.drag();self.pet.apply_settings(value,save=False)
            self.assertFalse(self.pet.dragging,value);self.assertFalse(self.pet.throwing)
        self.pet.apply_settings(dict(no_move=False,mouse_through=False),save=False)
        self.drag();self.pet.hide();self.assertFalse(self.pet.dragging)
    def test_completion_is_retained_when_drag_is_cancelled(self):
        self.drag()
        with patch.object(self.pet,'notify'),patch.object(self.pet,'refresh_quota'):
            self.pet.on_activity(dict(kind='complete',session='example',turn='one'))
        self.pet.cancel_pointer();self.assertTrue(self.pet.bubble.status_indicator.unread)
        self.assertIsNotNone(self.pet.pending_completion)
    def test_no_move_locks_drag_but_still_allows_clicks(self):
        self.pet.apply_settings(dict(no_move=True),save=False)
        self.press=SimpleNamespace(button=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(200,200))
        self.pet.mousePressEvent(self.press);self.pet.mouseReleaseEvent(self.press)
        self.assertTrue(self.pet.click_timer.isActive());self.assertFalse(self.pet.dragging)
    def test_character_switch_keeps_navigation_alive_and_shutdown_closes_it(self):
        nav=self.pet.codex_navigation
        self.pet.switch_character('builtin');self.assertIs(self.pet.codex_navigation,nav);self.assertFalse(nav.closed)
        with patch.object(nav,'_start') as start:
            self.assertTrue(nav.open());start.assert_called_once()
        self.pet.close();self.assertTrue(nav.closed)

if __name__=='__main__':unittest.main()
