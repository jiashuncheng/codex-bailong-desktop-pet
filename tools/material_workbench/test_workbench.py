from pathlib import Path
import os,sys,json,tempfile,time,unittest,copy
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QProcess
from PIL import Image,ImageDraw
from config_store import normalize,save_config,load_config
from workbench import MaterialWorkbench
from preview_player import PreviewCanvas,PreviewDecoder
import updater

APP=QApplication.instance() or QApplication([])
def wait_until(check,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        APP.processEvents()
        if check():return True
        time.sleep(.01)
    return False

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        cfg=load_config(Path(__file__).parent/'配置.json')
        cfg.update(input_dir=str(self.source),output_dir=str(self.root/'output'),state_dir=str(self.root/'state'),data_dir=str(self.root/'appdata'))
        self.config=self.root/'config.json';self.config.write_text(json.dumps(cfg),encoding='utf-8')
        self.window=MaterialWorkbench(self.config);self.window.show()
        self.assertTrue(wait_until(lambda:not self.window.scan_workers))
    def tearDown(self):
        self.window.close();APP.processEvents();self.tmp.cleanup()
    def rows(self):
        return [dict(action='custom_a',path=str(self.source/'a.webm'),name='雨伞龙娘',file='a.webm',bytes=1024,sha256='a',status='待处理',error='',processed='',processed_current=False,meta={}),
                dict(action='custom_b',path=str(self.source/'b.webm'),name='提灯龙娘',file='b.webm',bytes=2048,sha256='b',status='已加入',error='',processed='',processed_current=True,meta={})]
    def test_core_controls_visible_at_compact_and_wide_sizes(self):
        for size in ((900,650),(1180,780),(1440,900)):
            self.window.resize(*size);APP.processEvents()
            for widget in (self.window.process_button,self.window.apply_button,self.window.table,self.window.canvas,self.window.tabs):
                point=widget.mapTo(self.window,widget.rect().topLeft())
                self.assertGreaterEqual(point.x(),0);self.assertGreaterEqual(point.y(),0)
                self.assertLessEqual(point.x()+widget.width(),self.window.width())
                self.assertLessEqual(point.y()+widget.height(),self.window.height())
    def test_selection_processing_is_distinct_from_preview_selection(self):
        with patch.object(self.window,'load_preview'):
            self.window.populate(self.rows(),dict(ready=True,pending=False))
            self.assertEqual(self.window.checked_paths(),[str(self.source/'a.webm')])
            self.assertFalse(self.window.apply_button.isEnabled())
            self.window.table.selectRow(1);APP.processEvents()
            self.assertEqual(self.window.checked_paths(),[str(self.source/'a.webm')])
            self.window.select_all(True);self.assertEqual(len(self.window.checked_paths()),2)
            self.window.select_pending();self.assertEqual(len(self.window.checked_paths()),1)
    def test_processed_tab_and_apply_available_when_ready(self):
        rows=self.rows();rows[0]['processed']=str(self.root/'done.webp')
        with patch.object(self.window,'load_preview'):
            self.window.populate(rows,dict(ready=True,pending=True))
            self.assertTrue(self.window.tabs.isTabEnabled(1));self.assertTrue(self.window.apply_button.isEnabled())
            self.window.tabs.setCurrentIndex(1);self.assertEqual(self.window.tabs.currentIndex(),1)
    def test_utf8_process_lines_can_arrive_in_multiple_chunks(self):
        line=json.dumps(dict(message='新增素材编码进度',frame=12,total=24,file='白龙'),ensure_ascii=False).encode()+b'\n'
        with patch.object(self.window.process,'readAllStandardOutput',side_effect=[line[:19],line[19:31],line[31:]]):
            self.window.read_output();self.window.read_output();self.window.read_output()
        self.assertEqual(self.window.progress.value(),12);self.assertIn('12 / 24',self.window.status.text())
    def test_settings_slots_do_not_overwrite_windows_paths_on_mac(self):
        path=self.root/'slots.json';raw=dict(input_dir='D:/WindowsVideo',app_root='D:/WhiteDragon',python='D:/python.exe',data_dir='C:/Data',state_dir='C:/State',output_dir='D:/out',runtime='C:/Runtime')
        path.write_text(json.dumps(raw),encoding='utf-8')
        with patch.dict(os.environ,{'BAILONG_DATA_DIR':''}):
            mac=normalize(raw,self.root/'tool',platform='darwin',home=self.root/'mac-home')
        self.assertNotIn('D:',mac['input_dir']);self.assertIn('Library',mac['data_dir'])
        mac['input_dir']='/Users/example/Videos';save_config(path,mac,platform='darwin')
        saved=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['input_dir'],'D:/WindowsVideo');self.assertEqual(saved['platforms']['darwin']['input_dir'],'/Users/example/Videos')
    def test_selected_backend_only_prepares_the_requested_file(self):
        (self.source/'a.webm').write_bytes(b'a');(self.source/'b.webm').write_bytes(b'b')
        cfg=load_config(self.config);cfg['settle_seconds']=0
        app=Path(cfg['app_root']);sys.path.insert(0,str(app/'app'));import material_store
        base=dict(idle={'id':'idle','file':'idle.webp'},variants=[])
        root=self.root/'base';root.mkdir();(root/'素材清单.json').write_text(json.dumps(base),encoding='utf-8')
        fake=type('Store',(),dict(current='hd',root=root,verify=lambda *a:True))()
        release=self.root/'release';release.mkdir();prepared=copy.deepcopy(base);prepared['qualityRevision']=1
        with patch.object(material_store,'MaterialStore',return_value=fake),patch.object(updater,'prepare',return_value=dict(sourceSha256='a',source=str(self.source/'a.webm'),info={})) as prepare,\
             patch.object(updater,'build_runtime',return_value=(release,prepared,False)),patch.object(updater,'publish_small'),\
             patch.object(updater,'atomic_json'),patch.object(updater.appio,'valid_release',return_value=False):
            updater.run(cfg,prepare_only=True,selected_files=[str(self.source/'a.webm')])
        self.assertEqual(prepare.call_count,1);self.assertEqual(prepare.call_args.args[0].name,'a.webm')
    def test_preview_keeps_alpha_play_pause_and_seek(self):
        from media import write_animation
        path=self.root/'preview.webp';seq=[]
        for i in range(16):
            im=Image.new('RGBA',(120,160));ImageDraw.Draw(im).rectangle((30+i,20,65+i,140),fill=(120,90,220,255));seq.append((im,42))
        write_animation(path,seq);canvas=PreviewCanvas();canvas.load(path,True,known_meta=dict(frames=16,duration=.672,fps=24))
        self.assertTrue(wait_until(lambda:canvas.image is not None and canvas.index>=2))
        self.assertEqual(canvas.image.pixelColor(0,0).alpha(),0)
        canvas.set_playing(False);index=canvas.index;time.sleep(.1);APP.processEvents();self.assertEqual(canvas.index,index)
        canvas.seek(9);self.assertTrue(wait_until(lambda:canvas.image is not None and canvas.index==9))
        self.assertFalse(canvas.playing);canvas.close_player();canvas.close()
    def test_finished_preview_can_be_replayed(self):
        from media import write_animation
        path=self.root/'short.webp'
        write_animation(path,[(Image.new('RGBA',(20,20),(n*90,0,0,255)),30) for n in range(3)])
        canvas=PreviewCanvas();canvas.loop=False;canvas.load(path)
        self.assertTrue(wait_until(lambda:canvas.ended))
        self.assertFalse(canvas.timer.isActive());canvas.set_playing(True)
        self.assertTrue(wait_until(lambda:canvas.image is not None and canvas.index==0))
        canvas.close_player();canvas.close()
    def test_activate_only_does_not_decode_or_encode_sources(self):
        cfg=load_config(self.config);root=self.root/'base';root.mkdir();release=self.root/'release';release.mkdir()
        base=dict(idle={'id':'idle','file':'idle.webp'},variants=[],qualityRevision=42)
        (root/'素材清单.json').write_text(json.dumps(base),encoding='utf-8')
        (release/'素材清单.json').write_text(json.dumps(base),encoding='utf-8')
        (release/'新增处理记录.json').write_text(json.dumps(dict(base_root=str(root))),encoding='utf-8')
        state=Path(cfg['state_dir']);state.mkdir();(state/'state.json').write_text(json.dumps(dict(release=str(release),actions={'a':{'source':'missing','info':{}}})),encoding='utf-8')
        sys.path.insert(0,str(Path(cfg['app_root'])/'app'));import material_store
        fake=type('Store',(),dict(current='hd',root=root,verify=lambda *a:True))()
        with patch.object(material_store,'MaterialStore',return_value=fake),patch.object(updater,'prepare') as prepare,\
             patch.object(updater,'build_runtime') as build,patch.object(updater,'scan',return_value={}),\
             patch.object(updater,'publish_small'),patch.object(updater,'atomic_json'),\
             patch.object(updater.appio,'valid_release',return_value=True),patch.object(updater.appio,'recover'),\
             patch.object(updater.appio,'deploy',return_value={'pid':123}) as deploy:
            report=updater.run(cfg,activate_only=True)
        prepare.assert_not_called();build.assert_not_called();deploy.assert_called_once();self.assertTrue(report['restarted'])
    def test_posix_lock_uses_flock(self):
        import integration,types
        calls=[];fake=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,LOCK_UN=8,flock=lambda fd,mode:calls.append(mode))
        path=self.root/'posix.lock'
        with patch.object(integration,'Path',return_value=path),patch.object(integration.os,'name','posix'),patch.dict(sys.modules,{'fcntl':fake}):
            with integration.lock(str(path)):pass
        self.assertEqual(calls,[6,8])

if __name__=='__main__':unittest.main(verbosity=2)
