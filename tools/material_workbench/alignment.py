"""Per-action corrections in the original white-dragon master coordinate system."""
import copy,math

IDENTITY={'scale':1.,'offset':[0.,0.]}

def manual_values(value=None):
    value=value or {};scale=float(value.get('scale',1));offset=list(map(float,value.get('offset',[0,0])))
    if not math.isfinite(scale) or not .25<=scale<=2.5:raise ValueError('手动大小应在25%到250%之间')
    if len(offset)!=2 or not all(math.isfinite(v) and abs(v)<=2048 for v in offset):raise ValueError('手动位置超出可用范围')
    return dict(scale=scale,offset=offset)

def adjusted_record(record,adjustment=None):
    result=copy.deepcopy(record);base=copy.deepcopy(record.get('automaticTransform',record['transform']))
    manual=manual_values(adjustment);transform=copy.deepcopy(base)
    transform['scale']=base['scale']*manual['scale'];transform['offset']=manual['offset']
    if not .05<=transform['scale']<=12.5:raise ValueError('人物缩放超出范围')
    result.update(automaticTransform=base,transform=transform,manualAdjustment=manual)
    return result

def placement_rect(transform,anchor):
    sw,sh=transform['sourceSize'];scale=transform['scale'];w=max(1,round(sw*scale));h=max(1,round(sh*scale))
    ax,ay=transform['anchor'];dx,dy=transform.get('offset',[0,0])
    return [round(anchor[0]-ax*w/sw+dx),round(anchor[1]-ay*h/sh+dy),w,h]
