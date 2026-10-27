"""Move a user-confirmed managed installation without losing rollback versions."""
import json,os,subprocess,time,uuid
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QLockFile

def move_program(source,target,startup,progress=lambda text:None,wait_pid=None):
    from installer import DATA,read_manifest,checked_version,stop_existing,register
    from deployment_state import capture_entries,restore_entries,wait_ready,stop_version,recover,atomic,verify_payload
    from storage_locations import copy_tree,destination,plain
    source=plain(source);target=destination(target,'program',source)
    recover(source,True);manifest=read_manifest(source)
    if not manifest.get('current'):raise ValueError('没有可迁移的已安装版本')
    previous=checked_version(source,manifest['current'])/'BailongEnhanced.exe'
    snapshot=capture_entries(source,True);old=None;new=None
    try:
        progress('正在关闭桌宠并迁移程序，回退版本一同保留…');old=stop_existing(source)
        last=[0.]
        def copied(done,total,phase):
            if time.monotonic()-last[0]>.15 or done==total:
                last[0]=time.monotonic();progress(f'迁移并校验程序 {done/1048576:.0f} / {total/1048576:.0f} MB')
        plan=copy_tree(source,target,'program',progress=copied)
        for name in manifest['versions']:
            folder=checked_version(target,name)
            if (folder/'payload-manifest.json').is_file():verify_payload(folder,name.split('-')[0])
        new=checked_version(target,manifest['current'])/'BailongEnhanced.exe'
        # Startup only accepts nonce receipts beside its own executable.
        # The installation root is two levels higher and is deliberately rejected.
        token=uuid.uuid4().hex;receipt=new.parent/('.ready-'+token+'.json')
        env=dict(os.environ,BAILONG_DEPLOY_TOKEN=token,BAILONG_DEPLOY_RECEIPT=str(receipt))
        progress('正在确认新位置的窗口与本地服务…')
        process=subprocess.Popen([str(new)],cwd=new.parent,env=env,creationflags=0x08000000)
        wait_ready(process,new,receipt,token,manifest['current'].split('-')[0]);receipt.unlink(missing_ok=True)
        register(new,new.parent/'白龙安装管理.exe',startup)
        plan['wait_pid']=wait_pid or os.getpid();plan['wait_created']=__import__('psutil').Process(plan['wait_pid']).create_time()
        atomic(target/'location-migration.json',plan)
        clean_env=os.environ.copy()
        for key in ('BAILONG_DEPLOY_TOKEN','BAILONG_DEPLOY_RECEIPT'):clean_env.pop(key,None)
        subprocess.Popen([str(new),'--cleanup-storage-migration',str(target/'location-migration.json')],cwd=new.parent,env=clean_env,creationflags=0x08000000)
        return new
    except Exception:
        if new:stop_version(new)
        restore_entries(source,snapshot,True)
        if old:subprocess.Popen([str(previous)],cwd=previous.parent,creationflags=0x08000000)
        raise

class ProgramMoveJob(QThread):
    done=Signal(str);failed=Signal(str);progress=Signal(str)
    def __init__(self,source,target,startup,parent=None):
        super().__init__(parent);self.source=source;self.target=target;self.startup=startup
    def run(self):
        from installer import DATA
        lock=QLockFile(str(DATA/'deployment.lock'))
        try:
            if not lock.tryLock(0):raise OSError('另一个安装或更新正在运行')
            self.done.emit(str(move_program(self.source,self.target,self.startup,self.progress.emit)))
        except Exception as exc:self.failed.emit(str(exc)[:300])
        finally:
            if lock.isLocked():lock.unlock()
