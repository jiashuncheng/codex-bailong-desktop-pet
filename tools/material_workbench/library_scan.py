"""Read-only, background inventory for the material workbench."""
from pathlib import Path
import json,hashlib
from PySide6.QtCore import QThread,Signal
from alignment import manual_values

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default

def file_hash(path,cancel=lambda:False):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for data in iter(lambda:f.read(2*1024*1024),b''):
            if cancel():raise InterruptedError()
            h.update(data)
    return h.hexdigest()

class ScanWorker(QThread):
    result=Signal(list,dict);failed=Signal(str)
    def __init__(self,config,parent=None):super().__init__(parent);self.config=dict(config)
    def run(self):
        try:
            import updater
            config=self.config;state=read_json(Path(config['state_dir'])/'state.json',{}) or {}
            records=state.get('actions',{});settings=read_json(Path(config['data_dir'])/'settings.json',{}) or {}
            target=Path(config['data_dir'])/'characters'/config['character_key']
            active=read_json(target/'素材清单.json',{}) or {}
            active_items={v.get('sourceSha256'):v for v in active.get('variants',[]) if v.get('sourceSha256')} if settings.get('character')==config['character_key'] else {}
            errors={str(Path(v['file']).resolve()):v.get('error','处理失败') for v in state.get('failures',[]) if v.get('file')}
            rows=[]
            for action,path in updater.scan(config).items():
                if self.isInterruptionRequested():return
                stat=path.stat();sha=file_hash(path,self.isInterruptionRequested);record=records.get(action)
                processed_action=action
                if not record:
                    match_key=next((k for k,v in records.items() if v.get('sourceSha256')==sha),None)
                    if match_key:processed_action=match_key;record=records[match_key]
                match=bool(record and record.get('sourceSha256')==sha)
                processed=Path(config['output_dir'])/(processed_action+'.webp')
                manual=manual_values(config.get('adjustments',{}).get(path.name));stored=manual_values((record or {}).get('manualAdjustment'))
                current=match and manual==stored
                joined=sha in active_items and stored==manual_values(active_items[sha].get('manualAdjustment'))
                status='已加入' if current and joined else '已处理' if current else '待重生成' if match else '有更新' if record else '待处理'
                error=errors.get(str(path.resolve()),'')
                if error and not match:status='失败'
                info=record.get('info',{}) if match else {}
                rows.append(dict(action=action,path=str(path),name=config.get('action_names',{}).get(path.name,path.stem),
                    file=path.name,bytes=stat.st_size,sha256=sha,status=status,error=error,
                    processed=str(processed) if processed.is_file() else '',processed_current=current,
                    record=record if match else None,processed_action=processed_action,all_records=records,
                    meta=dict(frames=info.get('frames'),duration=info.get('durationMs',0)/1000,
                              fps=info.get('frames',0)/max(info.get('durationMs',1)/1000,.001),size=info.get('size')) if info else {}))
            release=Path(state.get('release','__missing__'));prepared=read_json(release/'素材清单.json',{}) or {}
            ready=bool(prepared.get('idle') and (release/'文件校验.json').is_file())
            pending=ready and (settings.get('character')!=config['character_key'] or prepared.get('qualityRevision')!=active.get('qualityRevision'))
            if not self.isInterruptionRequested():self.result.emit(rows,dict(ready=ready,pending=pending,active_actions=len(active.get('variants',[]))+1,
                custom_count=len(records),base_actions=35,release=str(release),layout=prepared.get('canvasLayout') or active.get('canvasLayout'),
                unprepared_adjustments=sum(r['status']=='待重生成' for r in rows)))
        except InterruptedError:return
        except Exception as error:self.failed.emit(str(error))
