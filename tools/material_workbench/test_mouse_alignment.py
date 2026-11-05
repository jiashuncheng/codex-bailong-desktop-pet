from pathlib import Path
import os,json,time,unittest,tempfile
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent,QWheelEvent
from PySide6.QtWidgets import QApplication
from PIL import Image,ImageDraw
from alignment_editor import AlignmentDialog
from config_store import load_config
from media import write_animation
APP=QApplication.instance() or QApplication([])
def wait(check,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        APP.processEvents()
        if check():return True
        time.sleep(.005)
    return False

class MouseAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);cfg=load_config(Path(__file__).parent/'配置.json');cfg['data_dir']=str(self.root/'data');cfg['adjustments']={}
        self.path=self.root/'clip.webp';seq=[]
        for n in range(8):
            im=Image.new('RGBA',(100,160));ImageDraw.Draw(im).rectangle((20+n%3,10,80,150),fill=(100+n*10,80,200,255));seq.append((im,40))
        write_animation(self.path,seq)
        record=dict(source=str(self.path),cache=str(self.path),name='测试',transform=dict(scale=1.,anchor=[50,151],sourceSize=[100,160]),info=dict(union=[20,10,81,151],frames=8,durationMs=320,size=[100,160]))
        row=dict(action='clip',processed_action='clip',name='测试',file='clip.webp',path=str(self.path),record=record,all_records={'clip':record},meta=dict(frames=8,fps=25,duration=.32))
        self.dialog=AlignmentDialog(row,cfg);self.dialog.show();self.canvas=self.dialog.canvas
        self.assertTrue(wait(lambda:self.canvas.image is not None));self.canvas.set_playing(False);self.assertEqual(self.canvas.image.pixelColor(0,0).alpha(),0)
    def tearDown(self):self.dialog.reject();APP.processEvents();self.tmp.cleanup()
    def point(self):return self.canvas.drawing_rects()[1].center()
    def mouse(self,kind,point,button=Qt.MouseButton.LeftButton,buttons=Qt.MouseButton.LeftButton):
        event=QMouseEvent(kind,point,point,button,buttons,Qt.KeyboardModifier.NoModifier);APP.sendEvent(self.canvas,event);APP.processEvents()
    def wheel(self,delta=120,fine=False,pixel=0):
        point=self.point();event=QWheelEvent(point,point,QPoint(0,pixel),QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.ShiftModifier if fine else Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        APP.sendEvent(self.canvas,event);APP.processEvents()
    def test_drag_updates_numeric_position_in_both_view_modes(self):
        for mode in ('适合窗口','桌宠实际尺寸'):
            self.dialog.reset_values();self.dialog.view.setCurrentText(mode);point=self.point();factor=self.canvas.drawing_rects()[2]
            self.assertTrue(self.canvas.hit_subject(point));self.mouse(QEvent.Type.MouseButtonPress,point)
            self.mouse(QEvent.Type.MouseMove,point+QPointF(20,12),Qt.MouseButton.NoButton)
            self.assertAlmostEqual(self.dialog.x.value(),round(20/factor*self.dialog.factor,1),places=1)
            self.assertAlmostEqual(self.dialog.y.value(),round(12/factor*self.dialog.factor,1),places=1)
            target=self.canvas.drawing_rects()[1];self.assertAlmostEqual(target.center().x()-point.x(),20,delta=.2)
            self.mouse(QEvent.Type.MouseButtonRelease,point+QPointF(20,12),buttons=Qt.MouseButton.NoButton)
            self.assertIsNone(self.canvas.drag_origin)
    def test_drag_freezes_view_scale_when_output_canvas_expands(self):
        point=self.point();factor=self.canvas.drawing_rects()[2];old_side=self.canvas.scene['canvas'][0]
        self.mouse(QEvent.Type.MouseButtonPress,point);destination=point+QPointF(210,-40)
        self.mouse(QEvent.Type.MouseMove,destination,Qt.MouseButton.NoButton)
        self.assertGreater(self.canvas.scene['canvas'][0],old_side);self.assertEqual(self.canvas.drawing_rects()[2],factor)
        self.assertAlmostEqual(self.canvas.drawing_rects()[1].center().x()-point.x(),210,delta=.2)
        self.mouse(QEvent.Type.MouseButtonRelease,destination,buttons=Qt.MouseButton.NoButton)
        self.assertTrue(self.dialog.valid)
    def test_drag_pauses_and_resumes_original_playback(self):
        self.canvas.set_playing(True);point=self.point();self.mouse(QEvent.Type.MouseButtonPress,point);self.assertFalse(self.canvas.playing)
        self.mouse(QEvent.Type.MouseButtonRelease,point+QPointF(2,2),buttons=Qt.MouseButton.NoButton);self.assertTrue(self.canvas.playing)
    def test_transparent_background_does_not_start_a_drag(self):
        point=self.canvas.drawing_rects()[1].topLeft()+QPointF(2,2);self.assertFalse(self.canvas.hit_subject(point));self.mouse(QEvent.Type.MouseButtonPress,point)
        self.mouse(QEvent.Type.MouseMove,point+QPointF(30,30),Qt.MouseButton.NoButton)
        self.mouse(QEvent.Type.MouseButtonRelease,point+QPointF(30,30),buttons=Qt.MouseButton.NoButton)
        self.assertEqual([self.dialog.x.value(),self.dialog.y.value()],[0,0]);self.assertIsNone(self.canvas.drag_origin)
    def test_wheel_and_shift_wheel_update_numeric_scale(self):
        self.wheel();self.assertEqual(self.dialog.scale.value(),102.)
        self.wheel(-120);self.assertEqual(self.dialog.scale.value(),100.)
        self.wheel(fine=True);self.assertEqual(self.dialog.scale.value(),100.2)
        self.assertAlmostEqual(self.dialog.result_adjustment['scale'],1.002)
        self.dialog.scale.setValue(250);self.wheel();self.assertEqual(self.dialog.scale.value(),250)
        self.dialog.scale.setValue(25);self.wheel(-120);self.assertEqual(self.dialog.scale.value(),25)
    def test_trackpad_pixel_scroll_and_numeric_edits_keep_preview_in_sync(self):
        self.wheel(delta=0,pixel=20);self.assertEqual(self.dialog.scale.value(),101)
        self.dialog.x.setValue(-6);self.dialog.y.setValue(9)
        self.assertAlmostEqual(self.dialog.result_adjustment['offset'][0]*self.dialog.factor,-6)
        self.assertAlmostEqual(self.dialog.result_adjustment['offset'][1]*self.dialog.factor,9)
        self.assertEqual(self.dialog.config['adjustments'],{})
    def test_lost_mouse_capture_clears_drag_without_accidental_resume(self):
        point=self.point();self.canvas.set_playing(True);self.mouse(QEvent.Type.MouseButtonPress,point)
        APP.sendEvent(self.canvas,QEvent(QEvent.Type.UngrabMouse));self.assertIsNone(self.canvas.drag_origin);self.assertIsNone(self.canvas.gesture_factor);self.assertFalse(self.canvas.playing)
        self.mouse(QEvent.Type.MouseMove,point+QPointF(50,50),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton)
        self.assertEqual([self.dialog.x.value(),self.dialog.y.value()],[0,0])

if __name__=='__main__':unittest.main(verbosity=2)
