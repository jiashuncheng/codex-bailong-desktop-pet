"""Soft starts/stops, safe rounded relocation and passive native guards."""
import math
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPointF,QRect,QRectF,Qt
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtGui import QColor,QPainter,QPixmap
from spring_motion import container_progress
from panel_placement import RoundedRoute,morph_route,morph_rect
from panel_transition import NativeLanding
from surface_morph import SurfaceMorph,SurfaceState

APP=QApplication.instance() or QApplication([])


class SmoothMotionTests(unittest.TestCase):
    def test_container_starts_and_stops_with_zero_velocity_and_acceleration(self):
        h=.0001
        for at,direction in ((0.,1.),(.9,-1.)):
            a=container_progress(at);b=container_progress(at+direction*h);c=container_progress(at+direction*2*h)
            self.assertLess(abs((b-a)/h),.001)
            self.assertLess(abs((c-2*b+a)/(h*h)),.1)
        values=[container_progress(i/1000) for i in range(1001)]
        self.assertTrue(all(a<=b for a,b in zip(values,values[1:])))
        self.assertLess(max((b-a)*1000 for a,b in zip(values,values[1:])),2.7)
        self.assertLess(container_progress(16/480),.003)
        self.assertTrue(all(v==1. for v in values[900:]))

    def test_relocation_rounds_corners_without_crossing_character(self):
        start=QRectF(1056,233,360,431);end=QRectF(771,520,360,431);pet=QRectF(1147,672,179,179)
        for a,z in ((start,end),(end,start)):
            route=morph_route(a,z,pet);self.assertIsInstance(route,RoundedRoute)
            self.assertTrue(any(control is not None for begin,control,finish in route.segments))
            self.assertEqual(morph_rect(a,z,0,route),a);self.assertEqual(morph_rect(a,z,1,route),z)
            points=[]
            for i in range(1001):
                self.assertFalse(morph_rect(a,z,i/1000,route).intersects(pet.adjusted(-4,-4,4,4)))
                points.append(route.point_at(i/1000))
            directions=[b-a for a,b in zip(points,points[1:])]
            cosines=[(a.x()*b.x()+a.y()*b.y())/(math.hypot(a.x(),a.y())*math.hypot(b.x(),b.y())) for a,b in zip(directions,directions[1:])]
            self.assertGreater(min(cosines),.98)

    def test_drag_translation_reuses_the_prepared_route_tables(self):
        route=RoundedRoute((QPointF(0,0),QPointF(100,0),QPointF(100,100)),20.)
        delta=QPointF(127,-63)
        with patch.object(RoundedRoute,'__init__',side_effect=AssertionError('reprepared while dragging')):
            moved=route.translated(delta)
        self.assertIs(moved.lengths,route.lengths);self.assertIs(moved.samples,route.samples)
        for f in (0.,.2,.5,.8,1.):
            difference=moved.point_at(f)-route.point_at(f)-delta
            self.assertLess(abs(difference.x())+abs(difference.y()),1e-8)

    def test_text_anchored_content_and_icon_follow_the_routed_body(self):
        start=QRectF(1056,233,360,431);end=QRectF(771,520,360,431);pet=QRectF(1147,672,179,179)
        heading=QRectF(12,12,160,56);child=QRectF(110,40,40,16);glyph=QRectF(200,20,16,16)
        green=QColor('#20d050');purple=QColor('#d020d0');red=QColor('#f03020')
        icon=QPixmap(16,16);icon.fill(red);states=[]
        for index,rect in enumerate((start,end)):
            content=QPixmap(360,431);content.fill(QColor('#faf8fc'))
            p=QPainter(content);p.fillRect(heading,green)
            if index:p.fillRect(child,purple)
            p.end();bounds={'conversations':heading}
            if index:bounds['conversation_title_extra']=child
            states.append(SurfaceState(rect,content,glyph.translated(rect.topLeft()),icon,False,[],
                page='status',expanded=True,shared_bounds=bounds))
        morph=SurfaceMorph(*states,pet);self.assertIsNotNone(morph.route);canvas=morph.bounds()
        reference=SurfaceMorph(*states);reference_canvas=reference.bounds()
        for time in (.2,.35,.5,.7):
            image=QPixmap(canvas.size());image.fill(Qt.GlobalColor.transparent)
            p=QPainter(image);morph.paint(p,time,canvas);p.end();raster=image.toImage()
            plain=QPixmap(reference_canvas.size());plain.fill(Qt.GlobalColor.transparent)
            p=QPainter(plain);reference.paint(p,time,reference_canvas);p.end();expected=plain.toImage()
            origin=morph.geometry(time).topLeft()-QPointF(canvas.topLeft())
            reference_origin=reference.geometry(time).topLeft()-QPointF(reference_canvas.topLeft())
            # Relocation must preserve the same body-local text, reveal and
            # icon pixels as a straight transition, including partial opacity.
            for local in (QPointF(30,30),child.center(),glyph.center()):
                point=origin+local;actual=raster.pixelColor(round(point.x()),round(point.y()))
                point=reference_origin+local;color=expected.pixelColor(round(point.x()),round(point.y()))
                self.assertLessEqual(max(abs(a-b) for a,b in zip(actual.getRgb(),color.getRgb())),2,(time,local))

    def test_mac_landing_guard_does_not_raise_or_activate_application(self):
        owner=QWidget(None,Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint);owner.show()
        guard=NativeLanding(owner)
        try:
            with patch('panel_transition.sys.platform','darwin'),patch('panel_transition.QApplication.platformName',return_value='cocoa'),patch('mac_native.show_hint') as show,patch.object(guard,'raise_') as raise_window,patch('native_landing.publish',return_value=False):
                guard.prepare(QRect(100,100,150,100))
                show.assert_called_once_with(guard,owner,True);raise_window.assert_not_called()
        finally:guard.release();guard.close();owner.close();guard.deleteLater();owner.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
