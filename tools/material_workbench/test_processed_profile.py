from pathlib import Path
from dataclasses import replace
import tempfile,unittest,json
from unittest.mock import patch
from PIL import Image,ImageDraw
import numpy as np
from media import write_animation,frames
from processed_profile import read,encode,from_layout,validate
from clip_editing import Clip,probe,export
from motion_stabilization import transform_at,analyse
import updater

class ProfileTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def source(self,name='source.webp',size=(80,100),anchor=(40,85),profile=True):
        path=self.root/name;seq=[]
        for x in (20,25,30):
            image=Image.new('RGBA',size);ImageDraw.Draw(image).rectangle((x,20,x+20,anchor[1]-1),fill=(120+x,70,220,255));seq.append((image,100))
        meta=from_layout(dict(canvas=list(size),anchor=list(anchor)))
        write_animation(path,seq,xmp=encode(meta) if profile else None);return path
    def test_trim_carries_fixed_anchor_without_private_paths_or_pixel_changes(self):
        path=self.source();out=self.root/'cut.webp';before=list(frames(path));export([Clip(str(path),100,300)],out)
        self.assertEqual(read(out),read(path));self.assertEqual([im.tobytes() for im,ms in frames(out)],[im.tobytes() for im,ms in before[1:]])
        with Image.open(out) as image:self.assertNotIn(str(self.root).encode(),image.info['xmp'])
    def test_different_processed_canvases_align_declared_feet_instead_of_frame_bottom(self):
        a=self.source();b=self.source('large.webp',(100,120),(50,95));out=self.root/'join.webp'
        export([Clip(str(a)),Clip(str(b))],out);profile=read(out);self.assertEqual(profile['anchor'],[50,95]);self.assertEqual(profile['canvas'],[100,120])
        decoded=list(frames(out));self.assertEqual(decoded[0][0].getchannel('A').getbbox()[3],95);self.assertEqual(decoded[3][0].getchannel('A').getbbox()[3],95)
    def test_mixed_processed_and_uncalibrated_transparent_inputs_are_rejected(self):
        a=self.source();b=self.source('raw.webp',profile=False)
        with self.assertRaises(ValueError):export([Clip(str(a)),Clip(str(b))],self.root/'bad.webp')
    def test_invalid_canvas_and_nonfinite_anchor_cannot_reach_processing(self):
        for value in (dict(schema=1,kind='bailong-processed',canvas=[80,100],anchor=[float('nan'),85]),dict(schema=1,kind='bailong-processed',canvas=[80,100],anchor=[40,85])):
            with self.assertRaises(ValueError):validate(value,(100,100))
    def test_reprocessing_processed_input_does_not_guess_face_or_apply_global_scale_again(self):
        path=self.source();config=dict(state_dir=str(self.root/'state'),settle_seconds=0,extra_scale=1.3,adjustments={},overrides={})
        matcher=type('Matcher',(),{'match':lambda *a:None})()
        with patch.object(updater,'BASE',Path(__file__).parent):result=updater.prepare(path,config,matcher)
        self.assertEqual(result['transform']['scale'],1);self.assertEqual(result['transform']['anchor'],[40,85]);self.assertTrue(result['calibration']['inherited'])
    def test_dynamic_transform_is_shared_with_export_without_mutating_manual_parameters(self):
        record=dict(transform=dict(scale=.85,anchor=[40,85],sourceSize=[80,100],offset=[3,-4]),stabilization=dict(frames=2,gains=[1,.9],footY=[85,95]))
        result=transform_at(record,1);self.assertAlmostEqual(result['scale'],.765);self.assertEqual(result['anchor'],[40,95]);self.assertEqual(result['offset'],[3,-4]);self.assertEqual(record['transform']['anchor'],[40,85])
    def test_low_confidence_camera_estimates_fail_instead_of_warping_an_animation(self):
        path=self.source();matcher=type('Matcher',(),{'match':lambda *a:dict(score=.4,scale=1,box=[20,20,40,40])})()
        with self.assertRaises(ValueError):analyse(path,matcher)
    def test_slow_zoom_and_vertical_drift_are_reduced_without_changing_poses_or_timing(self):
        path=self.root/'drift.webp';seq=[]
        for index in range(37):
            gain=1+.2*index/36;w=round(60*gain);h=round(100*gain);foot=150+round(30*index/36)
            image=Image.new('RGBA',(200,240));ImageDraw.Draw(image).rectangle((60,foot-h,60+w-1,foot-1),fill=(120+index,60,200,255));seq.append((image,40))
        write_animation(path,seq)
        class Matcher:
            def match(self,image):
                l,t,r,b=image.getchannel('A').getbbox();return dict(scale=(r-l)/60,score=.95,box=[l+5,t+5,r-5,t+30])
        profile=analyse(path,Matcher());self.assertEqual(profile['frames'],37)
        record=dict(transform=dict(scale=1.,anchor=[90.,150.],sourceSize=[200,240]),stabilization=profile)
        from media import placed
        widths=[];feet=[]
        for index,(image,ms) in enumerate(seq):
            rendered=placed(image,transform_at(record,index),240,[120,180]);box=rendered.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox();widths.append(box[2]-box[0]);feet.append(box[3])
        self.assertLessEqual(max(widths)-min(widths),4);self.assertLessEqual(max(feet)-min(feet),4)
    def test_baked_stabilization_is_not_applied_again(self):
        path=self.source();meta=read(path);meta['stabilizationBaked']=True;decoded=list(frames(path));write_animation(path,decoded,xmp=encode(meta))
        config=dict(state_dir=str(self.root/'state'),settle_seconds=0,extra_scale=1,adjustments={},stabilize_actions={path.name:True})
        matcher=type('Matcher',(),{'match':lambda *a:None})()
        with patch.object(updater,'BASE',Path(__file__).parent),patch.object(updater,'analyse',side_effect=AssertionError('should not reanalyse')):result=updater.prepare(path,config,matcher)
        self.assertTrue(result['stabilization']['alreadyBaked']);self.assertEqual(result['stabilization']['gains'],[1,1,1])
