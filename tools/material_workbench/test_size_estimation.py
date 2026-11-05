from pathlib import Path
from dataclasses import replace
import tempfile,unittest,hashlib
from PIL import Image,ImageDraw
from clip_editing import Clip,probe,export
from media import write_animation,frames
from size_estimation import estimate,identity,remember_actual,format_estimate,timeline

class SizeEstimateTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def source(self,count=4):
        path=self.root/'source.webp';seq=[]
        for index in range(count):
            image=Image.new('RGBA',(80,100));ImageDraw.Draw(image).rectangle((10+index%7,10,60,85),fill=(100+index%100,60,180,255));seq.append((image,40))
        write_animation(path,seq);info=probe(path);return path,{info.path:info}
    def test_short_clip_estimates_match_real_encoding_and_original_bytes(self):
        path,infos=self.source();clips=[Clip(str(path))];values=estimate(clips,infos,directory=self.root/'cache')
        self.assertEqual(values['lossless']['bytes'],path.stat().st_size);self.assertTrue(values['lossless']['exact'])
        for code in ('q95','q90','q85'):
            output=self.root/(code+'.webp');export(clips,output,infos,encoding=code)
            self.assertTrue(values[code]['exact']);self.assertEqual(values[code]['bytes'],output.stat().st_size)
    def test_sampled_long_clip_is_bounded_and_does_not_change_the_source(self):
        path,infos=self.source(40);before=hashlib.sha256(path.read_bytes()).digest()
        result=estimate([Clip(str(path),40,1560)],infos,codes=['q95'],directory=self.root/'cache')['q95']
        self.assertFalse(result['exact']);self.assertLessEqual(result['sampleFrames'],12);self.assertEqual(result['totalFrames'],38)
        self.assertLessEqual(result['low'],result['bytes']);self.assertLessEqual(result['bytes'],result['high'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before);self.assertFalse(list((self.root/'cache').glob('size-sample-*')))
    def test_actual_cache_and_new_ranges_are_distinguished(self):
        path,infos=self.source();clips=[Clip(str(path))];output=self.root/'q95.webp';result=export(clips,output,infos,encoding='q95')
        remember_actual(self.root/'cache',clips,infos,[result]);value=estimate(clips,infos,codes=['q95'],directory=self.root/'cache')['q95']
        self.assertEqual(value['source'],'previous-export');self.assertEqual(value['bytes'],output.stat().st_size)
        other=[Clip(str(path),40,160,2)];self.assertNotEqual(identity(clips,infos,'q95'),identity(other,infos,'q95'))
        self.assertEqual(len(timeline(other,infos)),6);self.assertEqual(sum(v[2] for v in timeline(other,infos)),240)
    def test_cancel_and_changed_source_do_not_yield_stale_predictions(self):
        path,infos=self.source()
        with self.assertRaises(InterruptedError):estimate([Clip(str(path))],infos,cancel=lambda:True)
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError):estimate([Clip(str(path))],infos)
    def test_format_marks_sampled_ranges_as_predictions(self):
        text=format_estimate(dict(bytes=15_000_000,low=12_000_000,high=20_000_000,exact=False))
        self.assertIn('预计',text);self.assertIn('抽样',text);self.assertIn('–',text)
