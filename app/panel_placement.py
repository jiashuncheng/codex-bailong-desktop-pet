"""Place a card and its report together without moving the character."""
from PySide6.QtCore import QRect,QRectF,QPointF
from bisect import bisect_left
import math


def character_geometry(owner):
    """Stable visible envelope, opt-in for padded rectangular character packs.

    Never inspect pixels on a frame clock. The declared animation envelope is
    mapped through the same source target used for painting, then translated
    into global logical coordinates. Legacy packs retain their HWND bounds.
    """
    fallback=owner.frameGeometry()
    manifest=getattr(owner,'manifest',{})
    value=manifest.get('canvasLayout') if isinstance(manifest,dict) else None
    if not isinstance(value,dict) or value.get('schema')!=1:return fallback
    bounds=value.get('panelBounds',value.get('alphaUnion'))
    if bounds is None or not hasattr(owner,'frame_target'):return fallback
    try:
        width,height=map(float,value['canvas'])
        left,top,right,bottom=map(float,bounds)
        if not all(math.isfinite(v) for v in (width,height,left,top,right,bottom)):return fallback
        if not 0<=left<right<=width or not 0<=top<bottom<=height:return fallback
        target=owner.frame_target(QRectF(owner.rect()))
        rect=QRectF(target.x()+target.width()*left/width,
                    target.y()+target.height()*top/height,
                    target.width()*(right-left)/width,
                    target.height()*(bottom-top)/height)
        return rect.translated(fallback.x(),fallback.y()).toAlignedRect()
    except (KeyError,TypeError,ValueError,OverflowError):return fallback


def distance(a,b):return math.hypot(b.x()-a.x(),b.y()-a.y())


class RoundedRoute:
    """Prepared line/quadratic path with an arc-length lookup for playback."""
    def __init__(self,points,radius):
        self.points=tuple(QPointF(p) for i,p in enumerate(points) if not i or p!=points[i-1])
        segments=[];last=self.points[0]
        for a,p,z in zip(self.points,self.points[1:],self.points[2:]):
            before,after=distance(a,p),distance(p,z)
            cut=min(radius,before*.4,after*.4)
            incoming=p+(a-p)*(cut/before);outgoing=p+(z-p)*(cut/after)
            if distance(last,incoming)>1e-8:segments.append((last,None,incoming))
            if cut:segments.append((incoming,p,outgoing))
            last=outgoing
        if distance(last,self.points[-1])>1e-8:segments.append((last,None,self.points[-1]))
        self.segments=tuple(segments);lengths=[0.];samples=[(0,0.)];last=self.points[0]
        for index,segment in enumerate(self.segments):
            steps=32 if segment[1] is not None else 1
            for step in range(1,steps+1):
                t=step/steps;point=self.evaluate(segment,t)
                lengths.append(lengths[-1]+distance(last,point));samples.append((index,t));last=point
        self.lengths=tuple(lengths);self.samples=tuple(samples);self.length=lengths[-1]
    @staticmethod
    def evaluate(segment,t):
        a,c,z=segment
        return a+(z-a)*t if c is None else a*((1.-t)**2)+c*(2.*t*(1.-t))+z*(t*t)
    def point_at(self,f):
        if f<=0 or not self.length:return QPointF(self.points[0])
        if f>=1:return QPointF(self.points[-1])
        target=f*self.length;index=bisect_left(self.lengths,target)
        segment,end=self.samples[index];previous,start=self.samples[index-1]
        if previous!=segment:start=0.
        low,high=self.lengths[index-1:index+1]
        t=start+(end-start)*(target-low)/(high-low)
        return self.evaluate(self.segments[segment],t)
    def translated(self,delta):
        result=object.__new__(type(self))
        result.points=tuple(p+delta for p in self.points)
        result.segments=tuple((a+delta,c+delta if c is not None else None,z+delta) for a,c,z in self.segments)
        result.lengths=self.lengths;result.samples=self.samples;result.length=self.length
        return result


def occupied_rect(card, reserve=0, overhang=0):
    return card.adjusted(-overhang, -reserve, overhang, 0)


def avoid_character(card, character, area, reserve=0, report_width=0, gap=8):
    card=QRect(card);reserve=max(0,min(reserve,area.height()-card.height()))
    overhang=max(0,(report_width-card.width()+1)//2+8) if reserve else 0
    def bounded(x,y):
        x=max(area.left()+overhang,min(x,area.right()-card.width()+1-overhang))
        y=max(area.top()+reserve,min(y,area.bottom()-card.height()+1))
        return QRect(x,y,card.width(),card.height())
    preferred=bounded(card.x(),card.y())
    if character is None:return preferred
    blocked=character.adjusted(-gap,-gap,gap,gap)
    if not occupied_rect(preferred,reserve,overhang).intersects(blocked):return preferred
    candidates=[preferred,
        bounded(preferred.x(),blocked.top()-card.height()),
        bounded(preferred.x(),blocked.bottom()+1+reserve),
        bounded(blocked.left()-card.width()-overhang,preferred.y()),
        bounded(blocked.right()+1+overhang,preferred.y())]
    def score(rect):
        overlap=occupied_rect(rect,reserve,overhang).intersected(blocked)
        return (overlap.width()*overlap.height(),
            (rect.x()-preferred.x())**2+(rect.y()-preferred.y())**2)
    return min(candidates,key=score)


def morph_rect(start,end,f,route=None):
    width=start.width()+(end.width()-start.width())*f
    height=start.height()+(end.height()-start.height())*f
    if isinstance(route,RoundedRoute):point=route.point_at(f)
    else:
        points=route or (QPointF(start.center().x(),start.bottom()),QPointF(end.center().x(),end.bottom()))
        lengths=[(b-a).manhattanLength() for a,b in zip(points,points[1:])]
        remaining=f*sum(lengths);point=points[-1]
        for a,b,length in zip(points,points[1:],lengths):
            if remaining<=length:
                point=a+(b-a)*(remaining/length if length else 0.);break
            remaining-=length
    return QRectF(point.x()-width/2,point.y()-height,width,height)


def morph_route(start,end,character):
    """Prepare waypoints once; the frame clock only interpolates rectangles."""
    blocked=QRectF(character).adjusted(-4,-4,4,4)
    if start.intersects(blocked) or end.intersects(blocked):return None
    def safe(route,steps=100):
        return all(not morph_rect(start,end,i/steps,route).intersects(blocked) for i in range(steps+1))
    if safe(None):return None
    a=QPointF(start.center().x(),start.bottom());z=QPointF(end.center().x(),end.bottom())
    width=max(start.width(),end.width())/2
    paths=[(a,QPointF(z.x(),a.y()),z),(a,QPointF(a.x(),z.y()),z)]
    for x in (blocked.left()-width-1,blocked.right()+width+1):
        paths.append((a,QPointF(x,a.y()),QPointF(x,z.y()),z))
    valid=[p for p in paths if safe(p)]
    if not valid:return None
    for radius in (28.,18.,10.,4.):
        rounded=[RoundedRoute(path,radius) for path in valid]
        rounded=[route for route in rounded if safe(route,200)]
        if rounded:return min(rounded,key=lambda route:route.length)
    return RoundedRoute(min(valid,key=lambda p:sum(distance(a,b) for a,b in zip(p,p[1:]))),0.)
