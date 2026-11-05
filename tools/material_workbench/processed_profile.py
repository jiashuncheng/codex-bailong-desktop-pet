"""Validated, path-free calibration carried in WebP XMP across edits."""
from pathlib import Path
import json,math,xml.etree.ElementTree as ET
from PIL import Image

NS='https://github.com/jiashuncheng/codex-bailong-desktop-pet/ns/1.0/'
def validate(profile,size=None):
    if not isinstance(profile,dict) or profile.get('schema')!=1 or profile.get('kind')!='bailong-processed':raise ValueError('已处理素材的校准信息无效')
    canvas=profile.get('canvas');anchor=profile.get('anchor')
    if not isinstance(canvas,list) or len(canvas)!=2 or any(type(v) is not int or not 1<=v<=2048 for v in canvas):raise ValueError('校准画布无效')
    if not isinstance(anchor,list) or len(anchor)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=canvas[i] for i,v in enumerate(anchor)):raise ValueError('校准脚底无效')
    if size is not None and list(size)!=canvas:raise ValueError('校准信息与实际画布不一致，请重新导出')
    height=profile.get('referenceHeight',607)
    if type(height) not in (int,float) or not math.isfinite(height) or height<=0:raise ValueError('参考身高无效')
    return dict(schema=1,kind='bailong-processed',canvas=list(canvas),anchor=list(anchor),referenceHeight=height,
                stabilizationBaked=bool(profile.get('stabilizationBaked',False)))

def from_layout(layout,baked=False):
    return validate(dict(schema=1,kind='bailong-processed',canvas=list(layout['canvas']),anchor=list(layout['anchor']),referenceHeight=layout.get('referenceHeight',607),stabilizationBaked=baked))

def encode(profile):
    profile=validate(profile)
    root=ET.Element('{adobe:ns:meta/}xmpmeta');rdf=ET.SubElement(root,'{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF')
    ET.SubElement(rdf,'{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description',{'{'+NS+'}profile':json.dumps(profile,separators=(',',':'))})
    return ET.tostring(root,encoding='utf-8')

def read(path):
    if Path(path).suffix.lower()!='.webp':return None
    with Image.open(path) as image:
        data=image.info.get('xmp');size=image.size
    if not data:return None
    if len(data)>32768:raise ValueError('素材校准信息过大')
    try:
        root=ET.fromstring(data)
        value=next((node.attrib['{'+NS+'}profile'] for node in root.iter() if '{'+NS+'}profile' in node.attrib),None)
        return validate(json.loads(value),size) if value else None
    except (ET.ParseError,json.JSONDecodeError) as error:raise ValueError('素材校准信息损坏') from error

def edit_layout(infos):
    profiles=[info.profile for info in infos]
    if not any(profiles):return None,None
    if not all(profiles):raise ValueError('已校准素材和未校准原片请先统一处理，再拼接')
    profiles=[validate(p,info.size) for p,info in zip(profiles,infos)]
    if len({p['referenceHeight'] for p in profiles})!=1:raise ValueError('参考身高不一致，请先统一人物尺度')
    anchor=[max(p['anchor'][i] for p in profiles) for i in (0,1)]
    canvas=[math.ceil(anchor[i]+max(p['canvas'][i]-p['anchor'][i] for p in profiles)) for i in (0,1)]
    profile=from_layout(dict(canvas=canvas,anchor=anchor,referenceHeight=profiles[0]['referenceHeight']),baked=all(p['stabilizationBaked'] for p in profiles))
    return tuple(canvas),profile
