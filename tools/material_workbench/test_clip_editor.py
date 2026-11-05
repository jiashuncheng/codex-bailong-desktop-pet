from pathlib import Path
import os,tempfile,time,unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from PIL import Image,ImageDraw
from media import write_animation,frames
from clip_editor import ClipEditor

APP=QApplication.instance() or QApplication([])
def wait(check,seconds=10):
    stop=time.monotonic()+seconds
    while time.monotonic()<stop:
        APP.processEvents()
        if check():return True
        time.sleep(.01)
    return False

class ClipEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.input=self.root/'input';self.input.mkdir()
        self.path=self.input/'source.webp';seq=[]
        for i,ms in enumerate((40,80,120,160)):
            image=Image.new('RGBA',(80,100));ImageDraw.Draw(image).ellipse((10+i*5,10,60,90),fill=(150,50+i*30,200,255));seq.append((image,ms))
        write_animation(self.path,seq)
        self.dialog=ClipEditor([str(self.path)],dict(input_dir=str(self.input),state_dir=str(self.root/'state')))
        self.dialog.show();self.assertTrue(wait(lambda:self.dialog.worker is None and self.dialog.list.count()==1))
    def tearDown(self):
        self.dialog.reject();wait(lambda:self.dialog.worker is None);self.dialog.close();APP.processEvents();self.tmp.cleanup()
    def test_frame_markers_use_start_and_end_of_current_variable_duration_frame(self):
        d=self.dialog;d.canvas.index=1;d.set_start_here();d.canvas.index=2;d.set_end_here()
        self.assertEqual((d.current().start_ms,d.current().end_ms),(40,240));self.assertIn('0.200',d.total.text())
        d.repeat.setValue(3);self.assertIn('0.600',d.total.text())
    def test_copy_remove_and_order_are_used_by_the_export_plan(self):
        d=self.dialog;d.start.setValue(.04);d.copy_current();d.start.setValue(.12)
        self.assertEqual([c.start_ms for c in d.clips()],[40,120])
        item=d.list.takeItem(1);d.list.insertItem(0,item);d.changed()
        self.assertEqual([c.start_ms for c in d.clips()],[120,40]);d.list.setCurrentRow(0);d.remove_current()
        self.assertEqual([c.start_ms for c in d.clips()],[40])
    def test_preview_then_save_is_non_destructive_and_changes_invalidate_result(self):
        d=self.dialog;d.start.setValue(.04);d.end.setValue(.24);d.repeat.setValue(2);d.generate_or_save()
        self.assertTrue(wait(lambda:d.worker is None and d.preview_result is not None));self.assertEqual(d.preview_result['durationMs'],400)
        self.assertEqual(d.generate_button.text(),'保存到素材列表');self.assertFalse(d.mark_start.isEnabled())
        self.assertTrue(d.result_button.isEnabled());d.list.setCurrentRow(-1);d.list.setCurrentRow(0);self.assertFalse(d.showing_result)
        d.result_button.click();self.assertTrue(d.showing_result)
        d.repeat.setValue(3);self.assertEqual(d.generate_button.text(),'重新生成预览')
        self.assertFalse(list(self.input.glob('剪辑*.webp')))
        d.generate_or_save();self.assertTrue(wait(lambda:d.worker is None and d.preview_result['durationMs']==600))
        output=self.input/'剪辑_test.webp';before=self.path.read_bytes()
        with patch('clip_editor.QFileDialog.getSaveFileName',return_value=(str(output),'动画 WebP')):d.generate_or_save()
        self.assertTrue(wait(lambda:d.worker is None and d.saved_path is not None))
        self.assertEqual(d.result(),QDialog.DialogCode.Accepted);self.assertEqual(d.saved_path,str(output.resolve()))
        self.assertTrue(output.exists());self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(sum(ms for im,ms in frames(output)),600)
    def test_invalid_range_disables_generation(self):
        d=self.dialog;d.start.setValue(.3);d.end.setValue(.1)
        self.assertFalse(d.generate_button.isEnabled());self.assertIn('起点',d.total.text())
    def test_cancel_active_probe_closes_after_worker_finishes(self):
        d=self.dialog
        def delayed(path,cancel):
            while not cancel():time.sleep(.005)
            raise InterruptedError('取消')
        with patch('clip_editor.probe',side_effect=delayed):
            d.add_paths([str(self.path)]);self.assertIsNotNone(d.worker);d.close()
            self.assertTrue(wait(lambda:d.worker is None and not d.isVisible()))
