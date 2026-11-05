from pathlib import Path
import os,json,tempfile,unittest,sys,copy,types
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QRect,QRectF,QSize,QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from desktop_reference import load_desktop_reference,reference_rects,MODES,attached_rect,character_rect
from config_store import load_config
from preview_player import PreviewCanvas
APP=QApplication.instance() or QApplication([])

class DesktopReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=load_config(Path(__file__).parent/'配置.json');self.source_root=self.config['app_root']
        self.config.update(data_dir=str(self.root/'data'),app_root=str(self.root/'source'))
        self.data=Path(self.config['data_dir']);self.role=self.data/'characters'/self.config['character_key'];self.role.mkdir(parents=True)
        app=Path(self.config['app_root'])/'app';app.mkdir(parents=True);(app/'island_widgets.py').write_text('WIDTH=246\nHEIGHT=44\n',encoding='utf-8')
        self.layout=dict(canvas=[1184,1184],anchor=[592,900],referenceHeight=607,displayHeight=607*256/720,panelBounds=[276,284,910,908])
        self.manifest=dict(qualityRevision=42,canvasLayout=self.layout)
        self.settings=dict(character=self.config['character_key'],scale=.7,quota_visible=True,panel_detached=False)
        self.runtime=dict(quality_revision=42,scale=.7,character_logical_size=[295,295],position=[1412,190],bubble_bounds=[1445,78,228,174],panel_page='status',island_visible=False,minimal_quota_mode=True)
        self.save()
    def save(self):
        for path,data in ((self.data/'settings.json',self.settings),(self.data/'runtime.json',self.runtime),(self.role/'素材清单.json',self.manifest)):path.write_text(json.dumps(data),encoding='utf-8')
    def tearDown(self):self.tmp.cleanup()
    def snapshot(self):return load_desktop_reference(self.config,[QRect(0,0,1920,1080)])
    def test_live_panel_and_source_sized_capsule_share_real_desktop_reference(self):
        ref=self.snapshot();panel,capsule=ref['items'];self.assertEqual(ref['mode'],'panel');self.assertEqual(panel['offset'][2:],[228,174]);self.assertEqual(panel['source'],'运行记录')
        self.assertEqual(capsule['offset'][2:],[210,38]);self.assertEqual(capsule['source'],'按源码布局估算')
        foot=[1412+592/1184*295,190+900/1184*295]
        self.assertEqual(panel['offset'][:2],[1445-foot[0],78-foot[1]])
    def test_current_capsule_uses_recorded_geometry_and_labels_panel_as_estimated(self):
        self.runtime.update(island_visible=True,bubble_bounds=[1450,214,213,38]);self.save();ref=self.snapshot()
        self.assertEqual(ref['mode'],'capsule');self.assertEqual(ref['items'][1]['offset'][2:],[213,38]);self.assertEqual(ref['items'][1]['source'],'运行记录');self.assertEqual(ref['items'][0]['source'],'按源码布局估算')
    def test_capsule_dimensions_follow_source_and_quota_setting(self):
        p=Path(self.config['app_root'])/'app/island_widgets.py';p.write_text('WIDTH=300\nHEIGHT=50\n',encoding='utf-8');self.settings['quota_visible']=False;self.save()
        self.assertEqual(self.snapshot()['items'][1]['offset'][2:],[219,43])
    def test_reference_is_fixed_relative_to_foot_when_canvas_grows_or_person_moves(self):
        ref=self.snapshot();scenes=[dict(canvas=[1184,1184],anchor=[592,900],image_rect=[213,-9,780,1162],desktop_reference=ref),dict(canvas=[1280,1280],anchor=[640,948],image_rect=[300,12,780,1162],desktop_reference=ref)]
        for scene in scenes:
            for item,rect in reference_rects(scene):
                self.assertAlmostEqual((rect.x()-scene['anchor'][0])*ref['factor'],item['offset'][0]);self.assertAlmostEqual((rect.y()-scene['anchor'][1])*ref['factor'],item['offset'][1])
    def test_fit_view_contains_both_panels_and_foot_line(self):
        ref=self.snapshot();canvas=PreviewCanvas();canvas.image=QImage(10,10,QImage.Format.Format_RGBA8888);canvas.resize(700,360);canvas.set_scene(dict(canvas=[1184,1184],anchor=[592,900],desktop_reference=ref))
        box,_,factor=canvas.drawing_rects();viewport=QRectF(canvas.rect())
        for _,rect in reference_rects(canvas.scene):
            mapped=QRectF(box.x()+rect.x()*factor,box.y()+rect.y()*factor,rect.width()*factor,rect.height()*factor);self.assertTrue(viewport.contains(mapped))
        self.assertTrue(viewport.contains(QPointF(box.center().x(),box.y()+900*factor)))
        canvas.set_panel_mode(MODES[1]);self.assertEqual([i['key'] for i,r in reference_rects(canvas.scene,canvas.panel_mode)],['panel'])
        canvas.set_panel_mode(MODES[2]);self.assertEqual([i['key'] for i,r in reference_rects(canvas.scene,canvas.panel_mode)],['capsule'])
        canvas.set_panel_mode(MODES[3]);self.assertEqual(reference_rects(canvas.scene,canvas.panel_mode),[]);canvas.close_player();canvas.close()
    def test_actual_view_preserves_panel_pixel_size(self):
        ref=self.snapshot();canvas=PreviewCanvas();canvas.image=QImage(10,10,QImage.Format.Format_RGBA8888);canvas.actual_scale=ref['factor'];canvas.set_view_mode('桌宠实际尺寸');canvas.set_scene(dict(canvas=[1184,1184],anchor=[592,900],desktop_reference=ref))
        for item,rect in reference_rects(canvas.scene):self.assertAlmostEqual(rect.width()*canvas.drawing_rects()[2],item['offset'][2])
        canvas.close_player();canvas.close()
    def test_detached_modes_retain_independent_card_center_and_bottom(self):
        self.settings['panel_detached']=True;self.runtime['bubble_bounds']=[900,400,228,174];self.save();ref=self.snapshot();panel,capsule=ref['items']
        self.assertEqual(panel['offset'][0]+panel['offset'][2]/2,capsule['offset'][0]+capsule['offset'][2]/2)
        self.assertEqual(panel['offset'][1]+panel['offset'][3],capsule['offset'][1]+capsule['offset'][3])
    def test_other_character_runtime_is_not_claimed_as_current_and_files_are_unchanged(self):
        self.settings['character']='other';self.save();paths=[self.data/'settings.json',self.data/'runtime.json'];before=[p.read_bytes() for p in paths];ref=self.snapshot()
        self.assertFalse(ref['live']);self.assertTrue(all(i['source']=='按源码布局估算' for i in ref['items']));self.assertEqual(before,[p.read_bytes() for p in paths])
    def test_capsule_placement_matches_the_desktop_source_implementation(self):
        sys.path.insert(0,str(Path(self.source_root)/'app'))
        from compact_bubble import CompactBubble
        from panel_placement import character_geometry,avoid_character
        area=APP.primaryScreen().availableGeometry();position=[area.x()+100,area.y()+300];size=[295,295]
        owner=types.SimpleNamespace(settings={},manifest=self.manifest,frameGeometry=lambda:QRect(*position,*size),rect=lambda:QRect(0,0,*size),frame_target=lambda canvas:canvas)
        character=character_geometry(owner);panel=types.SimpleNamespace(owner_pet=lambda:owner,report=None,panel_page='status',expanded=False,is_minimal=lambda:False,is_island=lambda:True)
        panel.avoid_character_geometry=lambda rect:avoid_character(rect,character,area)
        actual=CompactBubble.content_geometry(panel,QSize(210,38),docked=False)
        self.assertEqual(attached_rect([210,38],character,area),actual)

if __name__=='__main__':unittest.main(verbosity=2)
