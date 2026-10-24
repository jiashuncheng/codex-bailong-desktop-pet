"""Contracts for ordered liquid motion and identity-preserving native paint."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import math
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter

from status_motion import GlyphMotion,busy_liquid_parts
from status_paint import paint_liquid_glyph


def render(parts,island=False,scale=4):
    image=QImage(16*scale,16*scale,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.scale(scale,scale)
    paint_liquid_glyph(painter,parts,island);painter.end()
    return image


def components(image):
    """Opaque connected regions, ignoring isolated antialiasing specks."""
    remaining={(x,y) for y in range(image.height()) for x in range(image.width())
               if image.pixelColor(x,y).alpha()>=128}
    regions=[]
    while remaining:
        todo=[remaining.pop()];region=set(todo)
        while todo:
            x,y=todo.pop()
            for point in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if point in remaining:
                    remaining.remove(point);region.add(point);todo.append(point)
        if len(region)>4:regions.append(region)
    return regions


class LiquidStatusTests(unittest.TestCase):
    def assertPartsClose(self,a,b,tolerance=1e-8):
        self.assertEqual(len(a),len(b))
        for left,right in zip(a,b):
            for x,y in zip(left,right):self.assertLessEqual(abs(x-y),tolerance)

    def test_full_loop_preserves_ball_and_color_identity_without_a_beat_jump(self):
        # Compare by identity, not nearest position: rotating the mint identity
        # into a lavender ball's slot cannot pass this seam check.
        for time in (0,.19,.43,.95,1.5,2.75,4.55,8.3,10.799):
            parts=busy_liquid_parts(time)
            self.assertPartsClose(parts,busy_liquid_parts(time+10.8))
            self.assertEqual([p.mint for p in parts],[0,0,1])
            self.assertTrue(all(p.hole==0 and p.opacity==1 for p in parts))
        for beat in range(1,7):
            self.assertPartsClose(busy_liquid_parts(beat*1.8-.001),
                                  busy_liquid_parts(beat*1.8+.001),.02)
        first,last=render(busy_liquid_parts(0)),render(busy_liquid_parts(10.8))
        self.assertEqual(bytes(first.constBits()),bytes(last.constBits()))

    def test_inward_pass_and_whole_group_rotation_are_both_present(self):
        outer=busy_liquid_parts(0);passing=busy_liquid_parts(.43)
        for start,middle in zip(outer,passing):
            self.assertGreater(math.hypot(start.x-8,start.y-8)
                               -math.hypot(middle.x-8,middle.y-8),1.)
        # Between crossing and the next beat the three balls must still rotate
        # together. A local crossing alone or a static triad fails this test.
        before,after=busy_liquid_parts(1.5),busy_liquid_parts(1.7)
        shifts=[]
        for a,b in zip(before,after):
            shift=math.atan2(b.y-8,b.x-8)-math.atan2(a.y-8,a.x-8)
            shifts.append(math.atan2(math.sin(shift),math.cos(shift)))
            self.assertAlmostEqual(math.hypot(a.x-8,a.y-8),math.hypot(b.x-8,b.y-8))
        self.assertTrue(all(.05<angle<.2 for angle in shifts))
        self.assertLess(max(shifts)-min(shifts),1e-8)

    def test_neck_rotates_between_identities_and_releases_each_round(self):
        for beat in range(6):
            with self.subTest(beat=beat):
                parts=busy_liquid_parts(beat*1.8+.95)
                selected=[i for i,p in enumerate(parts) if p.bond>.5]
                self.assertEqual(selected,[beat%3])
                # Inspect output topology, not just the bond flag. Only the
                # selected pair joins; the third ball must remain independent.
                for island in (False,True):
                    self.assertEqual(len(components(render(parts,island))),2)
                first,second=parts[beat%3],parts[(beat+1)%3]
                self.assertLess(math.hypot(first.x-second.x,first.y-second.y),5.8)
                released=busy_liquid_parts(beat*1.8+1.6)
                self.assertEqual([p.bond for p in released],[0,0,0])
                self.assertEqual(len(components(render(released))),3)

    def test_one_mint_ball_survives_bonding_on_both_backgrounds(self):
        for time in (0,.95,2.75,4.55):
            parts=busy_liquid_parts(time)
            for island in (False,True):
                image=render(parts,island)
                for index,part in enumerate(parts):
                    color=image.pixelColor(round(part.x*4),round(part.y*4))
                    self.assertGreater(color.alpha(),250)
                    if index==2:self.assertGreater(color.green()-color.red(),20)
                    else:self.assertGreater(color.blue()-color.green(),15)

    def test_retarget_from_live_neck_and_warning_keeps_color_and_shape_continuous(self):
        motion=GlyphMotion();motion.set_state('busy',0,animate=False)
        now=.95
        self.assertGreater(motion.sample(now)[0].bond,.9)
        for state in ('warning','waiting','paused','busy','complete','attention'):
            before=motion.sample(now);motion.set_state(state,now)
            self.assertPartsClose(before,motion.sample(now))
            after=motion.sample(now+.06)
            self.assertNotEqual(before,after)
            for part in after:
                self.assertTrue(all(math.isfinite(v) for v in part))
                self.assertTrue(all(0<=v<=1 for v in (part.mint,part.bond,part.warm)))
            now+=.06
        warning=GlyphMotion();warning.set_state('warning',0,animate=False)
        before=warning.sample(1.)
        self.assertTrue(all(p.warm==1 for p in before))
        warning.set_state('busy',1.)
        self.assertPartsClose(before,warning.sample(1.))
        self.assertTrue(all(0<p.warm<1 for p in warning.sample(1.2)))
        self.assertTrue(all(p.warm==0 for p in warning.sample(1.6)))

    def test_settled_task_symbols_stay_distinct_visible_and_stop_moving(self):
        # Check topology as well as geometry: two pause rails, an exclamation
        # with a separate dot and one connected checkmark must survive painting.
        region_counts={'idle':1,'paused':2,'attention':2,'warning':2,'complete':1}
        silhouettes={}
        for state,expected in region_counts.items():
            motion=GlyphMotion();motion.set_state(state,0)
            parts=motion.sample(10)
            self.assertFalse(motion.moving(10))
            self.assertEqual(parts,motion.sample(11))
            self.assertEqual(parts[2].mint,1)
            image=render(parts)
            self.assertEqual(len(components(image)),expected)
            # Alpha silhouettes distinguish actual task symbols. Attention and
            # warning intentionally share shape, using palette and text instead.
            silhouettes[state]=bytes(image.constBits())[3::4]
            for scale in (1,2):
                small=render(parts,scale=scale)
                self.assertTrue(any(small.pixelColor(x,y).alpha()>150
                                    for x in range(small.width()) for y in range(small.height())))
                edge=small.width()-1
                self.assertTrue(all(small.pixelColor(x,y).alpha()<128
                                    for i in range(small.width())
                                    for x,y in ((i,0),(i,edge),(0,i),(edge,i))))
        self.assertEqual(len({silhouettes[s] for s in ('idle','paused','attention','complete')}),4)


if __name__=='__main__':unittest.main()
