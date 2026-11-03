"""Place a card and its report together without moving the character."""
from PySide6.QtCore import QRect,QRectF,QPointF


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
    def safe(route):
        return all(not morph_rect(start,end,i/100,route).intersects(blocked) for i in range(101))
    if safe(None):return None
    a=QPointF(start.center().x(),start.bottom());z=QPointF(end.center().x(),end.bottom())
    width=max(start.width(),end.width())/2
    paths=[(a,QPointF(z.x(),a.y()),z),(a,QPointF(a.x(),z.y()),z)]
    for x in (blocked.left()-width-1,blocked.right()+width+1):
        paths.append((a,QPointF(x,a.y()),QPointF(x,z.y()),z))
    valid=[p for p in paths if safe(p)]
    return min(valid,key=lambda p:sum((b-a).manhattanLength() for a,b in zip(p,p[1:]))) if valid else None
