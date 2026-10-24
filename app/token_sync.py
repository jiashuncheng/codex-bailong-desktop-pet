"""Cross-platform sync transport and offline cache; never send logs or prose."""
import hashlib
import json
import os
import platform
import socket
import sqlite3
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from urllib.error import HTTPError,URLError
from sync_ledger import SyncLedger


class SyncError(OSError):pass

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    import uuid
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf-8') as stream:
            if os.name!='nt':os.chmod(temp,0o600)
            json.dump(value,stream,ensure_ascii=False,separators=(',',':'))
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def config_path(state):return Path(state)/'token-sync.json'

def read_config(state):
    try:
        result=json.loads(config_path(state).read_text(encoding='utf-8'))
        return result if isinstance(result,dict) else {}
    except (FileNotFoundError,ValueError):return {}

def token_for(state,config):
    if sys.platform not in ('win32','darwin'):return config.get('token','')
    from desktop_services import SecretStore
    return SecretStore(Path(state)/'token-sync-credentials.json').get(config.get('credential_slot','access-token'))

def save_connection(state,config,token):
    state=Path(state);config=dict(config)
    if sys.platform in ('win32','darwin'):
        from desktop_services import SecretStore
        config['credential_slot']='device:'+config['device_id']
        SecretStore(state/'token-sync-credentials.json').put(config['credential_slot'],token)
    else:config=dict(config,token=token)
    atomic(config_path(state),config)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise SyncError('同步地址发生重定向，请检查连接配置。')

def request(config,path,payload=None,token='',timeout=8):
    url=str(config.get('url','')).rstrip('/');parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('','/'):
        raise SyncError('同步服务必须使用 HTTPS 主地址。')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ca=config.get('ca')
    if ca:context.load_verify_locations(cadata=ca)
    else:context.load_default_certs()
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    body=json.dumps(payload,separators=(',',':')).encode() if payload is not None else None
    headers={'Accept':'application/json','User-Agent':'BailongTokenSync/1'}
    if body is not None:headers['Content-Type']='application/json'
    if token:headers['Authorization']='Bearer '+token
    try:
        with opener.open(Request(url+path,data=body,headers=headers),timeout=timeout) as response:
            raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise SyncError('同步响应过大。')
            result=json.loads(raw)
            if not isinstance(result,dict):raise SyncError('同步响应格式无效。')
            return result
    except HTTPError as error:
        if error.code==401:raise SyncError('同步认证已失效，请重新导入连接文件。') from None
        if error.code==400:raise SyncError('连接文件已使用/过期，或同步数据校验失败。') from None
        raise SyncError('同步服务 HTTP '+str(error.code)) from None
    except (URLError,ssl.SSLError,socket.timeout,TimeoutError,ValueError):
        raise SyncError('无法安全连接同步服务，稍后自动重试；本地统计继续保存。') from None

def import_connection(state,bundle,name=None):
    if not isinstance(bundle,dict) or set(bundle)-{'schema','url','ca','invite','expires'}:raise SyncError('连接文件格式无效。')
    invite=bundle.get('invite')
    if not isinstance(invite,str) or not 20<=len(invite)<=256:raise SyncError('连接文件无效。')
    result=request(bundle,'/v1/enroll',dict(invite=invite,name=name or platform.node() or sys.platform))
    config={key:bundle[key] for key in ('url','ca') if key in bundle}
    config.update(enabled=True,view='all',device_id=result['device_id'],device_name=name or platform.node() or sys.platform)
    save_connection(state,config,result['token']);return config

def export_connection(state,destination):
    config=read_config(state);result=request(config,'/v1/invites',{},token_for(state,config))
    bundle={key:config[key] for key in ('url','ca') if key in config}
    bundle.update(schema=1,invite=result['invite'],expires=result['expires']);atomic(destination,bundle)

def sync_once(state,home,stop=lambda:False,budget=4):
    state=Path(state);config=read_config(state)
    if not config.get('enabled'):return None
    token=token_for(state,config)
    if not token:raise SyncError('尚未导入 Token 同步连接文件。')
    identity=hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:16]
    ledger=SyncLedger(state/('token-sync-ledger-'+identity+'.sqlite3'),home)
    scan=ledger.scan(stop,budget)
    target=hashlib.sha256((config['url']+'\0'+config['device_id']).encode()).hexdigest()
    uploaded=0;more=False
    for _ in range(5):
        if stop():raise SyncError('同步已停止。')
        batch=ledger.batch(target)
        if not batch:break
        records=[{k:v for k,v in row.items() if k!='seq'} for row in batch]
        ack=request(config,'/v1/records',dict(records=records),token)
        if ack.get('accepted')!=len(batch):raise SyncError('同步回执无效，未推进本地进度。')
        ledger.acknowledge(target,batch[-1]['seq']);uploaded+=len(batch)
    more=bool(ledger.batch(target,1)) or scan['more']
    snapshot=request(config,'/v1/snapshot',token=token)
    if snapshot.get('scope')!='all' or not isinstance(snapshot.get('all_total'),int) or not isinstance(snapshot.get('history_days'),dict):raise SyncError('汇总响应无效，保留上一份统计。')
    snapshot.update(sync_checked=time.time(),sync_more=more,sync_scan_errors=scan['errors'])
    if more or scan['errors']:snapshot['partial']=True
    atomic(state/'token-sync-cache.json',snapshot)
    atomic(state/'token-sync-status.json',dict(connected=True,checked=time.time(),uploaded=uploaded,more=more,scan_errors=scan['errors'],total=snapshot['all_total'],devices=snapshot.get('devices',[])))
    return snapshot

def apply_sync(local,state,home,stop=lambda:False):
    config=read_config(state)
    if not config.get('enabled'):return local
    try:
        cloud=sync_once(state,home,stop)
        if config.get('view','all')=='local':return dict(local,sync_connected=True)
        return cloud
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        status=dict(connected=False,checked=time.time(),error=str(error) if isinstance(error,SyncError) else '同步暂不可用，稍后重试。')
        atomic(Path(state)/'token-sync-status.json',status)
        if config.get('view','all')!='local':
            try:
                cloud=json.loads((Path(state)/'token-sync-cache.json').read_text(encoding='utf-8'))
                return dict(cloud,partial=True,sync_stale=True,sync_connected=False,source='多端 Codex 日志（离线缓存）')
            except (OSError,ValueError,TypeError):pass
        return dict(local,sync_connected=False,source='本机 Codex 日志（多端同步暂不可用）')
