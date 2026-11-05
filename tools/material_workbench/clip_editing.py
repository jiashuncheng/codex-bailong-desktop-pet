"""Non-destructive, timestamp-based editing of opaque and alpha animations."""
from dataclasses import dataclass
from pathlib import Path
import bisect,math,os,tempfile
from PIL import Image
from media import frames,write_animation
import processed_profile

MAX_MS=60_000
MAX_FRAMES=3600
MAX_PIXELS=16_777_216

def check_cancel(cancel):
    if cancel():raise InterruptedError('已取消，原文件未改动')

def snapshot(path):
    stat=Path(path).stat();return stat.st_size,stat.st_mtime_ns

@dataclass(frozen=True)
class MediaInfo:
    path: str
    size: tuple
    durations: tuple
    alpha: bool
    stamp: tuple
    profile: dict|None=None

    @property
    def duration_ms(self):return sum(self.durations)
    @property
    def starts(self):
        result=[0]
        for duration in self.durations:result.append(result[-1]+duration)
        return result
    def index_at(self,milliseconds):
        return max(0,min(len(self.durations)-1,bisect.bisect_right(self.starts,milliseconds)-1))
    def preview_meta(self):
        return dict(size=list(self.size),frames=len(self.durations),duration=self.duration_ms/1000,
                    fps=len(self.durations)*1000/self.duration_ms)

@dataclass(frozen=True)
class Clip:
    path: str
    start_ms: int=0
    end_ms: int|None=None
    repeat: int=1

def probe(path,cancel=lambda:False):
    path=Path(path).resolve();before=snapshot(path);size=None;durations=[];alpha=False
    iterator=frames(path)
    try:
        total=0
        for image,ms in iterator:
            check_cancel(cancel)
            if image.width*image.height>MAX_PIXELS:raise ValueError('单帧超过1600万像素')
            if size is not None and image.size!=size:raise ValueError('原片画布在变化')
            size=image.size
            if not math.isfinite(ms) or int(ms)!=ms or ms<=0:raise ValueError('无效的帧时长')
            durations.append(int(ms));total+=int(ms)
            if len(durations)>MAX_FRAMES or total>MAX_MS:raise ValueError('单段素材最多60秒、3600帧')
            alpha=alpha or image.getchannel('A').getextrema()[0]<255
    finally:iterator.close()
    if not durations:raise ValueError('没有可读取的画面')
    if snapshot(path)!=before:raise ValueError('原片仍在写入，请等同步完成')
    return MediaInfo(str(path),size,tuple(durations),alpha,before,processed_profile.read(path))

def bounds(clip,info):
    values=(clip.start_ms,info.duration_ms if clip.end_ms is None else clip.end_ms,clip.repeat)
    if any(isinstance(v,bool) or not isinstance(v,int) for v in values):raise ValueError('剪辑时间需为整数毫秒，重复次数需为整数')
    start,end,repeat=values
    if not 0<=start<end<=info.duration_ms:raise ValueError('起点应早于终点，且都在原片范围内')
    if not 1<=repeat<=20:raise ValueError('每段重复次数为1至20次')
    return start,end,repeat

def composition(infos):
    infos=list(infos);kinds={info.alpha for info in infos}
    if len(kinds)>1:raise ValueError('透明素材与不透明原片请先统一抠图，再拼接，避免拼入一块背景')
    calibrated,profile=processed_profile.edit_layout(infos)
    canvas=calibrated or tuple(max(info.size[i] for info in infos) for i in (0,1))
    if canvas[0]*canvas[1]>MAX_PIXELS:raise ValueError('合并后的画布过大，请先统一画幅')
    if not next(iter(kinds)) and len({info.size for info in infos})>1:raise ValueError('不透明原片画幅不同，请先统一处理')
    return canvas,profile

def compose_frame(image,info,canvas,profile):
    offset=(round(profile['anchor'][0]-info.profile['anchor'][0]),round(profile['anchor'][1]-info.profile['anchor'][1])) if profile else ((canvas[0]-image.width)//2,canvas[1]-image.height)
    if image.size!=canvas or offset!=(0,0):
        padded=Image.new('RGBA',canvas);padded.paste(image,offset);return padded
    return image

def can_copy_lossless(clips,sources,canvas,profile):
    info=sources[str(Path(clips[0].path).resolve())]
    return (len(clips)==1 and Path(info.path).suffix.lower()=='.webp' and bounds(clips[0],info)==(0,info.duration_ms,1)
        and info.size==canvas and processed_profile.read(info.path)==profile)

def export(clips,target,infos=None,cancel=lambda:False,progress=lambda *a:None,encoding='lossless'):
    """Exact half-open intervals; pad bottom/centre, never stretch or resample."""
    clips=list(clips);target=Path(target).resolve()
    from encoding_presets import preset
    preset(encoding)
    if not clips:raise ValueError('请先添加片段')
    if target.suffix.lower()!='.webp':raise ValueError('请导出为保留透明度的动画 WebP')
    if target.exists():raise FileExistsError('目标文件已存在，请换一个名称；原文件不会覆盖')
    unique={str(Path(clip.path).resolve()) for clip in clips}
    if str(target) in unique:raise ValueError('不能覆盖原始素材')
    known=infos or {};sources={}
    for path in unique:
        check_cancel(cancel);info=known.get(path)
        if info is None:info=probe(path,cancel)
        if snapshot(path)!=info.stamp:raise ValueError('原片已变化，请重新添加片段')
        sources[path]=info
    kinds={v.alpha for v in sources.values()};canvas,profile=composition(sources.values())
    total=0;estimated_frames=0
    for clip in clips:
        info=sources[str(Path(clip.path).resolve())];start,end,repeat=bounds(clip,info)
        total+=(end-start)*repeat
        starts=info.starts
        estimated_frames+=sum(left<end and right>start for left,right in zip(starts,starts[1:]))*repeat
    if total>MAX_MS or estimated_frames>MAX_FRAMES:raise ValueError('合成动作最多60秒、3600帧；请缩短选段或减少重复')
    if estimated_frames<2:raise ValueError('请至少保留两个画面帧，才能作为桌宠动画')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.bailong-edit-',suffix='.tmp',dir=target.parent);os.close(fd)
    temporary=Path(name)
    single_info=sources[str(Path(clips[0].path).resolve())]
    direct_copy=encoding=='lossless' and can_copy_lossless(clips,sources,canvas,profile)
    def sequence():
        count=0
        for clip in clips:
            info=sources[str(Path(clip.path).resolve())];start,end,repeat=bounds(clip,info)
            for _ in range(repeat):
                iterator=frames(info.path);timestamp=0
                try:
                    for image,ms in iterator:
                        check_cancel(cancel)
                        right=timestamp+ms
                        overlap=min(right,end)-max(timestamp,start)
                        if overlap>0:
                            if image.size!=info.size:raise ValueError('原片画布变化，请重新读取')
                            image=compose_frame(image,info,canvas,profile)
                            count+=1;progress(count,estimated_frames)
                            yield image,int(overlap)
                        timestamp=right
                        if timestamp>=end:break
                finally:iterator.close()
        check_cancel(cancel)
    try:
        if direct_copy:
            check_cancel(cancel)
            with open(single_info.path,'rb') as source,open(temporary,'wb') as dest:
                while chunk:=source.read(1024*1024):check_cancel(cancel);dest.write(chunk)
            count=estimated_frames;duration=total;progress(count,count)
        else:
            iterator=sequence()
            try:count,duration=write_animation(temporary,iterator,xmp=processed_profile.encode(profile) if profile else None,encoding=encoding)
            finally:iterator.close()
        check_cancel(cancel)
        if count!=estimated_frames or duration!=total:raise ValueError('编码时序与选段不一致，未保存')
        # Decode the actual output before publishing it; WebP may coalesce equal frames.
        decoded_ms=0;decoded_count=0;durations=[]
        decoded=_decoded_webp(temporary)
        try:
            for image,ms in decoded:
                check_cancel(cancel)
                if image.size!=canvas:raise ValueError('导出画布校验失败')
                decoded_ms+=ms;decoded_count+=1;durations.append(ms)
        finally:decoded.close()
        if decoded_ms!=total or decoded_count<2:raise ValueError('导出时序异常或只剩静止画面，请扩大选段')
        for info in sources.values():
            if snapshot(info.path)!=info.stamp:raise ValueError('导出期间原片变化，未保存')
        check_cancel(cancel)
        publish(temporary,target,cancel)
        return dict(path=str(target),size=list(canvas),durationMs=total,frames=decoded_count,
                    alpha=next(iter(kinds)),segments=len(clips),durations=durations,encoding=encoding,bytes=target.stat().st_size)
    finally:temporary.unlink(missing_ok=True)

def _decoded_webp(path):
    with Image.open(path) as image:
        for index in range(getattr(image,'n_frames',1)):
            image.seek(index);image.load()
            yield image,int(image.info.get('duration',0))

def publish(source,target,cancel=lambda:False):
    """Exclusive creation protects source files, including a racing filename collision."""
    target=Path(target);owned=False
    try:
        with open(source,'rb') as src,open(target,'xb') as out:
            owned=True
            while chunk:=src.read(1024*1024):
                check_cancel(cancel);out.write(chunk)
            out.flush();os.fsync(out.fileno())
        check_cancel(cancel)
    except BaseException:
        if owned:target.unlink(missing_ok=True)
        raise

def publish_batch(jobs,cancel=lambda:False):
    jobs=[(Path(source),Path(target)) for source,target in jobs]
    targets=[str(target.resolve()) for _,target in jobs]
    if len(set(targets))!=len(targets):raise ValueError('批量输出名称重复')
    if any(target.exists() for _,target in jobs):raise FileExistsError('有同名文件，请换一组名称；未覆盖已有文件')
    created=[]
    try:
        for source,target in jobs:
            check_cancel(cancel);publish(source,target,cancel);created.append((target,snapshot(target)))
        return [str(target.resolve()) for _,target in jobs]
    except BaseException:
        for target,stamp in created:
            if target.exists() and snapshot(target)==stamp:target.unlink()
        raise
