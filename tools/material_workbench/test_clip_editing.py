from pathlib import Path
import hashlib,tempfile,unittest
from PIL import Image,ImageDraw
from clip_editing import Clip,probe,export,publish
from media import frames,write_animation

class ClipEditingTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def source(self,name='source.webp',size=(40,60),alpha=True,durations=(40,80,120,160)):
        path=self.root/name;sequence=[]
        for i,ms in enumerate(durations):
            image=Image.new('RGBA',size,(0,0,0,0) if alpha else (0,255,0,255))
            ImageDraw.Draw(image).rectangle((8+i,10,20+i,40),fill=(120+i*25,50,210,128 if alpha else 255))
            sequence.append((image,ms))
        write_animation(path,sequence);return path
    def read(self,path):return [(im.copy(),ms) for im,ms in frames(path)]
    def test_trim_uses_true_variable_frame_timestamps_and_partial_boundary_frames(self):
        path=self.source();original=self.read(path);before=path.read_bytes();output=self.root/'trim.webp'
        result=export([Clip(str(path),50,300)],output);actual=self.read(output)
        self.assertEqual([ms for im,ms in actual],[70,120,60]);self.assertEqual(result['durationMs'],250)
        self.assertEqual([im.tobytes() for im,ms in actual],[im.tobytes() for im,ms in original[1:]])
        self.assertEqual(path.read_bytes(),before);self.assertEqual(result['size'],[40,60])
    def test_reordering_and_repeat_keep_alpha_pixels_and_durations(self):
        a=self.source();b=self.source('other.webp',durations=(70,90));output=self.root/'join.webp'
        expected=self.read(b)+self.read(a)[1:3]*2
        export([Clip(str(b)),Clip(str(a),40,240,2)],output)
        actual=self.read(output)
        # WebP may coalesce equal consecutive frames across a join. Compare the
        # visible timeline at every millisecond, rather than requiring redundant frames.
        timeline=lambda seq:[im.tobytes() for im,ms in seq for _ in range(ms)]
        self.assertEqual(timeline(actual),timeline(expected))
        self.assertEqual(actual[0][0].getchannel('A').getextrema(),(0,128))
    def test_different_transparent_canvases_only_add_bottom_centered_padding(self):
        small=self.source(size=(40,60));large=self.source('large.webp',size=(52,80));out=self.root/'padded.webp'
        export([Clip(str(small)),Clip(str(large))],out);actual=self.read(out);source=self.read(small)
        for (image,ms),(expected,_) in zip(actual,source):
            self.assertEqual(image.size,(52,80));self.assertEqual(image.crop((6,20,46,80)).tobytes(),expected.tobytes())
            self.assertEqual(image.crop((0,0,52,20)).getchannel('A').getextrema(),(0,0))
    def test_reject_mixed_alpha_and_opaque_and_inconsistent_raw_canvases(self):
        alpha=self.source();raw=self.source('raw.webp',alpha=False);other=self.source('wide.webp',size=(70,60),alpha=False)
        for clips in ([Clip(str(alpha)),Clip(str(raw))],[Clip(str(raw)),Clip(str(other))]):
            with self.assertRaises(ValueError):export(clips,self.root/'bad.webp')
        self.assertFalse((self.root/'bad.webp').exists())
    def test_exact_end_frame_is_excluded(self):
        path=self.source();out=self.root/'boundary.webp';export([Clip(str(path),0,120)],out)
        self.assertEqual([ms for im,ms in self.read(out)],[40,80])
    def test_invalid_and_too_long_ranges_do_not_produce_output(self):
        path=self.source();out=self.root/'bad.webp'
        for clip in (Clip(str(path),200,100),Clip(str(path),-1,40),Clip(str(path),0,401),Clip(str(path),0,300,0),Clip(str(path),0,300,21),Clip(str(path),0,40)):
            with self.assertRaises(ValueError):export([clip],out)
            self.assertFalse(out.exists())
        with self.assertRaises(ValueError):export([Clip(str(path),0,400,20)]*8,out)
    def test_existing_file_and_original_source_are_never_overwritten(self):
        path=self.source();before=hashlib.sha256(path.read_bytes()).digest()
        with self.assertRaises(FileExistsError):export([Clip(str(path))],path)
        target=self.root/'existing.webp';target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):publish(path,target)
        self.assertEqual(target.read_bytes(),b'keep');self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
    def test_cancel_mid_export_removes_temporary_and_new_output(self):
        path=self.source();flag=[False];out=self.root/'cancel.webp'
        def progress(n,total):flag[0]=n==2
        with self.assertRaises(InterruptedError):export([Clip(str(path))],out,cancel=lambda:flag[0],progress=progress)
        self.assertFalse(out.exists());self.assertFalse(list(self.root.glob('.bailong-edit-*')))
    def test_changed_source_invalidates_previously_probed_metadata(self):
        path=self.source();info=probe(path);path.write_bytes(path.read_bytes()+b'new')
        with self.assertRaises(ValueError):export([Clip(str(path))],self.root/'bad.webp',{str(path.resolve()):info})
    def test_probe_supplies_actual_time_to_frame_mapping(self):
        info=probe(self.source());self.assertEqual(info.starts,[0,40,120,240,400])
        self.assertEqual([info.index_at(v) for v in (0,39,40,119,120,399,400)],[0,0,1,1,2,3,3])
    def test_green_mp4_can_be_trimmed_at_native_resolution_before_matting(self):
        import imageio_ffmpeg
        path=self.root/'green.mp4'
        writer=imageio_ffmpeg.write_frames(str(path),(64,96),fps=24,codec='libx264',macro_block_size=1)
        writer.send(None)
        try:
            for index in range(8):
                image=Image.new('RGB',(64,96),(0,255,0));ImageDraw.Draw(image).rectangle((10+index,15,35+index,85),fill=(150+index*8,60,200))
                writer.send(image.tobytes())
        finally:writer.close()
        info=probe(path);self.assertEqual(info.size,(64,96));self.assertFalse(info.alpha)
        output=self.root/'green-trim.webp';result=export([Clip(str(path),0,250)],output)
        self.assertEqual(result['size'],[64,96]);self.assertEqual(result['durationMs'],250)
        expected=self.read(path);actual=self.read(output)
        for (left,_),(right,_) in zip(expected,actual):self.assertEqual(left.tobytes(),right.tobytes())
