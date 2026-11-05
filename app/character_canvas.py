"""Opt-in rectangular character canvases; legacy square packs keep their layout."""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class CanvasLayout:
    width:float
    height:float
    anchor_x:float
    anchor_y:float
    reference_height:float
    display_height:float

    def size(self,scale):
        factor=self.display_height*scale/self.reference_height
        return max(1,round(self.width*factor)),max(1,round(self.height*factor))

    def anchor(self,width,height):
        return self.anchor_x/self.width*width,self.anchor_y/self.height*height

def layout(manifest):
    if not isinstance(manifest,dict):raise ValueError('角色清单结构无效')
    value=manifest.get('canvasLayout')
    if value is None:return None
    if not isinstance(value,dict) or value.get('schema')!=1:raise ValueError('角色画布布局版本无效')
    try:
        width,height=map(float,value['canvas'])
        x,y=map(float,value['anchor'])
        reference=float(value['referenceHeight'])
        display=float(value['displayHeight'])
    except (KeyError,ValueError,TypeError,OverflowError):raise ValueError('角色画布布局参数无效') from None
    values=(width,height,x,y,reference,display)
    if not all(math.isfinite(v) for v in values):raise ValueError('角色画布布局参数必须有限')
    if not (1<=width<=4096 and 1<=height<=4096 and 0<=x<=width and 0<=y<=height and 1<=reference<=height and 32<=display<=512):
        raise ValueError('角色画布布局参数超出范围')
    bounds=value.get('alphaUnion',[0,0,width,height])
    try:
        left,top,right,bottom=map(float,bounds)
        if not all(math.isfinite(v) for v in (left,top,right,bottom)):raise ValueError
        if not (0<=left<right<=width and 0<=top<bottom<=height):raise ValueError
    except (ValueError,TypeError,OverflowError):raise ValueError('角色透明边界无效') from None
    return CanvasLayout(*values)

def square_anchor(manifest,root):
    """Inspect only the standard idle frame at character-switch preparation."""
    from pathlib import Path
    from PIL import Image
    item=manifest['idle'];path=Path(root)/(item.get('playbackFile') or item['file'])
    with Image.open(path) as image:
        alpha=image.convert('RGBA').getchannel('A').point(lambda a:255 if a>=100 else 0)
        box=alpha.getbbox()
        return (.5,box[3]/image.height) if box else (.5,1.)
