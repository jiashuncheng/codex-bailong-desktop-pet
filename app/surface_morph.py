"""One continuous body, a shared status glyph and separately moving satellites.

Reference: Apple's WWDC23 10194 at 11:12 and 12:43. Captures are prepared
once per navigation; each frame is only a few raster draws on a fixed canvas.
"""
from dataclasses import dataclass
import math
from PySide6.QtCore import QRectF,QPoint,QPointF,QSizeF,Qt
from PySide6.QtGui import QPixmap,QPainter,QPainterPath,QColor,QPen,QRegion
from PySide6.QtWidgets import QWidget,QToolButton
from spring_motion import container_progress,stage
from ui_theme import SURFACE,ISLAND

PANEL_RADIUS=18.


def pixel_size(value,ratio):return math.floor(value*ratio+.5)


def raster_offset(point,canvas,ratio,origin=QPointF()):
    """Difference of native pixel positions, not a rounded logical delta.

    At 150%, round(100*1.5)-round(99*1.5) differs from round(1*1.5).
    Use the screen origin just as Qt's per-monitor geometry conversion does.
    """
    def native(v):return math.floor(v+.5) if v>=0 else math.ceil(v-.5)
    return QPointF((native((point.x()-origin.x())*ratio)-native((canvas.x()-origin.x())*ratio))/ratio,
                   (native((point.y()-origin.y())*ratio)-native((canvas.y()-origin.y())*ratio))/ratio)


def complete_frame(bubble):
    size=bubble.content.size();ratio=bubble.devicePixelRatioF()
    image=QPixmap(pixel_size(size.width(),ratio),pixel_size(size.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not bubble.is_compact():
        p.setBrush(QColor(SURFACE));p.setPen(QPen(QColor('#e0d9e6'),1))
        p.drawRoundedRect(QRectF(0,0,size.width(),size.height()).adjusted(.5,.5,-.5,-.5),PANEL_RADIUS,PANEL_RADIUS)
    bubble.content.render(p,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren);p.end()
    return image


def snapshot(widget,children_only=False,skip=None):
    ratio=widget.devicePixelRatioF();image=QPixmap(pixel_size(widget.width(),ratio),pixel_size(widget.height(),ratio))
    image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
    if children_only:
        painter=QPainter(image)
        for child in widget.findChildren(QWidget,options=Qt.FindChildOption.FindDirectChildrenOnly):
            if child.isVisibleTo(widget) and child is not skip:child.render(painter,child.pos(),QRegion(),QWidget.RenderFlag.DrawChildren)
        painter.end()
    else:widget.render(image,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
    return image


@dataclass
class SurfaceState:
    rect:QRectF
    content:QPixmap
    icon_rect:QRectF
    icon:QPixmap
    island:bool
    satellites:list
    frame:QPixmap=None
    frame_origin:QPointF=None
    screen_origin:QPointF=None
    radius:float=PANEL_RADIUS

    @classmethod
    def capture(cls,bubble,origin=None):
        origin=bubble.pos() if origin is None else origin;island=bubble.is_island()
        minimal=bubble.is_minimal()
        root=bubble.island if island else bubble.minimal_quota if minimal else bubble.content
        offset=root.mapTo(bubble.content,QPoint())
        rect=QRectF(QPointF(origin+offset),QSizeF(root.size()))
        icon=bubble.status_indicator;icon_pos=icon.mapTo(root,QPoint()) if not minimal else QPoint()
        image=snapshot(root,children_only=island,skip=icon)
        # Extract the shared glyph so it follows one path instead of appearing
        # twice in two fading, differently positioned screenshots.
        clear=QPainter(image);clear.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        clear.fillRect(QRectF(QPointF(icon_pos),QSizeF(icon.size())),Qt.GlobalColor.transparent);clear.end()
        glyph=snapshot(icon) if not minimal else QPixmap();glyph_rect=QRectF(QPointF(origin+offset+icon_pos),QSizeF(icon.size())) if not minimal else QRectF(rect.center(),QSizeF(0,0))
        if minimal:image=snapshot(root)
        satellites=[]
        if island:
            for name in ('island_shortcut','island_quota'):
                widget=next((w for w in bubble.findChildren(QToolButton,name) if w.isVisibleTo(bubble.content)),None)
                if widget:
                    pos=widget.mapTo(bubble.content,QPoint());satellites.append((QRectF(QPointF(origin+pos),QSizeF(widget.size())),snapshot(widget)))
        screen=bubble.screen()
        return cls(rect,image,glyph_rect,glyph,island,satellites,complete_frame(bubble),QPointF(origin),QPointF(screen.geometry().topLeft()) if screen else QPointF(),root.height()/2 if island or minimal else PANEL_RADIUS)


def mix_rect(a,z,f):
    return QRectF(a.x()+(z.x()-a.x())*f,a.y()+(z.y()-a.y())*f,a.width()+(z.width()-a.width())*f,a.height()+(z.height()-a.height())*f)


class SurfaceMorph:
    def __init__(self,start,end):
        self.start=start;self.end=end;self._landing=None
        self.shrinking=end.rect.width()*end.rect.height()<start.rect.width()*start.rect.height()
    def content_opacities(self,time):
        if not self.start.island and not self.end.island and self.start.radius==PANEL_RADIUS and self.end.radius==PANEL_RADIUS:
            # Normal/detail cards share a surface. Do not fade both contents
            # to zero midway: that exposes a blank white card as a flash.
            incoming=stage(time,.10,.72)
            return 1.-incoming,incoming
        if self.shrinking:
            incoming=stage(time,.08,.42)
            return 1.-incoming,incoming
        return 1.-stage(time,0.,.18),stage(time,.24,.62)
    def geometry(self,time):
        a,z=self.start.rect,self.end.rect;f=container_progress(time)
        # One progress for every edge; staggered spring axes can visibly twist
        # the small capsule when it becomes a tall editor.
        width=a.width()+(z.width()-a.width())*f;height=a.height()+(z.height()-a.height())*f
        center=a.center().x()+(z.center().x()-a.center().x())*f
        bottom=a.bottom()+(z.bottom()-a.bottom())*f
        return QRectF(center-width/2,bottom-height,width,height)
    def bounds(self):
        rect=self.start.rect.united(self.end.rect)
        for i in range(101):rect=rect.united(self.geometry(i/100))
        for state in (self.start,self.end):
            for satellite,image in state.satellites:rect=rect.united(satellite)
        return rect.adjusted(-1,-1,1,1).toAlignedRect()
    def prepare_landing(self,canvas,ratio):
        if self.end.frame is None:return
        key=(canvas.x(),canvas.y(),canvas.width(),canvas.height(),ratio)
        if self._landing is not None and self._landing[0]==key:return
        frames=[]
        for native in (False,True):
            image=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
            q=QPainter(image)
            if native:
                z=self.end;q.drawPixmap(raster_offset(z.frame_origin,canvas.topLeft(),ratio,z.screen_origin),z.frame)
            else:self._paint_body(q,1.,canvas)
            q.end();frames.append(image)
        self._landing=(key,frames,frames[0].copy(),frames[0].copy())
    def paint(self,p,time,canvas):
        if time<=0 and self.start.frame is not None:
            a=self.start;p.drawPixmap(raster_offset(a.frame_origin,canvas.topLeft(),p.device().devicePixelRatioF(),a.screen_origin),a.frame);return
        if time>=.9 and self.end.frame is not None:
            self.prepare_landing(canvas,p.device().devicePixelRatioF())
            f=stage(time,.9,1.);a,z=self._landing[1]
            # Premultiplied interpolation preserves alpha at translucent edges.
            # QWidget backing stores do not support every composition mode;
            # perform Plus on a raster pixmap, then submit one opaque frame.
            # Weight the source first: Plus with constant painter opacity falls
            # back to SourceOver on Qt raster paths. Complementary 8-bit alpha
            # weights keep an opaque center exactly opaque through the blend.
            weight=round(f*255);weighted=self._landing[3];weighted.fill(Qt.GlobalColor.transparent)
            q=QPainter(weighted);q.setOpacity((weight+1)/256);q.drawPixmap(0,0,z);q.end()
            mixed=self._landing[2];mixed.fill(Qt.GlobalColor.transparent);q=QPainter(mixed)
            q.setOpacity((256-weight)/256);q.drawPixmap(0,0,a)
            q.setOpacity(1.);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus);q.drawPixmap(0,0,weighted);q.end()
            p.drawPixmap(0,0,mixed);return
        self._paint_body(p,time,canvas)
    def _paint_body(self,p,time,canvas):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a,z=self.start,self.end;rect=self.geometry(time).translated(-canvas.x(),-canvas.y())
        f=container_progress(time);blend=stage(time,0.,.42)
        ca=QColor(ISLAND if a.island else SURFACE);cz=QColor(ISLAND if z.island else SURFACE)
        color=QColor(*[round(x+(y-x)*blend) for x,y in zip(ca.getRgb(),cz.getRgb())])
        radius=a.radius+(z.radius-a.radius)*f
        # Match the live widget's inset fill/stroke, including antialiased alpha.
        # Filling the entire uninset rect left a brighter edge at handoff.
        inset=rect.adjusted(.5,.5,-.5,-.5)
        border_a=QColor('#494052' if a.island else '#e0d9e6');border_z=QColor('#494052' if z.island else '#e0d9e6')
        border=QColor(*[round(x+(y-x)*blend) for x,y in zip(border_a.getRgb(),border_z.getRgb())])
        path=QPainterPath();path.addRoundedRect(inset,radius,radius)
        p.save();p.setPen(QPen(border,1));p.setBrush(color);p.drawRoundedRect(inset,radius,radius);p.setClipPath(path)
        outgoing,incoming=self.content_opacities(time)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for state,opacity,scale in ((a,outgoing,1.-.025*stage(time,0.,.18)),(z,incoming,.975+.025*incoming)):
            if opacity<=0:continue
            size=state.content.deviceIndependentSize();w=size.width()*scale;h=size.height()*scale
            target=QRectF(rect.center().x()-w/2,rect.center().y()-h/2,w,h)
            p.setOpacity(opacity);p.drawPixmap(target,state.content,QRectF(state.content.rect()))
        # Same semantic icon, moving once between the corresponding positions.
        start_icon=a.icon_rect.translated(-a.rect.x(),-a.rect.y());end_icon=z.icon_rect.translated(-z.rect.x(),-z.rect.y())
        nx=start_icon.center().x()/a.rect.width()+(end_icon.center().x()/z.rect.width()-start_icon.center().x()/a.rect.width())*f
        ny=start_icon.center().y()/a.rect.height()+(end_icon.center().y()/z.rect.height()-start_icon.center().y()/a.rect.height())*f
        icon=mix_rect(start_icon,end_icon,f);icon.moveCenter(QPointF(rect.x()+rect.width()*nx,rect.y()+rect.height()*ny))
        for image,opacity in ((a.icon,1.-blend),(z.icon,blend)):
            if opacity>0:p.setOpacity(opacity);p.drawPixmap(icon,image,QRectF(image.rect()))
        p.restore();p.setOpacity(1.)
        for state,entering in ((a,False),(z,True)):
            motion=stage(time,.32,.82) if entering else stage(time,0.,.4)
            opacity=stage(time,.42,.8) if entering else 1.-stage(time,0.,.2)
            if opacity<=0:continue
            for satellite,image in state.satellites:
                source=satellite.center()+(state.rect.center()-satellite.center())*.10 if entering else satellite.center()
                target=satellite.center() if entering else satellite.center()+(state.rect.center()-satellite.center())*.10
                center=source+(target-source)*motion-QPointF(canvas.x(),canvas.y())
                scale=.88+.12*motion if entering else 1.-.12*motion
                r=QRectF(center.x()-satellite.width()*scale/2,center.y()-satellite.height()*scale/2,satellite.width()*scale,satellite.height()*scale)
                p.setOpacity(opacity);p.drawPixmap(r,image,QRectF(image.rect()))
        p.setOpacity(1.)
