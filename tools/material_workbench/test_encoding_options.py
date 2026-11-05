from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
from media import frames,write_animation
from clip_editing import Clip,export,publish_batch
from processed_profile import from_layout,encode,read
from encoding_presets import PRESETS
import updater

class EncodingTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def source(self):
        path=self.root/'source.webp';sequence=[]
        for index in range(4):
            a=np.zeros((96,80,4),np.uint8);yy,xx=np.mgrid[:96,:80]
            a[:,:,0]=(xx*2+index*17)%255;a[:,:,1]=(yy*2+index*23)%255;a[:,:,2]=130
            a[10:80,10+index:65,3]=255;a[8:10,15:60,3]=132;a[80:82,15:60,3]=21
            sequence.append((Image.fromarray(a),[40,80,120,160][index]))
        profile=from_layout(dict(canvas=[80,96],anchor=[40,82]))
        write_animation(path,sequence,xmp=encode(profile));return path
    def test_four_encodings_preserve_alpha_geometry_duration_and_calibration(self):
        path=self.source();original=list(frames(path))
        for code in PRESETS:
            output=self.root/(code+'.webp');report=export([Clip(str(path))],output,encoding=code);decoded=list(frames(output))
            self.assertEqual(report['encoding'],code);self.assertEqual(report['bytes'],output.stat().st_size);self.assertEqual(read(output),read(path))
            self.assertEqual([ms for im,ms in decoded],[40,80,120,160])
            for (left,_),(right,_) in zip(original,decoded):
                self.assertEqual(left.size,right.size);self.assertTrue(np.array_equal(np.asarray(left)[:,:,3],np.asarray(right)[:,:,3]))
                if code=='lossless':self.assertEqual(left.tobytes(),right.tobytes())
    def test_full_lossless_comparison_reuses_original_bytes(self):
        path=self.source();target=self.root/'copy.webp'
        with patch('clip_editing.write_animation',side_effect=AssertionError('must not reencode')):export([Clip(str(path))],target)
        self.assertEqual(path.read_bytes(),target.read_bytes())
    def test_unchanged_processed_source_remains_compact_when_loaded_again(self):
        path=self.source();profile=read(path);record=dict(cache=str(path),processedProfile=profile,transform=dict(scale=1.,anchor=[40,82],sourceSize=[80,96],offset=[0,0]))
        self.assertFalse(updater.preserve_processed_bytes(record,96,[48,82]))
        square=self.root/'square.webp';im=Image.new('RGBA',(96,96));ImageDraw.Draw(im).rectangle((20,20,60,80),fill='purple');im2=im.copy();im2.putpixel((40,40),(200,100,120,255))
        meta=from_layout(dict(canvas=[96,96],anchor=[48,82]));write_animation(square,[(im,100),(im2,100)],xmp=encode(meta),encoding='q95')
        record.update(cache=str(square),processedProfile=meta,transform=dict(scale=1.,anchor=[48,82],sourceSize=[96,96],offset=[0,0]))
        self.assertTrue(updater.preserve_processed_bytes(record,96,[48,82]));record['transform']['scale']=.9;self.assertFalse(updater.preserve_processed_bytes(record,96,[48,82]))
    def test_batch_collision_is_detected_before_saving_any_output(self):
        source=self.source();a=self.root/'a.webp';b=self.root/'b.webp';b.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):publish_batch([(source,a),(source,b)])
        self.assertFalse(a.exists());self.assertEqual(b.read_bytes(),b'keep')
    def test_cancelled_batch_cleans_only_its_own_new_files(self):
        import clip_editing
        source=self.source();a=self.root/'a.webp';b=self.root/'b.webp';stop=[False];original=clip_editing.publish
        def save(*args,**kwargs):original(*args,**kwargs);stop[0]=True
        with patch.object(clip_editing,'publish',side_effect=save):
            with self.assertRaises(InterruptedError):publish_batch([(source,a),(source,b)],cancel=lambda:stop[0])
        self.assertFalse(a.exists());self.assertFalse(b.exists());self.assertTrue(source.exists())
    def test_actual_library_build_reuses_compact_processed_file_byte_for_byte(self):
        import json
        from config_store import load_config
        base=self.root/'base';base.mkdir();idle=Image.new('RGBA',(720,720));ImageDraw.Draw(idle).rectangle((270,150,450,667),fill='purple');idle.save(base/'idle.webp',lossless=True)
        manifest=dict(idle=dict(id='idle',file='idle.webp',durationMs=1000),variants=[])
        (base/'素材清单.json').write_text(json.dumps(manifest),encoding='utf-8')
        source=self.root/'compact.webp';a=Image.new('RGBA',(800,800));ImageDraw.Draw(a).rectangle((300,250,500,707),fill=(140,100,220,255));b=a.copy();b.putpixel((400,400),(200,60,180,255))
        meta=from_layout(dict(canvas=[800,800],anchor=[400,708]));write_animation(source,[(a,100),(b,100)],xmp=encode(meta),encoding='q95')
        cfg=load_config(Path(__file__).parent/'配置.json');cfg.update(state_dir=str(self.root/'state'),data_dir=str(self.root/'data'),settle_seconds=0,extra_scale=1,adjustments={})
        matcher=type('Matcher',(),{'match':lambda *a:None})();record=updater.prepare(source,cfg,matcher)
        with patch.object(updater,'write_animation',side_effect=AssertionError('unchanged processed input must not be reencoded')):
            release,_,_=updater.build_runtime(cfg,base,manifest,{'compact':record})
        self.assertEqual((release/'custom/compact.webp').read_bytes(),source.read_bytes())
    def test_opaque_rectangles_on_transparent_canvas_keep_alpha_in_compact_modes(self):
        for code in ('q95','q90','q85'):
            source=self.root/(code+'.webp');a=Image.new('RGBA',(160,160));ImageDraw.Draw(a).rectangle((40,40,100,140),fill='purple');b=a.copy();b.putpixel((70,70),(200,60,180,255))
            write_animation(source,[(a,100),(b,100)],encoding=code)
            for image,ms in frames(source):self.assertEqual(image.getchannel('A').getextrema(),(0,255))
