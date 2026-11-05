"""Bounded sample encodes for per-preset estimates, plus known exact results."""
from pathlib import Path
import hashlib,json,math,tempfile
import numpy as np
from clip_editing import bounds,composition,compose_frame,can_copy_lossless,snapshot,check_cancel,MAX_MS,MAX_FRAMES
from encoding_presets import PRESETS,preset
from media import frames,write_animation,atomic_json
import processed_profile

def identity(clips,infos,code):
    preset(code)
    values=[dict(path=str(Path(c.path).resolve()),stamp=infos[str(Path(c.path).resolve())].stamp,
        profile=infos[str(Path(c.path).resolve())].profile,start=c.start_ms,end=c.end_ms,repeat=c.repeat) for c in clips]
    return hashlib.sha256(json.dumps(dict(revision=2,clips=values,encoding=code),sort_keys=True).encode()).hexdigest()

def read_cache(directory):
    path=Path(directory)/'encoding-size-cache.json'
    try:
        if path.stat().st_size>2_000_000:return {}
        value=json.loads(path.read_text(encoding='utf-8'));return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}

def remember_actual(directory,clips,infos,results):
    cached=read_cache(directory)
    for result in results:
        size=result.get('bytes')
        if type(size) is int and size>0:cached[identity(clips,infos,result.get('encoding','lossless'))]=size
    atomic_json(Path(directory)/'encoding-size-cache.json',dict(list(cached.items())[-256:]))

def timeline(clips,infos):
    result=[];total=0
    for clip in clips:
        path=str(Path(clip.path).resolve());info=infos[path];start,end,repeat=bounds(clip,info);position=0;part=[]
        for index,ms in enumerate(info.durations):
            overlap=min(position+ms,end)-max(position,start)
            if overlap>0:part.append((path,index,int(overlap)))
            position+=ms
            if position>=end:break
        result.extend(part*repeat);total+=(end-start)*repeat
    if not result or len(result)>MAX_FRAMES or total>MAX_MS:raise ValueError('请使用60秒、3600帧以内的有效选段')
    return result

def estimate(clips,infos,codes=None,directory=None,cancel=lambda:False):
    clips=list(clips);codes=list(codes or PRESETS);infos=dict(infos)
    if not clips:raise ValueError('请先添加片段')
    used={str(Path(c.path).resolve()):infos[str(Path(c.path).resolve())] for c in clips}
    for path,info in used.items():
        if snapshot(path)!=info.stamp:raise ValueError('原片已更新，请刷新后再估算')
    canvas,profile=composition(used.values());sequence=timeline(clips,used)
    known=read_cache(directory) if directory else {};results={};pending=[]
    for code in codes:
        preset(code);check_cancel(cancel);size=known.get(identity(clips,used,code))
        if type(size) is int and size>0:
            results[code]=dict(bytes=size,low=size,high=size,exact=True,source='previous-export');continue
        if code=='lossless' and can_copy_lossless(clips,used,canvas,profile):
            size=Path(clips[0].path).stat().st_size
            results[code]=dict(bytes=size,low=size,high=size,exact=True,source='original-bytes');continue
        pending.append(code)
    if not pending:return results
    # At most twelve native-size frames and roughly 64 MB of RGBA samples.
    budget=max(1,min(12,64_000_000//max(1,canvas[0]*canvas[1]*4)))
    if len(sequence)<=budget:windows=[list(range(len(sequence)))]
    else:
        length=min(3,budget);count=max(1,min(3,budget//length))
        starts=np.linspace(0,len(sequence)-length,count).round().astype(int)
        windows=[list(range(int(start),int(start)+length)) for start in starts]
    positions=sorted(set(p for window in windows for p in window));needed={}
    for p in positions:
        path,index,_=sequence[p];needed.setdefault(path,set()).add(index)
    images={}
    for path,indexes in needed.items():
        iterator=frames(path);last=max(indexes)
        try:
            for index,(image,_) in enumerate(iterator):
                check_cancel(cancel)
                if index in indexes:images[(path,index)]=compose_frame(image,used[path],canvas,profile)
                if index>=last:break
        finally:iterator.close()
    parent=Path(directory) if directory else None
    if parent:parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='size-sample-',dir=parent) as temporary:
        for code in pending:
            rates=[];sizes=[]
            for window in windows:
                check_cancel(cancel);target=Path(temporary)/(code+'.webp')
                def sample():
                    for p in window:
                        check_cancel(cancel);path,index,ms=sequence[p];yield images[(path,index)],ms
                write_animation(target,sample(),xmp=processed_profile.encode(profile) if profile else None,encoding=code)
                size=target.stat().st_size;sizes.append(size);rates.append(size/len(window))
            central=max(1,round(float(np.mean(rates))*len(sequence)))
            exact=len(windows)==1 and len(windows[0])==len(sequence)
            variability=float(np.std(rates)/max(1,np.mean(rates)))
            uncertainty=min(.65,max(.25,.25+variability*.7)) if len(windows)>1 else .50
            if exact:central=sizes[0];uncertainty=0
            results[code]=dict(bytes=central,low=max(1,round(central*(1-uncertainty))),high=round(central*(1+uncertainty)),
                exact=exact,source='sample-encode',sampleFrames=len(positions),totalFrames=len(sequence))
    check_cancel(cancel)
    for path,info in used.items():
        if snapshot(path)!=info.stamp:raise ValueError('估算期间原片变化，请刷新后重试')
    return results

def format_estimate(value):
    if not value:return '预计：待估算'
    divisor,unit=(1024,'KB') if value.get('high',value['bytes'])<1048576 else (1048576,'MB')
    if value.get('exact'):
        suffix='已有结果' if value.get('source')=='previous-export' else '可确定'
        return f"约 {value['bytes']/divisor:.1f} {unit}（{suffix}）"
    return f"预计 {value['low']/divisor:.1f}–{value['high']/divisor:.1f} {unit}（抽样）"
