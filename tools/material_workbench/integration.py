"""Cross-platform desktop IPC and transactional custom-character activation."""
from pathlib import Path
import copy,hashlib,json,os,shutil,subprocess,sys,time,uuid
from contextlib import contextmanager
from media import atomic_json,digest,HIDDEN

def log(message,**extra):
    print(json.dumps(dict(message=message,**extra),ensure_ascii=False),flush=True)


def read_json(path,default=None):
    p=Path(path)
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else copy.deepcopy(default)


@contextmanager
def lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    f=open(path,'a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
    if os.name=='nt':
        import msvcrt
        acquire=lambda:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        release=lambda:msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        acquire=lambda:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=lambda:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
    try:
        try:acquire()
        except OSError:raise RuntimeError('已有更新任务在运行，请等待；不要重复点击')
        yield
    finally:
        f.seek(0)
        try:release()
        except OSError:pass
        f.close()


def snapshot(path):
    s=Path(path).stat();return s.st_size,s.st_mtime_ns


def stable_hash(path,settle=3):
    before=snapshot(path)
    if before[0]==0 or time.time_ns()-before[1]<settle*1e9:raise ValueError('文件仍在写入/同步，留待下次处理')
    sha=digest(path)
    if snapshot(path)!=before:raise ValueError('文件在校验期间发生变化')
    return sha,before


def valid_release(path):
    try:
        hashes=read_json(Path(path)/'文件校验.json')
        return isinstance(hashes,dict) and bool(hashes) and all((Path(path)/n).is_file() and digest(Path(path)/n)==s for n,s in hashes.items())
    except (OSError,ValueError):return False


def pipe_command(config,command):
    # Use the app's own QLocalSocket protocol through a separate short-lived process.
    code="from PySide6.QtCore import QCoreApplication;from PySide6.QtNetwork import QLocalSocket;import sys;sys.path.insert(0,sys.argv[2]);from platform_support import server_name;app=QCoreApplication([]);s=QLocalSocket();s.connectToServer(server_name());ok=s.waitForConnected(1500);\nif ok:\n s.write(sys.argv[1].encode());s.flush();s.waitForBytesWritten(1500);s.disconnectFromServer()\nsys.exit(0 if ok else 3)"
    return subprocess.run([config['python'],'-c',code,command,str(Path(config['app_root'])/'app')],capture_output=True,timeout=8,creationflags=HIDDEN,env=dict(os.environ,BAILONG_DATA_DIR=config['data_dir'])).returncode==0


def app_running(config):
    # App-defined ping is silent and releases its connection correctly.
    return pipe_command(config,'ping')


def stop_app(config):
    if not app_running(config):return
    if not pipe_command(config,'quit'):raise RuntimeError('桌宠退出请求失败，未改动当前素材')
    end=time.monotonic()+25
    while time.monotonic()<end:
        if not app_running(config):return
        time.sleep(.4)
    raise RuntimeError('桌宠未正常退出，未替换当前素材')


def start_app(config):
    root=Path(config['app_root']);exe=Path(config['python']).with_name('pythonw.exe') if os.name=='nt' else Path(config['python'])
    subprocess.Popen([str(exe if exe.exists() else config['python']),str(root/'run_source.py')],
        cwd=str(root),creationflags=HIDDEN,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=dict(os.environ,BAILONG_DATA_DIR=config['data_dir']))


def wait_active(config,manifest,since):
    runtime=Path(config['data_dir'])/'runtime.json';end=time.monotonic()+70;last={}
    while time.monotonic()<end:
        try:
            if runtime.stat().st_mtime>=since:
                last=read_json(runtime,{})
                # Actual keys are checked in the live app, not inferred from a process lookup.
                settings=read_json(Path(config['data_dir'])/'settings.json',{})
                from desktop_services import all_items
                if (settings.get('character')==config['character_key'] and
                    last.get('quality_revision')==manifest['qualityRevision'] and
                    last.get('asset_count')==len(all_items(manifest)) and
                    not last.get('decode_error')):
                    return dict(character=settings['character'],**{k:last.get(k) for k in ('pid','quality_revision','asset_count','decode_error','position','scale')})
        except (OSError,ValueError):pass
        time.sleep(.7)
    raise RuntimeError('重启后未收到正确素材数量的运行记录：'+json.dumps({k:last.get(k) for k in ('character','asset_count','decode_error')},ensure_ascii=False))


def preserve_foot(config,current,target,manifest,runtime,old_manifest=None):
    """Change only placement when canvas size changes, keeping the visible feet fixed."""
    old=old_manifest or read_json(target/'素材清单.json',{})
    before=old.get('canvasLayout');after=manifest['canvasLayout']
    if not before or not runtime.get('character_logical_size'):return current
    scale=float(current.get('scale',1));ow,oh=runtime['character_logical_size'];x,y=runtime['position']
    nw=round(after['canvas'][0]*after['displayHeight']*scale/after['referenceHeight'])
    nh=round(after['canvas'][1]*after['displayHeight']*scale/after['referenceHeight'])
    code="import json;from PySide6.QtWidgets import QApplication;a=QApplication([]);print(json.dumps([dict(name=s.name(),rect=[s.availableGeometry().x(),s.availableGeometry().y(),s.availableGeometry().width(),s.availableGeometry().height()]) for s in a.screens()]))"
    p=subprocess.run([config['python'],'-c',code],capture_output=True,text=True,encoding='utf-8',timeout=12,creationflags=HIDDEN)
    if p.returncode:raise RuntimeError('无法查询屏幕坐标，未替换素材')
    screens=json.loads(p.stdout);saved=current.get('screen_position',{})
    screen=next((s for s in screens if s['name']==saved.get('screen')),screens[0])
    sx,sy,sw,sh=screen['rect']
    # The graceful exit saved the latest position; runtime.json can lag a recent drag.
    if saved:
        x=round(sx+max(0,sw-ow)*max(0,min(1,float(saved.get('rx',.85)))))
        y=round(sy+max(0,sh-oh)*max(0,min(1,float(saved.get('ry',.85)))))
    foot=[x+before['anchor'][0]/before['canvas'][0]*ow,y+before['anchor'][1]/before['canvas'][1]*oh]
    left=round(foot[0]-after['anchor'][0]/after['canvas'][0]*nw)
    top=round(foot[1]-after['anchor'][1]/after['canvas'][1]*nh)
    left=max(sx,min(left,sx+sw-nw));top=max(sy,min(top,sy+sh-nh))
    current['screen_position']=dict(screen=screen['name'],rx=(left-sx)/max(1,sw-nw),ry=(top-sy)/max(1,sh-nh))
    current['position']=[left,top]
    return current


def deploy(config,release,manifest,state):
    data=Path(config['data_dir']);target=data/'characters'/config['character_key']
    if target.parent.resolve()!= (data/'characters').resolve():raise ValueError('角色目录无效')
    target.parent.mkdir(parents=True,exist_ok=True)
    def linked_copy(src,dst):
        try:os.link(src,dst)
        except OSError:shutil.copy2(src,dst)
        return dst
    stage=target.parent/('import-oneclick-'+uuid.uuid4().hex);shutil.copytree(release,stage,copy_function=linked_copy)
    if not valid_release(stage):raise ValueError('暂存素材校验失败')
    backup=Path(config['state_dir'])/'backups'/time.strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True,exist_ok=False)
    settings=data/'settings.json';old_existed=target.exists();installed=False;stopped=False
    transaction=Path(config['state_dir'])/'pending-transaction.json'
    atomic_json(transaction,dict(target=str(target),backup=str(backup),stage=str(stage),release=str(release)))
    try:
        log('素材校验通过，正在让桌宠保存设置并退出')
        stop_app(config);stopped=True
        if settings.exists():shutil.copy2(settings,backup/'settings.json')
        # Preserve screen identity and the visual foot, even if transparent canvas grows.
        current=read_json(settings,{})
        previous_key=current.get('character','builtin')
        if previous_key not in config.get('allowed_characters',[config['character_key']]):
            raise RuntimeError('当前不是白龙角色，请先切换到白龙再更新')
        prefs=current.setdefault('character_preferences',{})
        prefs[previous_key]={k:copy.deepcopy(current[k]) for k in ('scale','playback_speed','talk_lines') if k in current}
        current.update(prefs.get(config['character_key'],{}))
        current=preserve_foot(config,current,target,manifest,read_json(data/'runtime.json',{}),
                              config.get('builtin_layout_manifest') if previous_key=='builtin' else None)
        current['character']=config['character_key']
        prefs[config['character_key']]={k:copy.deepcopy(current[k]) for k in ('scale','playback_speed','talk_lines') if k in current}
        if old_existed:os.replace(target,backup/'character')
        os.replace(stage,target);installed=True
        # The app owns all other settings. Only this role's existing preference remains in use.
        atomic_json(settings,current)
        started=time.time();start_app(config);live=wait_active(config,manifest,started)
        if not valid_release(target):raise RuntimeError('安装后的文件校验失败')
        atomic_json(backup/'transaction-result.json',dict(success=True,live=live))
        transaction.unlink();log('桌宠已重新加载白龙及新增素材',**live)
        return live
    except Exception as error:
        log('更新失败，恢复上一套有效素材',error=str(error))
        if installed:
            stop_app(config)
            os.replace(target,backup/'failed-character')
        if (backup/'character').exists():os.replace(backup/'character',target)
        if (backup/'settings.json').exists():shutil.copy2(backup/'settings.json',settings)
        if stopped:start_app(config)
        atomic_json(backup/'transaction-result.json',dict(success=False,error=str(error)))
        if transaction.exists():transaction.unlink()
        raise


def recover(config):
    transaction=Path(config['state_dir'])/'pending-transaction.json'
    if not transaction.exists():return
    tx=read_json(transaction);data=Path(config['data_dir']).resolve();target=data/'characters'/config['character_key']
    backup=Path(tx['backup']).resolve()
    if (str(target)!=tx['target'] or not backup.is_relative_to((Path(config['state_dir'])/'backups').resolve())):
        raise RuntimeError('未完成事务路径无效，请检查 pending-transaction.json')
    log('发现上次中断的更新，先恢复旧素材')
    stop_app(config)
    if (backup/'character').exists():
        if target.exists():os.replace(target,backup/('interrupted-'+uuid.uuid4().hex))
        os.replace(backup/'character',target)
    if (backup/'settings.json').exists():shutil.copy2(backup/'settings.json',data/'settings.json')
    transaction.unlink();start_app(config)
