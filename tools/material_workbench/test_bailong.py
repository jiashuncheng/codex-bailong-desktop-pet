from pathlib import Path
import os,tempfile,unittest,json,copy,sys
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
import updater as u
from media import write_animation,frames,atomic_json,digest
from webp_padding import pad_webp
from cartoon import CartoonFace,calibrate,body_anchor

class WhiteDragonTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def sample(self):
        im=Image.new('RGBA',(80,80));ImageDraw.Draw(im).ellipse((12,12,60,66),fill=(150,110,230,255));return im
    def test_webp_padding_preserves_every_visible_pixel_and_timing(self):
        source=self.root/'source.webp';dest=self.root/'padded.webp'
        seq=[]
        for i in range(12):
            a=self.sample();ImageDraw.Draw(a).rectangle((20+i,25,25+i,40),fill=(230,90,120,200));seq.append((a,41+i%2))
        write_animation(source,seq);result=pad_webp(source,dest,104,12)
        self.assertTrue(result['container_only'])
        left=list(frames(source));right=list(frames(dest));self.assertEqual(len(left),len(right))
        for (a,ms),(b,ms2) in zip(left,right):
            self.assertEqual(ms,ms2);self.assertEqual(b.size,(104,104))
            original=np.asarray(a);crop=np.asarray(b.crop((12,12,92,92)));visible=original[:,:,3]>0
            self.assertTrue(np.array_equal(original[:,:,3],crop[:,:,3]))
            self.assertTrue(np.array_equal(original[visible],crop[visible]))
            self.assertEqual(b.getchannel('A').crop((0,0,104,12)).getextrema(),(0,0))
    def test_invalid_padding_is_rejected(self):
        source=self.root/'source.webp';write_animation(source,[(self.sample(),100),(Image.new('RGBA',(80,80)),100)])
        with self.assertRaises(ValueError):pad_webp(source,self.root/'bad.webp',100,9)
    def test_cartoon_matching_ignores_overhead_prop(self):
        matcher=CartoonFace(u.BASE/'白龙标准参考.png')
        ref=matcher.reference;image=Image.new('RGBA',(1100,1500));scaled=ref.resize((900,900),Image.Resampling.LANCZOS);image.paste(scaled,(100,500))
        ImageDraw.Draw(image).ellipse((50,50,1050,420),fill=(180,150,220,255))
        result=matcher.match(image);self.assertGreater(result['score'],.68)
        self.assertAlmostEqual(result['scale'],1.25,delta=.09)
    def test_unreliable_face_does_not_silently_guess_scale(self):
        with self.assertRaises(ValueError):calibrate([dict(scale=1,score=.2)])
        self.assertEqual(calibrate([],{'scale':.8})[0],.8)
    def test_face_size_changes_are_rejected(self):
        with self.assertRaises(ValueError):calibrate([dict(scale=1,score=.9),dict(scale=1.6,score=.9)])
    def test_detached_snow_does_not_move_person_foot_anchor(self):
        im=self.sample();ImageDraw.Draw(im).rectangle((5,74,15,79),fill='white')
        anchor=body_anchor(im,dict(box=[20,20,50,40]))
        self.assertLess(anchor[1],74);self.assertEqual(im.getpixel((10,77)),(255,255,255,255))
    def test_geometry_adds_space_without_changing_person_scale(self):
        r=dict(transform=dict(scale=1,anchor=[400,1000]),info=dict(union=[0,0,900,1100]))
        before=copy.deepcopy(r);side,pad,anchor=u.geometry({'a':r})
        self.assertGreater(side,800);self.assertEqual(r,before);self.assertEqual(anchor[1],668+pad)
    def test_source_edge_is_warning_but_output_clipping_is_error(self):
        p=self.root/'edge.webp';a=self.sample();a.putpixel((0,1),(200,80,120,255));b=a.copy();b.putpixel((30,30),(230,100,200,255))
        write_animation(p,[(a,100),(b,100)]);info,_=u.decode_check(p)
        self.assertEqual(info['sourceEdgeTouchFrames'],2)
        with self.assertRaises(ValueError):u.decode_check(p,allow_source_edge=False)
    def test_original_action_metadata_and_nested_seams_are_retained(self):
        manifest=dict(idle=dict(id='idle',file='old.webp',renderScale=1,renderOffset=[0,0]),
            workAnimations=[dict(id='work02',file='work.webp',sustained=dict(start=4,end=9,seamFile='seam.webp'))])
        before=copy.deepcopy(manifest);u.shift_render_metadata(manifest,800,40)
        self.assertEqual(manifest['workAnimations'][0]['sustained'],before['workAnimations'][0]['sustained'])
        self.assertEqual(manifest['idle']['renderOffset'],[0.,0.])
        self.assertEqual(manifest['idle']['file'],'old.webp')
    def test_scan_excludes_processed_outputs_and_keeps_stable_action_id(self):
        src=self.root/'input';src.mkdir();out=src/'已处理';out.mkdir()
        for name in ('雨伞龙娘_透明有损预览_784x1168_24fps.webm','雨伞龙娘_无损母版.webm'):(src/name).write_bytes(b'test')
        (out/'not-input.webp').write_bytes(b'out')
        result=u.scan(dict(input_dir=str(src),output_dir=str(out),recursive=True))
        self.assertEqual(len(result),1);self.assertIn('无损',next(iter(result.values())).name)
    def test_deployment_failure_restores_builtin_selection(self):
        data=self.root/'data';data.mkdir();release=self.root/'release';release.mkdir()
        (release/'new.webp').write_bytes(b'new');atomic_json(release/'文件校验.json',{'new.webp':digest(release/'new.webp')})
        original=dict(character='builtin',scale=.7,talk_lines=['keep'],playback_speed=1,random_actions=True,character_preferences={})
        atomic_json(data/'settings.json',original)
        cfg=dict(data_dir=str(data),character_key='bailong-custom-final',allowed_characters=['builtin','bailong-custom-final'],state_dir=str(self.root/'state'))
        with patch.object(u.appio,'stop_app'),patch.object(u.appio,'start_app') as start,\
             patch.object(u.appio,'preserve_foot',side_effect=lambda c,s,*a,**k:s),\
             patch.object(u.appio,'wait_active',side_effect=RuntimeError('injected startup failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):u.appio.deploy(cfg,release,{}, {})
        self.assertEqual(u.read_json(data/'settings.json'),original);self.assertEqual(start.call_count,2)

if __name__=='__main__':unittest.main(verbosity=2)
