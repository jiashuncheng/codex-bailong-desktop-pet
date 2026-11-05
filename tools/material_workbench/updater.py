"""White-dragon add-on updater: preserve all built-in clips and add new actions."""
from pathlib import Path
import argparse,copy,hashlib,json,math,os,re,shutil,sys,time,uuid
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from media import frames,digest,atomic_json,GreenMatte,write_animation,placed,foot_anchor
from cartoon import CartoonFace,calibrate,body_anchor
from webp_padding import pad_webp
from config_store import load_config,pillow_font
from alignment import adjusted_record,manual_values
import integration as appio

BASE=Path(__file__).resolve().parent
REVISION='bailong-cartoon-v2-eyes'
MANIFEST_REVISION=3
EXTENSIONS={'.webm','.webp','.mp4','.mov','.mkv'}
log=appio.log;read_json=appio.read_json

def link_copy(source,dest):
    dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,dest)
    except OSError:shutil.copy2(source,dest)

def scan(config):
    root=Path(config['input_dir']).resolve();out=Path(config['output_dir']).resolve()
    if not root.is_dir():raise ValueError('输入目录不存在')
    exported=root/'导出结果'
    if config.get('prefer_export_subdir',True) and exported.is_dir() and any(p.suffix.lower() in EXTENSIONS for p in exported.rglob('*') if p.is_file()):
        root=exported
    result={}
    for path in sorted(root.rglob('*') if config.get('recursive') else root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS or path.resolve().is_relative_to(out):continue
        stem=re.sub(r'[_ -]*(透明|有损|无损|预览|母版|\d+x\d+|\d+fps).*','',path.stem)
        stem=re.sub(r'^\d+[ _-]*','',stem) or path.stem
        action='custom_'+hashlib.sha256(stem.encode()).hexdigest()[:12]
        previous=result.get(action)
        rank=lambda p:(p.suffix.lower() in ('.webm','.webp'),'无损' in p.stem or '母版' in p.stem,'透明' in p.stem,p.stat().st_mtime_ns)
        if previous is None or rank(path)>rank(previous):result[action]=path
    return result

def decode_check(path,matcher=None,allow_source_edge=True):
    union=None;count=0;duration=0;first=None;samples=[];touch=[];durations=[]
    for index,(im,ms) in enumerate(frames(path)):
        if im.width*im.height>16777216:raise ValueError('素材分辨率超过1600万像素')
        alpha=im.getchannel('A');extrema=alpha.getextrema();box=alpha.getbbox()
        if not box or extrema[0]!=0 or extrema[1]<240:raise ValueError(f'第{index+1}帧没有有效透明背景/主体')
        if first is None:first=im.copy();size=im.size
        if im.size!=size:raise ValueError('动画画布不一致')
        union=list(box) if union is None else [min(union[0],box[0]),min(union[1],box[1]),max(union[2],box[2]),max(union[3],box[3])]
        if box[0]==0 or box[1]==0 or box[2]==im.width or box[3]==im.height:touch.append(index)
        if matcher and index in (0,6,12,18,24):
            sample=matcher.match(im)
            if sample:samples.append(dict(frame=index,**sample))
        count+=1;duration+=ms;durations.append(ms)
        if count>3600 or duration>60000:raise ValueError('单段动画超过60秒或3600帧')
    if count<2:raise ValueError('需要至少两帧的动画')
    if touch and not allow_source_edge:raise ValueError('新输出出现额外裁切，拒绝安装')
    return dict(size=list(size),frames=count,durationMs=duration,durations=durations,union=union,
                sourceEdgeTouchFrames=len(touch),faceSamples=samples),first

def prepare(path,config,matcher):
    sha,before=appio.stable_hash(path,config.get('settle_seconds',3))
    override=config.get('overrides',{}).get(path.name,{})
    key=hashlib.sha256(json.dumps(dict(source=sha,revision=REVISION,override=override,
        multiplier=config.get('extra_scale',1),reference=digest(BASE/'白龙标准参考.png')),sort_keys=True).encode()).hexdigest()
    cache=Path(config['state_dir'])/'sources'/key;receipt=cache/'record.json'
    old=read_json(receipt,{})
    if old and Path(old.get('cache','')).is_file() and digest(old['cache'])==old.get('cacheSha256'):
        old.update(source=str(path),name=config.get('action_names',{}).get(path.name,path.stem))
        log('复用已处理白龙素材',file=path.name);return adjusted_record(old,config.get('adjustments',{}).get(path.name))
    cache.mkdir(parents=True,exist_ok=True)
    gen=frames(path)
    try:first,_=next(gen)
    finally:gen.close()
    transparent=first.getchannel('A').getextrema()[0]<255
    native=cache/('native'+(path.suffix.lower() if transparent else '.webp'))
    if transparent:
        log('保留原透明度，不重复抠图',file=path.name);shutil.copy2(path,native)
    else:
        log('原分辨率绿幕处理',file=path.name);engine=GreenMatte(BASE,config['runtime'])
        source_stats=[0,0]
        def converted():
            for index,(im,ms) in enumerate(frames(path)):
                if im.width*im.height>16777216 or index>=3600 or source_stats[1]+ms>60000:raise ValueError('素材尺寸或时长超过上限')
                source_stats[0]+=1;source_stats[1]+=ms
                if index%48==0:log('抠图进度',file=path.name,frame=index+1)
                yield engine.apply(im),ms
        write_animation(native,converted())
    info,first=decode_check(native,matcher,allow_source_edge=True)
    if not transparent and (info['frames']!=source_stats[0] or info['durationMs']!=source_stats[1]):raise ValueError('抠图后帧数/时序变化')
    if appio.snapshot(path)!=before or digest(path)!=sha:raise ValueError('文件仍在变化，留待下次处理')
    scale,matches=calibrate(info['faceSamples'],override)
    scale*=float(config.get('extra_scale',1))
    if not math.isfinite(scale) or not .2<=scale<=5:raise ValueError('人物缩放超出范围')
    if override.get('anchor'):anchor=override['anchor']
    elif matches:
        first_match=next((v for v in matches if v.get('frame')==0),None)
        if first_match is None:
            first_match=matches[0]
            for idx,(img,_) in enumerate(frames(native)):
                if idx==first_match['frame']:first=img;break
        anchor=body_anchor(first,first_match)
    else:anchor=foot_anchor(first)
    if len(anchor)!=2 or not all(math.isfinite(float(v)) for v in anchor):raise ValueError('落脚锚点无效')
    record=dict(source=str(path),sourceSha256=sha,cache=str(native),cacheSha256=digest(native),info=info,
        transform=dict(scale=scale,anchor=list(map(float,anchor)),sourceSize=info['size']),name=config.get('action_names',{}).get(path.name,path.stem),
        calibration=dict(method='白龙双眼与脸部模板匹配',matches=matches,manual=bool(override.get('scale'))))
    atomic_json(receipt,record);return adjusted_record(record,config.get('adjustments',{}).get(path.name))

def geometry(actions):
    # Original 720 canvas stays centered; only transparent padding changes.
    extent=360
    for a in actions.values():
        t=a['transform'];s=t['scale'];x,y=t['anchor'];l,top,r,b=a['info']['union']
        dx,dy=t.get('offset',[0,0]);relative=[(l-x)*s+dx,(top-y)*s+dy,(r-x)*s+dx,(b-y)*s+dy]
        extent=max(extent,-relative[0]+24,relative[2]+24,-relative[1]-308+24,relative[3]+308+24)
    side=max(800,math.ceil(extent*2/8)*8)
    if side>2048:raise ValueError('动作跨度过大，画布超过当前播放器2048上限，请检查校准')
    pad=(side-720)//2
    return side,pad,[side/2,668+pad]

def shift_render_metadata(manifest,side,pad):
    def visit(value):
        if isinstance(value,dict):
            if 'file' in value and 'id' in value:
                scale=float(value.get('renderScale',1));x,y=value.get('renderOffset',[0,0])
                value['renderOffset']=[float(x)*720/side,(float(y)*720+pad*(scale-1))/side]
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(manifest)

def build_runtime(config,base_root,base,actions):
    sys.path.insert(0,str(Path(config['app_root'])/'app'))
    from desktop_services import all_items,validate_character
    from sustained_assets import seam_items
    side,pad,anchor=geometry(actions);state=Path(config['state_dir'])
    fingerprint=hashlib.sha256(json.dumps(dict(base=digest(base_root/'素材清单.json'),canvas=side,
        revision=REVISION,manifestRevision=MANIFEST_REVISION,actions={k:[v['cacheSha256'],v['transform'],v['name']] for k,v in actions.items()}),sort_keys=True).encode()).hexdigest()
    release=state/'releases'/fingerprint
    if appio.valid_release(release):
        log('播放库已是本次版本，无需重新生成');return release,read_json(release/'素材清单.json'),False
    stage=state/'releases'/('staging-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    manifest=copy.deepcopy(base);manifest['character']='白龙娘 · 自定义新增动作'
    manifest['clickAnimations']=copy.deepcopy(base.get('clickAnimations') or base.get('variants',[]))
    manifest['version']='1.0.0';manifest['qualityRevision']=time.time_ns();manifest['decodeResolution']=side
    manifest['playbackCanvas']=[side,side]
    # Conservative old-canvas bounds plus full-action custom unions.
    bounds=[pad,pad,pad+720,pad+720]
    shift_render_metadata(manifest,side,pad)
    paths=sorted(set((i.get('playbackFile') or i['file']) for i in all_items(base)+seam_items(base)))
    pool=state/'base-cache';pool.mkdir(parents=True,exist_ok=True)
    for number,name in enumerate(paths):
        source=base_root/name;source_sha=digest(source)
        cached=pool/(source_sha+f'-{side}.webp');stamp=cached.with_suffix('.json')
        saved=read_json(stamp,{})
        if not cached.is_file() or saved.get('sha256')!=digest(cached):
            log('保留原白龙帧，仅增加透明留白',asset=number+1,total=len(paths),file=name)
            result=pad_webp(source,cached,side,pad)
            atomic_json(stamp,dict(sourceSha256=source_sha,sha256=digest(cached),**result))
        link_copy(cached,stage/name)
    union_original=Image.open(base_root/(base['idle'].get('playbackFile') or base['idle']['file'])).convert('RGBA').getchannel('A').point(lambda a:255 if a>=24 else 0).getbbox()
    preview=Image.new('RGB',(600,350*max(1,math.ceil(len(actions)/2))),(240,240,240));draw=ImageDraw.Draw(preview)
    font=pillow_font(14)
    for index,(action,record) in enumerate(sorted(actions.items())):
        playback_key=hashlib.sha256(json.dumps(dict(source=record['cacheSha256'],transform=record['transform'],canvas=side),sort_keys=True).encode()).hexdigest()
        cached=state/'playback-cache'/(playback_key+'.webp');cached.parent.mkdir(parents=True,exist_ok=True)
        metadata=cached.with_suffix('.json');old=read_json(metadata,{})
        if not cached.exists() or old.get('sha256')!=digest(cached):
            log('生成新增白龙播放素材',file=record['name'],canvas=side)
            def converted():
                for frame_index,(im,ms) in enumerate(frames(record['cache'])):
                    if frame_index%48==0:log('新增素材编码进度',action=action,frame=frame_index+1,total=record['info']['frames'])
                    yield placed(im,record['transform'],side,anchor),ms
            tmp=cached.with_name(cached.stem+'-tmp.webp');count,duration=write_animation(tmp,converted())
            info,first=decode_check(tmp,allow_source_edge=False)
            if (count,duration)!=(record['info']['frames'],record['info']['durationMs']):raise ValueError('输出帧数/时序变化')
            if (info['frames'],info['durationMs'])!=(count,duration):raise ValueError('逐帧回读检查失败')
            os.replace(tmp,cached);old=dict(sha256=digest(cached),info=info);atomic_json(metadata,old)
        else:info=old['info'];first=next(frames(cached))[0]
        name='custom/'+action+'.webp';link_copy(cached,stage/name)
        item=dict(id=action,name=record['name'],file=name,durationMs=info['durationMs'],automatic=True,
            renderScale=1.,renderOffset=[0,0],sourceFrames=record['info']['frames'],decodedFrames=info['frames'],
            sourceSha256=record['sourceSha256'],playbackSha256=old['sha256'],manualAdjustment=record.get('manualAdjustment'))
        manifest.setdefault('variants',[]).append(item)
        manifest.setdefault('clickAnimations',[]).append(copy.deepcopy(item))
        b=info['union'];bounds=[min(bounds[0],b[0]),min(bounds[1],b[1]),max(bounds[2],b[2]),max(bounds[3],b[3])]
        a=np.asarray(first).copy();a[a[:,:,3]==0,:3]=0;first=Image.fromarray(a)
        first.save(stage/(action+'_首帧.png'))
        x=index%2*300;y=index//2*350;draw.text((x+5,y+5),record['name'][:25],font=font,fill='black')
        for dx,color in [(0,(248,248,248)),(150,(30,34,42))]:
            t=first.copy();t.thumbnail((148,310));bg=Image.new('RGB',(150,320),color);bg.paste(t,((150-t.width)//2,(320-t.height)//2),t);preview.paste(bg,(x+dx,y+25))
    panel=[max(0,union_original[0]+pad-8),max(0,union_original[1]+pad-8),min(side,union_original[2]+pad+8),min(side,union_original[3]+pad+8)]
    manifest['canvasLayout']=dict(schema=1,canvas=[side,side],anchor=anchor,referenceHeight=607,
        displayHeight=607*256/720,alphaUnion=bounds,panelBounds=panel)
    preview.save(stage/'新增动作深浅底预览.jpg',quality=94)
    atomic_json(stage/'素材清单.json',manifest)
    atomic_json(stage/'新增处理记录.json',dict(revision=REVISION,base_root=str(base_root),base_manifest_sha256=digest(base_root/'素材清单.json'),base_actions=len(all_items(base)),
        custom_actions=actions,canvas=side,base_method='WebP container padding; compressed frame pixels and frame timing unchanged'))
    log('校验完整白龙动作库',original=len(all_items(base)),new=len(actions))
    actual=validate_character(stage)
    if len(all_items(actual))!=len(all_items(base))+len(actions):raise ValueError('合并动作数量不匹配')
    atomic_json(stage/'文件校验.json',{p.relative_to(stage).as_posix():digest(p) for p in stage.rglob('*') if p.is_file()})
    if release.exists():release=release.with_name(fingerprint+'-'+str(time.time_ns()))
    stage.rename(release);return release,manifest,True

def publish_small(config,release,actions,report):
    output=Path(config['output_dir']);output.mkdir(parents=True,exist_ok=True)
    manifest=read_json(release/'素材清单.json');items={i['id']:i for i in manifest['variants']}
    for action,record in actions.items():
        source=release/items[action]['file'];target=output/(action+'.webp')
        if not target.exists() or digest(source)!=digest(target):shutil.copy2(source,target)
        png=release/(action+'_首帧.png')
        if png.exists():shutil.copy2(png,output/png.name)
    cols=min(2,max(1,len(actions)));preview=Image.new('RGB',(720*cols,470*max(1,math.ceil(len(actions)/cols))),(238,240,243))
    draw=ImageDraw.Draw(preview);font=pillow_font(18)
    for index,(action,record) in enumerate(sorted(actions.items())):
        with Image.open(release/(action+'_首帧.png')) as im:first=im.convert('RGBA')
        x=index%cols*720;y=index//cols*470;draw.text((x+8,y+8),record['name'][:38],font=font,fill='black')
        for dx,color in [(0,(248,248,248)),(360,(30,34,42))]:
            thumb=first.copy();thumb.thumbnail((356,420),Image.Resampling.LANCZOS)
            panel=Image.new('RGB',(360,430),color);panel.paste(thumb,((360-thumb.width)//2,(430-thumb.height)//2),thumb)
            preview.paste(panel,(x+dx,y+36))
    preview.save(output/'新增动作深浅底预览.jpg',quality=95)
    atomic_json(output/'新增素材清单.json',[items[k] for k in sorted(actions)])
    atomic_json(output/'处理记录.json',report)
    atomic_json(output/'文件校验.json',{p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='文件校验.json'})

def run(config,prepare_only=False,selected_files=None,activate_only=False):
    state=Path(config['state_dir']);state.mkdir(parents=True,exist_ok=True)
    with appio.lock(state/'update.lock'):
        if not prepare_only:appio.recover(config)
        sys.path.insert(0,str(Path(config['app_root'])/'app'))
        from material_store import MaterialStore
        from desktop_services import all_items
        store=MaterialStore(Path(config['app_root']),Path(config['data_dir']))
        if not store.current:raise ValueError('当前白龙基础素材不可用')
        store.verify(store.root,store.current)
        base_root=store.root;base=read_json(base_root/'素材清单.json')
        config['allowed_characters']=['builtin',config['character_key']]
        config['builtin_layout_manifest']=dict(canvasLayout=dict(canvas=[720,720],anchor=[360,668]))
        saved=read_json(state/'state.json',dict(actions={}));actions=saved.get('actions',{})
        matcher=CartoonFace(BASE/'白龙标准参考.png');failures=[]
        sources={} if activate_only else scan(config)
        if selected_files is not None:
            selected={str(Path(p).resolve()) for p in selected_files}
            sources={k:p for k,p in sources.items() if str(p.resolve()) in selected}
            if not sources and not activate_only:raise ValueError('选中的素材已移动或不在当前目录中，请刷新后重试')
        if activate_only:sources={}
        for action,path in sources.items():
            try:
                record=prepare(path,config,matcher)
                duplicate=next((k for k,v in actions.items() if k!=action and v['sourceSha256']==record['sourceSha256']),None)
                if duplicate:
                    if Path(actions[duplicate]['source']).is_file():
                        log('内容重复，沿用已有动作',file=path.name);continue
                    del actions[duplicate]
                actions[action]=record
            except Exception as error:
                failures.append(dict(file=str(path),error=str(error)));log('本条未更新，保留旧动作',file=path.name,error=str(error))
        if not actions:raise ValueError('没有可用的新增动作；当前白龙保持不变')
        if not prepare_only:
            for record in actions.values():
                requested=config.get('adjustments',{}).get(Path(record['source']).name)
                if manual_values(requested)!=manual_values(record.get('manualAdjustment')):
                    raise ValueError('有手动调整尚未重新生成，请先处理这些动作，再加入桌宠')
        if activate_only:
            release=Path(saved.get('release',''))
            if not appio.valid_release(release):raise ValueError('还没有完整的处理结果，请先处理素材并预览')
            info=read_json(release/'新增处理记录.json',{})
            if Path(info.get('base_root','')).resolve()!=base_root.resolve():raise ValueError('白龙基础素材已更换，请先重新处理以合并新版素材')
            if info.get('base_manifest_sha256') and info['base_manifest_sha256']!=digest(base_root/'素材清单.json'):raise ValueError('白龙基础素材已更新，请先重新处理以合并新版素材')
            manifest=read_json(release/'素材清单.json');encoded=False
        else:release,manifest,encoded=build_runtime(config,base_root,base,actions)
        atomic_json(state/'state.json',dict(actions=actions,failures=failures,release=str(release)))
        target=Path(config['data_dir'])/'characters'/config['character_key']
        settings=read_json(Path(config['data_dir'])/'settings.json',{})
        already=(settings.get('character')==config['character_key'] and appio.valid_release(target) and
                 read_json(target/'素材清单.json')==manifest)
        live=None
        if not prepare_only and not already:live=appio.deploy(config,release,manifest,{})
        elif not prepare_only:log('当前白龙已是这一版，无需重启')
        report=dict(success=True,prepared_only=prepare_only,source_candidates=len(scan(config)) if Path(config['input_dir']).is_dir() else 0,available_actions=len(all_items(manifest)),
            base_actions=len(all_items(base)),custom_actions=len(actions),failed=failures,encoded=encoded,
            restarted=not prepare_only and not already,live=live,output=config['output_dir'],release=str(release),
            warnings=[dict(file=v['source'],source_edge_frames=v['info']['sourceEdgeTouchFrames']) for v in actions.values() if v['info'].get('sourceEdgeTouchFrames')])
        publish_small(config,release,actions,report)
        atomic_json(BASE/'最近结果.json',report);atomic_json(state/'最近结果.json',report)
        log('更新完成',**report);return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(BASE/'配置.json'))
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--input');parser.add_argument('--scale',type=float)
    parser.add_argument('--retry-failed',action='store_true');parser.add_argument('--selection-file')
    parser.add_argument('--activate-only',action='store_true');args=parser.parse_args();config=load_config(args.config)
    if args.input:config['input_dir']=args.input
    if args.scale is not None:config['extra_scale']=args.scale
    if not .5<=float(config.get('extra_scale',1))<=1.5:raise ValueError('新增人物倍率应在0.5到1.5之间')
    selected=read_json(args.selection_file) if args.selection_file else None
    if selected is not None and (not isinstance(selected,list) or any(not isinstance(p,str) for p in selected)):raise ValueError('素材选择清单无效')
    try:result=run(config,args.prepare_only,selected_files=selected,activate_only=args.activate_only);return 2 if result['failed'] else 0
    except Exception as error:
        import traceback;log('更新未完成',error=str(error));traceback.print_exc();return 1

if __name__=='__main__':sys.exit(main())
