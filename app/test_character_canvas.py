import os,tempfile,json,unittest,time,copy
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['BAILONG_ISOLATED']='1'
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint,QRectF
from PySide6.QtGui import QPixmap,QPainter
from character_canvas import layout
from desktop_services import validate_character
from desktop import DesktopPet
import material_store
APP=QApplication.instance() or QApplication([])

LAYOUT=dict(schema=1,canvas=[960,600],anchor=[480.47,490.09],referenceHeight=296,displayHeight=256*607/720,alphaUnion=[137,144,836,514])

class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.base=self.root/'base';self.base.mkdir()
        im=Image.new('RGBA',(720,720));ImageDraw.Draw(im).ellipse((270,100,450,667),fill=(150,50,200,255))
        im.save(self.base/'idle.webp',lossless=True)
        self.builtin={'character':'fixture','idle':{'id':'idle','file':'idle.webp','durationMs':1000},'variants':[]}
        (self.base/'素材清单.json').write_text(json.dumps(self.builtin),encoding='utf-8')
        original=material_store.MaterialStore
        base=self.base
        class Store(original):
            def __init__(s,*a,**kw):
                super().__init__(*a,**kw);s.root=base;s.current='light'
        self.patches=[patch('material_store.MaterialStore',Store),patch('pet.ASSETS',self.base)]
        self.patches += [patch(m+'.'+key,self.root/('settings.json' if key=='CONFIG' else '')) for m in ('desktop','enhanced') for key in ('CONFIG','STATE_DIR')]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False)
        self.pet.apply_settings(dict(wandering=False,random_actions=False,drag_physics=False),save=False)
        self.pet.move(300,100)
        self.role=self.pet.character_dir/'baby';self.role.mkdir()
        im=Image.new('RGBA',(720,450));d=ImageDraw.Draw(im);d.ellipse((300,220,420,340),fill=(20,180,230,255))
        im.save(self.role/'idle.webp',lossless=True)
        self.manifest={'character':'baby','canvasLayout':LAYOUT,'allowRoaming':False,'idle':{'id':'idle','file':'idle.webp','durationMs':1000},'variants':[]}
        (self.role/'素材清单.json').write_text(json.dumps(self.manifest),encoding='utf-8')

    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_constructor_keeps_saved_position_for_different_canvas(self):
        p=self.pet;p.switch_character('baby')
        p.apply_settings({'scale':.83},save=False);p.move(100,100);p.save_settings()
        saved=json.loads((self.root/'settings.json').read_text(encoding='utf-8'))
        expected=(p.x(),p.y());p.close();APP.processEvents()
        self.pet=DesktopPet(monitor=False);APP.processEvents()
        self.assertEqual((self.pet.x(),self.pet.y()),expected)
        self.assertEqual(self.pet.settings['screen_position'],saved['screen_position'])

    def test_roundtrip_preserves_foot_and_user_state(self):
        p=self.pet
        p.settings.update(notifications=True,mouse_through=True,card_anchor={'screen':'x','rx':.2,'ry':.3})
        original=(p.x()+p.width()/2,p.y()+p.height()*668/720)
        preserved={k:copy.deepcopy(p.settings[k]) for k in ('notifications','mouse_through','card_anchor')}
        for _ in range(3):
            p.switch_character('baby');a=layout(p.manifest).anchor(p.width(),p.height())
            self.assertLessEqual(abs(p.x()+a[0]-original[0]),1)
            self.assertLessEqual(abs(p.y()+a[1]-original[1]),1)
            self.assertAlmostEqual(p.width()/p.height(),1.6,delta=.004)
            p.switch_character('builtin')
            self.assertLessEqual(abs(p.x()+p.width()/2-original[0]),1)
            self.assertLessEqual(abs(p.y()+p.height()*668/720-original[1]),1)
        self.assertEqual(preserved,{k:p.settings[k] for k in preserved})

    def test_rectangular_image_is_round_and_hit_test_matches(self):
        p=self.pet;p.switch_character('baby');p.settings['mouse_through']=False
        # Stop the stream after its prepared first frame; all painting uses the
        # production frame_target/draw_frame and production inverse alpha hit.
        from PySide6.QtCore import Qt
        pix=QPixmap(p.size());pix.fill(Qt.GlobalColor.transparent);painter=QPainter(pix)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(pix.rect(),Qt.GlobalColor.transparent)
        p.draw_frame(painter,QRectF(pix.rect()));painter.end()
        image=pix.toImage();xs=[];ys=[]
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x,y).alpha()>=100:xs.append(x);ys.append(y)
        self.assertAlmostEqual((max(xs)-min(xs))/(max(ys)-min(ys)),1.,delta=.035)
        center=((min(xs)+max(xs))//2,(min(ys)+max(ys))//2)
        self.assertTrue(p.alpha_hit(*center));self.assertFalse(p.alpha_hit(1,1))
        # Square snapshots must preserve the same source shape.
        target=p.frame_target(QRectF(0,0,500,500));self.assertAlmostEqual(target.width()/target.height(),1.6)

    def test_scaling_keeps_anchor_and_roaming_has_no_side_effect(self):
        p=self.pet;p.switch_character('baby');a=layout(p.manifest).anchor(p.width(),p.height());before=(p.x()+a[0],p.y()+a[1])
        p.apply_settings({'scale':.8},save=False);a=layout(p.manifest).anchor(p.width(),p.height())
        self.assertLessEqual(abs(p.x()+a[0]-before[0]),1);self.assertLessEqual(abs(p.y()+a[1]-before[1]),1)
        with patch.object(p.roaming,'next') as next_leg:p.start_walk();next_leg.assert_not_called()

    def test_invalid_layout_or_wrong_aspect_rejected(self):
        validate_character(self.role)
        self.manifest['canvasLayout']=dict(LAYOUT,referenceHeight=float('nan'))
        (self.role/'素材清单.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        with self.assertRaises(ValueError):validate_character(self.role)
        self.manifest['canvasLayout']=LAYOUT
        Image.new('RGBA',(720,720)).save(self.role/'idle.webp')
        (self.role/'素材清单.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        with self.assertRaises(ValueError):validate_character(self.role)

    def test_candidate_is_excluded_from_random_click_but_remains_selectable(self):
        p=self.pet;p.switch_character('baby')
        approved=dict(p.manifest['idle'],id='basic')
        candidate=dict(p.manifest['idle'],id='candidate',file='candidate.webp',automatic=False)
        p.manifest['variants']=[approved,candidate]
        with patch.object(p,'choose') as choose:
            for _ in range(4):p.single_click()
            self.assertTrue(choose.called)
            self.assertTrue(all(c.args[0]['id']!='candidate' for c in choose.call_args_list))
        self.assertIn(candidate,p.manifest['variants'])

    def test_panel_tracks_visible_envelope_at_multiple_scales(self):
        from panel_placement import character_geometry
        from PySide6.QtCore import QRect,QSize
        p=self.pet;p.switch_character('baby');p.show()
        for scale in (.5,.7,1.2):
            p.apply_settings({'scale':scale},save=False)
            p.move(100,280)
            r=character_geometry(p);target=p.frame_target(QRectF(p.rect()))
            self.assertLessEqual(abs(r.top()-(p.y()+target.y()+144/600*target.height())),1)
            p.bubble.size_transition.complete();p.bubble.size_transition.release_landing()
            card=p.bubble.content_geometry(QSize(190,120))
            self.assertGreater(r.top()-p.y(),0)
            self.assertLessEqual(abs(r.top()-card.bottom()-9),1)
            # Insets describe a stable source envelope, independent of frame pixels.
            p.frame=QPixmap(720,720)
            self.assertEqual(character_geometry(p),r)

    def test_legacy_panel_bounds_are_unchanged_and_invalid_bounds_fallback(self):
        from panel_placement import character_geometry
        p=self.pet
        self.assertEqual(character_geometry(p),p.frameGeometry())
        p.switch_character('baby')
        p.manifest['canvasLayout']['panelBounds']=[0,float('nan'),700,600]
        self.assertEqual(character_geometry(p),p.frameGeometry())

    def test_hd_role_decodes_at_physical_canvas_size_and_legacy_cap_is_preserved(self):
        p=self.pet;p.switch_character('baby');p.settings['scale']=.9
        with patch.object(p,'devicePixelRatioF',return_value=1.5):
            self.assertEqual(p.desired_decode_size(),720)
            p.manifest['decodeResolution']=1920
            self.assertEqual(p.desired_decode_size(),945)
            p.settings['scale']=1.2
            self.assertEqual(p.desired_decode_size(),1260)
            p.settings['scale']=4.
            self.assertEqual(p.desired_decode_size(),1920)
            p.manifest['decodeResolution']=float('nan')
            self.assertEqual(p.desired_decode_size(),720)

if __name__=='__main__':unittest.main()
