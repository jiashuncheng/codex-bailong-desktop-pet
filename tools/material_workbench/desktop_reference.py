"""Read-only desktop layout references; never move or change the running pet."""
from pathlib import Path
import ast,json,math
from PySide6.QtCore import QRect,QRectF
from PySide6.QtWidgets import QApplication

MODES=['面板＋胶囊','只看面板','只看胶囊','隐藏面板参照']
def read_json(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default

def display_factor(config):
    data=Path(config['data_dir']);settings=read_json(data/'settings.json',{}) or {}
    manifest=read_json(data/'characters'/config['character_key']/'素材清单.json',{}) or {}
    layout=manifest.get('canvasLayout',{})
    return float(layout.get('displayHeight',607*256/720))*float(settings.get('scale',1))/float(layout.get('referenceHeight',607))

def constants(path,names,defaults):
    result=dict(defaults)
    try:
        for node in ast.parse(Path(path).read_text(encoding='utf-8-sig')).body:
            if isinstance(node,ast.Assign):
                for target in node.targets:
                    if isinstance(target,ast.Name) and target.id in names:
                        value=ast.literal_eval(node.value)
                        if isinstance(value,(int,float)) and math.isfinite(value):result[target.id]=value
    except (OSError,ValueError,SyntaxError):pass
    return result

def character_rect(position,size,layout):
    cw,ch=layout.get('canvas',[720,720]);bounds=layout.get('panelBounds',[44,52,678,676])
    l,t,r,b=bounds;sx=size[0]/cw;sy=size[1]/ch
    return QRectF(position[0]+l*sx,position[1]+t*sy,(r-l)*sx,(b-t)*sy).toAlignedRect()

def attached_rect(size,character,area):
    """Same compact-card positioning and collision gap as CompactBubble."""
    w,h=size;x=character.x()+(character.width()-w)//2;y=character.y()-h-8
    if y<area.top():y=character.bottom()+9
    x=max(area.left(),min(x,area.right()-w+1));y=max(area.top(),min(y,area.bottom()-h+1))
    preferred=QRect(x,y,w,h);blocked=character.adjusted(-8,-8,8,8)
    if not preferred.intersects(blocked):return preferred
    def bounded(x,y):return QRect(max(area.left(),min(x,area.right()-w+1)),max(area.top(),min(y,area.bottom()-h+1)),w,h)
    choices=[preferred,bounded(x,blocked.top()-h),bounded(x,blocked.bottom()+1),bounded(blocked.left()-w,y),bounded(blocked.right()+1,y)]
    def score(rect):
        overlap=rect.intersected(blocked)
        return overlap.width()*overlap.height(),(rect.x()-x)**2+(rect.y()-y)**2
    return min(choices,key=score)

def load_desktop_reference(config,screen_rects=None):
    data=Path(config['data_dir']);settings=read_json(data/'settings.json',{}) or {};runtime=read_json(data/'runtime.json',{}) or {}
    manifest=read_json(data/'characters'/config['character_key']/'素材清单.json',{}) or {};layout=manifest.get('canvasLayout',{})
    factor=display_factor(config);cw,ch=layout.get('canvas',[720,720]);anchor=layout.get('anchor',[360,668])
    same=bool(runtime.get('character_logical_size') and settings.get('character')==config['character_key'] and runtime.get('quality_revision')==manifest.get('qualityRevision') and abs(float(runtime.get('scale',-1))-float(settings.get('scale',1)))<1e-6)
    position=list(runtime.get('position',[0,0])) if same else [0,0]
    size=list(runtime['character_logical_size']) if same else [round(cw*factor),round(ch*factor)]
    foot=[position[0]+anchor[0]/cw*size[0],position[1]+anchor[1]/ch*size[1]]
    character=character_rect(position,size,layout)
    if screen_rects is None and same:
        app=QApplication.instance();screen_rects=[s.availableGeometry() for s in app.screens()] if app else []
    if screen_rects is None:screen_rects=[]
    area=next((r for r in screen_rects if r.contains(character.center())),None)
    if area is None:area=QRect(character.center().x()-2000,character.top()-2000,4000,4000)
    role_scale=float(settings.get('scale',1));panel_scale=max(.8,min(1.5,1+(role_scale-1)*.5))
    native=constants(Path(config.get('app_root',''))/'app/island_widgets.py',('WIDTH','HEIGHT'),dict(WIDTH=246,HEIGHT=44))
    capsule_size=[math.ceil((native['WIDTH'] if settings.get('quota_visible',True) else native['WIDTH']-43)*panel_scale),math.ceil(native['HEIGHT']*panel_scale)]
    panel_size=[math.ceil(268*panel_scale),math.ceil(205*panel_scale)]
    bounds=runtime.get('bubble_bounds')
    mode='capsule' if runtime.get('island_visible') else 'minimal' if bounds and bounds[2]<80 else 'panel'
    live=bool(same and runtime.get('panel_page','status')=='status' and bounds and len(bounds)==4 and bounds[2]>0 and bounds[3]>0)
    if live and mode=='panel':panel_size=list(bounds[2:])
    if live and mode=='capsule':capsule_size=list(bounds[2:])
    rects={key:attached_rect(sz,character,area) for key,sz in (('panel',panel_size),('capsule',capsule_size))}
    detached=bool(settings.get('panel_detached'))
    if detached and live:
        cx=bounds[0]+bounds[2]/2;bottom=bounds[1]+bounds[3]
        for key,sz in (('panel',panel_size),('capsule',capsule_size)):rects[key]=QRect(round(cx-sz[0]/2),round(bottom-sz[1]),*sz)
    if live and mode in rects:rects[mode]=QRect(*bounds)
    items=[]
    for key,title in (('panel','状态栏 / 面板'),('capsule','胶囊')):
        rect=rects[key];items.append(dict(key=key,title=title,offset=[rect.x()-foot[0],rect.y()-foot[1],rect.width(),rect.height()],source='运行记录' if live and mode==key else '按源码布局估算'))
    description='；'.join(f"{v['title']} {v['offset'][2]}×{v['offset'][3]}px（{v['source']}）" for v in items)
    return dict(factor=factor,items=items,description=description,detached=detached,live=live,mode=mode,quota_visible=settings.get('quota_visible',True))

def visible_items(reference,mode=MODES[0]):
    if not reference or mode==MODES[3]:return []
    return [v for v in reference.get('items',[]) if mode==MODES[0] or v['key']==('panel' if mode==MODES[1] else 'capsule')]

def reference_rects(scene,mode=MODES[0]):
    reference=(scene or {}).get('desktop_reference');anchor=(scene or {}).get('anchor',[0,0]);result=[]
    for item in visible_items(reference,mode):
        x,y,w,h=item['offset'];f=reference['factor']
        result.append((item,QRectF(anchor[0]+x/f,anchor[1]+y/f,w/f,h/f)))
    return result
