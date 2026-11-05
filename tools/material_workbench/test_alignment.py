from pathlib import Path
import os,sys,json,tempfile,copy,unittest,time
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtGui import QImage
from PIL import Image,ImageDraw
from alignment import adjusted_record,manual_values,placement_rect
from alignment_editor import AlignmentDialog,scene_for
from preview_player import PreviewCanvas
from media import placed,write_animation,digest
from config_store import load_config,save_config
from library_scan import ScanWorker
from workbench import MaterialWorkbench
APP=QApplication.instance() or QApplication([])
def wait(check,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        APP.processEvents()
        if check():return True
        time.sleep(.01)
    return False

class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=load_config(Path(__file__).parent/'配置.json');self.config.update(input_dir=str(self.root/'input'),output_dir=str(self.root/'out'),state_dir=str(self.root/'state'),data_dir=str(self.root/'data'))
        for key in ('input_dir','output_dir','state_dir','data_dir'):Path(self.config[key]).mkdir()
        self.config['adjustments']={};self.config_path=self.root/'config.json';self.config_path.write_text(json.dumps(self.config),encoding='utf-8')
        self.clip=Path(self.config['input_dir'])/'action.webp'
        images=[]
        for n in range(6):
            im=Image.new('RGBA',(100,160));ImageDraw.Draw(im).rectangle((20+n,10,80,150),fill=(120+n*10,90,220,255));images.append((im,40))
        write_animation(self.clip,images)
        self.record=dict(cache=str(self.clip),source=str(self.clip),sourceSha256=digest(self.clip),name='动作',
            transform=dict(scale=1.,anchor=[50,151],sourceSize=[100,160]),info=dict(union=[20,10,81,151],frames=6,durationMs=240,size=[100,160]))
        self.row=dict(action='test',processed_action='test',name='动作',file=self.clip.name,path=str(self.clip),record=self.record,all_records={'test':self.record},meta=dict(frames=6,fps=25,duration=.24))
    def tearDown(self):APP.processEvents();self.tmp.cleanup()
    def test_manual_corrections_are_not_compounded_on_repeated_edit(self):
        record=adjusted_record(self.record,dict(scale=1.3,offset=[32,-15]))
        again=adjusted_record(record,dict(scale=1.3,offset=[32,-15]))
        self.assertEqual(record['transform'],again['transform']);self.assertEqual(self.record['transform']['scale'],1)
        reset=adjusted_record(record);self.assertEqual(reset['transform']['scale'],1);self.assertEqual(reset['transform']['offset'],[0,0])
    def test_export_position_matches_preview_and_offset_signs(self):
        record=adjusted_record(self.record,dict(scale=1.25,offset=[30,-20]));scene=scene_for(record,{'test':record})
        x,y,w,h=scene['image_rect'];self.assertEqual(scene['image_rect'],placement_rect(record['transform'],scene['anchor']))
        im=Image.new('RGBA',(100,160),(240,60,30,255));out=placed(im,record['transform'],scene['canvas'][0],scene['anchor'])
        self.assertEqual(out.getchannel('A').getbbox(),(x,y,x+w,y+h))
        zero=placement_rect(adjusted_record(self.record,dict(scale=1.25))['transform'],scene['anchor'])
        self.assertEqual([x-zero[0],y-zero[1]],[30,-20])
    def test_geometry_keeps_entire_clip_union_and_other_actions_unchanged(self):
        from updater import geometry
        other=copy.deepcopy(self.record);other['info']['union']=[-40,-80,130,190]
        record=adjusted_record(self.record,dict(scale=1.4,offset=[-180,60]));before=copy.deepcopy(other)
        side,pad,anchor=geometry({'a':record,'b':other})
        for item in (record,other):
            x,y,w,h=placement_rect(item['transform'],anchor);sw,sh=item['transform']['sourceSize'];l,t,r,b=item['info']['union']
            self.assertGreaterEqual(x+l*w/sw,0);self.assertGreaterEqual(y+t*h/sh,0)
            self.assertLessEqual(x+r*w/sw,side);self.assertLessEqual(y+b*h/sh,side)
        self.assertEqual(other,before)
    def test_invalid_or_excessively_large_corrections_are_rejected(self):
        for value in (dict(scale=float('nan')),dict(scale=0),dict(offset=[1]),dict(offset=[float('inf'),0])):
            with self.assertRaises(ValueError):manual_values(value)
        from updater import geometry
        with self.assertRaises(ValueError):geometry({'a':adjusted_record(self.record,dict(offset=[2048,0]))})
    def test_actual_preview_uses_desktop_scale_independent_of_viewport(self):
        canvas=PreviewCanvas();canvas.image=QImage(50,80,QImage.Format.Format_RGBA8888)
        canvas.actual_scale=.25;canvas.set_scene(dict(canvas=[1184,1184],image_rect=[400,300,200,400]));canvas.set_view_mode('桌宠实际尺寸')
        for size in ((400,300),(800,600)):
            canvas.resize(*size);box,image,factor=canvas.drawing_rects();self.assertEqual(box.width(),296);self.assertEqual(image.height(),100);self.assertEqual(factor,.25)
        canvas.close_player();canvas.close()
    def test_editor_preview_save_cancel_and_reset(self):
        dialog=AlignmentDialog(self.row,self.config);dialog.show()
        self.assertTrue(wait(lambda:dialog.canvas.image is not None))
        dialog.scale.setValue(120);dialog.x.setValue(10);dialog.y.setValue(-5)
        self.assertAlmostEqual(dialog.result_adjustment['scale'],1.2)
        self.assertAlmostEqual(dialog.result_adjustment['offset'][0]*dialog.factor,10)
        self.assertTrue(dialog.save.isEnabled());self.assertEqual(self.config['adjustments'],{})
        dialog.reset_values();self.assertEqual(dialog.result_adjustment,manual_values());dialog.reject();self.assertEqual(self.config['adjustments'],{})
    def test_corrections_persist_across_platform_config_saves(self):
        self.config['adjustments']={'action.webp':dict(scale=1.2,offset=[20,-10])};save_config(self.config_path,self.config)
        self.assertEqual(load_config(self.config_path)['adjustments'],self.config['adjustments'])
    def test_modified_alignment_requires_regeneration_before_activation(self):
        import updater
        action=next(iter(updater.scan(self.config)));record=adjusted_record(self.record)
        (Path(self.config['state_dir'])/'state.json').write_text(json.dumps(dict(actions={action:record})),encoding='utf-8')
        self.config['adjustments']={self.clip.name:dict(scale=1.2,offset=[0,0])}
        rows=[];info=[];worker=ScanWorker(self.config);worker.result.connect(lambda r,i:(rows.extend(r),info.append(i)));worker.start()
        self.assertTrue(wait(worker.isFinished));APP.processEvents();self.assertEqual(rows[0]['status'],'待重生成');self.assertFalse(rows[0]['processed_current'])
        self.assertEqual(info[0]['unprepared_adjustments'],1)
    def test_editor_regeneration_is_one_action_and_never_auto_applies(self):
        window=MaterialWorkbench(self.config_path);window.show();self.assertTrue(wait(lambda:not window.scan_workers));window.auto_apply.setChecked(True)
        with patch.object(window,'validate_environment',return_value=True),patch.object(window,'start_process') as start:
            window.start_processing(selected_files=[str(self.clip)],preview_only=True)
        args=start.call_args.args[0];self.assertIn('--prepare-only',args)
        request=Path(args[args.index('--selection-file')+1]);self.assertEqual(json.loads(request.read_text(encoding='utf-8')),[str(self.clip)])
        window.close()
    def test_real_build_exports_manual_alignment_and_reuses_the_same_revision(self):
        import updater,numpy as np
        from media import frames
        self.record['cacheSha256']=digest(self.clip)
        base_root=self.root/'base';base_root.mkdir();base_file=base_root/'idle.webp'
        base_frames=[(im.resize((720,720)),ms) for im,ms in frames(self.clip)];write_animation(base_file,base_frames)
        base=dict(idle=dict(id='idle',file='idle.webp',durationMs=240),variants=[])
        (base_root/'素材清单.json').write_text(json.dumps(base),encoding='utf-8')
        record=adjusted_record(self.record,dict(scale=1.25,offset=[25,-15]))
        release,manifest,encoded=updater.build_runtime(self.config,base_root,base,{'test':record})
        self.assertTrue(encoded);self.assertEqual(manifest['variants'][0]['manualAdjustment'],record['manualAdjustment'])
        scene=scene_for(record,{'test':record});outputs=list(frames(release/manifest['variants'][0]['file']))
        for (im,ms),(original,source_ms) in zip(outputs,frames(self.clip)):
            expected=placed(original,record['transform'],scene['canvas'][0],scene['anchor']);actual=np.asarray(im);wanted=np.asarray(expected);mask=wanted[:,:,3]>0
            self.assertTrue(np.array_equal(actual[:,:,3],wanted[:,:,3]));self.assertTrue(np.array_equal(actual[mask],wanted[mask]));self.assertEqual(ms,source_ms)
        again,_,encoded=updater.build_runtime(self.config,base_root,base,{'test':record})
        self.assertEqual(again,release);self.assertFalse(encoded)
        self.assertEqual(base,dict(idle=dict(id='idle',file='idle.webp',durationMs=240),variants=[]))
    def test_backend_cannot_activate_stale_alignment(self):
        import updater
        sys.path.insert(0,str(Path(self.config['app_root'])/'app'));import material_store
        base_root=self.root/'base';base_root.mkdir();(base_root/'素材清单.json').write_text(json.dumps(dict(idle={'id':'idle','file':'idle.webp'},variants=[])),encoding='utf-8')
        (Path(self.config['state_dir'])/'state.json').write_text(json.dumps(dict(actions={'a':self.record})),encoding='utf-8')
        self.config['adjustments']={self.clip.name:dict(scale=1.2,offset=[0,0])}
        fake=type('Store',(),dict(current='hd',root=base_root,verify=lambda *a:True))()
        with patch.object(material_store,'MaterialStore',return_value=fake),patch.object(updater.appio,'recover'),patch.object(updater.appio,'deploy') as deploy:
            with self.assertRaisesRegex(ValueError,'尚未重新生成'):updater.run(self.config,activate_only=True)
        deploy.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
