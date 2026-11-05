"""Per-platform paths without overwriting another device's configuration."""
from pathlib import Path
import copy,json,os,re,sys
PATH_KEYS=('input_dir','output_dir','state_dir','data_dir','app_root','python','runtime')

def source_root(base):
    """Find a checkout without depending on a particular user's folder names."""
    base=Path(base).resolve()
    candidates=list((base,*base.parents))
    candidates.extend((base.parent/'白龙桌宠源码版',base.parent.parent/'白龙桌宠源码版'))
    return next((p for p in candidates if (p/'run_source.py').is_file() and (p/'app').is_dir()),None)

def defaults(platform=None,home=None):
    platform=platform or sys.platform;home=Path(home or Path.home())
    if os.environ.get('BAILONG_DATA_DIR'):data=Path(os.environ['BAILONG_DATA_DIR']).expanduser()
    elif platform=='win32':data=Path(os.environ.get('LOCALAPPDATA',str(home/'AppData/Local')))/'BailongEnhanced'
    elif platform=='darwin':data=home/'Library/Application Support/BailongMac'
    else:data=home/'.local/share/BailongMac'
    return dict(data_dir=str(data),state_dir=str(data/'tools/bailong-oneclick-state'),runtime=str(data/'tools/baby-matting-runtime'))

def normalize(raw,base,platform=None,home=None):
    platform=platform or sys.platform;base=Path(base);cfg=copy.deepcopy(raw)
    slots=raw.get('platforms',{});slot=slots.get(platform,{})
    cfg.update(slot)
    if platform!='win32' and not slot:
        fallback=defaults(platform,home)
        for key in PATH_KEYS:
            if re.match(r'^[A-Za-z]:[\\/]',str(cfg.get(key,''))):cfg[key]=''
        for key,value in fallback.items():cfg[key]=cfg.get(key) or value
        candidate=source_root(base)
        cfg['app_root']=cfg.get('app_root') or (str(candidate) if candidate else '')
        src=base.parent/'白龙自定义新增素材';cfg['input_dir']=cfg.get('input_dir') or str(src if src.is_dir() else base.parent)
        cfg['output_dir']=cfg.get('output_dir') or str(Path(cfg['input_dir'])/'已处理')
        if cfg['app_root']:
            exe=Path(cfg['app_root'])/'.venv/bin/python'
            cfg['python']=cfg.get('python') or (str(exe) if exe.is_file() else sys.executable)
        else:cfg['python']=cfg.get('python') or sys.executable
    for key,value in defaults(platform,home).items():cfg[key]=cfg.get(key) or value
    cfg.setdefault('character_key','bailong-custom-final');cfg.setdefault('extra_scale',1.)
    cfg.setdefault('recursive',True);cfg.setdefault('prefer_export_subdir',True)
    cfg.setdefault('settle_seconds',3);cfg.setdefault('overrides',{})
    cfg.setdefault('clip_encodings',['q95','lossless'])
    cfg['input_dir']=cfg.get('input_dir') or str(base/'input')
    cfg['output_dir']=cfg.get('output_dir') or str(base/'processed')
    candidate=source_root(base)
    cfg['app_root']=cfg.get('app_root') or (str(candidate) if candidate else '')
    if not cfg.get('python'):
        exe=Path(cfg['app_root'])/('.venv/Scripts/python.exe' if platform=='win32' else '.venv/bin/python')
        cfg['python']=str(exe) if exe.is_file() else sys.executable
    for key in PATH_KEYS:
        value=cfg.get(key)
        if value and not re.match(r'^[A-Za-z]:[\\/]',value):
            path=Path(value).expanduser()
            cfg[key]=str(path if path.is_absolute() else (base/path).resolve())
    return cfg

def load_config(path,platform=None,home=None):
    path=Path(path);raw=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    return normalize(raw,path.parent,platform,home)

def save_config(path,cfg,platform=None):
    path=Path(path);platform=platform or sys.platform
    raw=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    raw.setdefault('platforms',{})[platform]={k:cfg[k] for k in PATH_KEYS if k in cfg}
    for key in ('extra_scale','auto_apply','action_names','preview_background','preview_speed','adjustments','stabilize_actions','processed_profiles','automatic_actions','clip_encodings'):
        if key in cfg:raw[key]=cfg[key]
    # Retain the established Windows CLI configuration; other platforms use their slot.
    if platform=='win32':
        for key in PATH_KEYS:
            if key in cfg:raw[key]=cfg[key]
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,path)

def pillow_font(size):
    from PIL import ImageFont
    choices=['C:/Windows/Fonts/msyh.ttc','/System/Library/Fonts/PingFang.ttc',
             '/System/Library/Fonts/STHeiti Medium.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for name in choices:
        if Path(name).is_file():
            try:return ImageFont.truetype(name,size)
            except OSError:pass
    return ImageFont.load_default(size=size)
