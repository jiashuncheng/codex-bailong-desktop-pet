"""Authenticated shared transport and offline cache; never send raw logs."""
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

def connection(config):
    url=str(config.get('url','')).rstrip('/');parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('','/'):
        raise SyncError('同步服务必须使用 HTTPS 主地址。')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ca=config.get('ca')
    if ca:context.load_verify_locations(cadata=ca)
    else:context.load_default_certs()
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    return url,opener

def request(config,path,payload=None,token='',timeout=8):
    url,opener=connection(config)
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

def sync_once(state,home,stop=lambda:False,budget=4,cycle=None):
    state=Path(state);config=read_config(state)
    if not config.get('enabled'):return None
    token=token_for(state,config)
    if not token:raise SyncError('尚未导入 Token 同步连接文件。')
    identity=hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:16]
    ledger=SyncLedger(state/('token-sync-ledger-'+identity+'.sqlite3'),home)
    scan=ledger.scan(stop,budget)
    capabilities=request(config,'/health')
    unified=capabilities.get('schema',1)>=2
    target=hashlib.sha256((config['url']+'\0'+config['device_id']+('v2' if unified else '')).encode()).hexdigest()
    uploaded=0;more=False
    for _ in range(5):
        if stop():raise SyncError('同步已停止。')
        batch=ledger.batch(target,v2=unified)
        if not batch:break
        records=[{k:v for k,v in row.items() if k!='seq'} for row in batch]
        ack=request(config,'/v2/records' if unified else '/v1/records',dict(records=records),token)
        if ack.get('accepted')!=len(batch):raise SyncError('同步回执无效，未推进本地进度。')
        ledger.acknowledge(target,batch[-1]['seq']);uploaded+=len(batch)
    more=bool(ledger.batch(target,1)) or scan['more']
    if unified:
        if uploaded or more:request(config,'/v2/progress',dict(ready=False),token)
        from shared_quota import upload
        more=upload(state,home,config,token,request,stop,cycle) or more
    if unified:request(config,'/v2/progress',dict(ready=not more and not scan['errors']),token)
    snapshot=request(config,'/v1/snapshot',token=token)
    if snapshot.get('scope')!='all' or not isinstance(snapshot.get('all_total'),int) or not isinstance(snapshot.get('history_days'),dict):raise SyncError('汇总响应无效，保留上一份统计。')
    snapshot.update(sync_checked=time.time(),sync_more=more,sync_scan_errors=scan['errors'])
    if more or scan['errors']:snapshot['partial']=True
    atomic(state/'token-sync-cache.json',snapshot)
    atomic(state/'token-sync-status.json',dict(connected=True,checked=time.time(),uploaded=uploaded,more=more,scan_errors=scan['errors'],total=snapshot['all_total'],devices=snapshot.get('devices',[])))
    return snapshot

def fetch_snapshot(state):
    state=Path(state);config=read_config(state)
    value=request(config,'/v1/snapshot',token=token_for(state,config))
    if value.get('scope')!='all' or type(value.get('all_total')) is not int or not isinstance(value.get('history_days'),dict):raise SyncError('汇总响应无效')
    value.update(sync_checked=time.time(),sync_connected=True)
    atomic(state/'token-sync-cache.json',value)
    return value

def with_local_quota(cloud,local):
    result=dict(cloud)
    # Global counters must never inherit a different device's denominator.
    if result.get('quota_scope')!='all':
        result.pop('week_cycle',None)
        result['quota_history']=dict(cycles=[],anomaly=None,pending=True,partial=True,scope='all',reason='汇总服务待升级')
    return result


def apply_sync(local,state,home,stop=lambda:False,cycle=None):
    config=read_config(state)
    if not config.get('enabled'):return local
    try:
        cloud=sync_once(state,home,stop,cycle=cycle)
        if config.get('view','all')=='local':return dict(local,sync_connected=True)
        return with_local_quota(cloud,local)
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        status=dict(connected=False,checked=time.time(),error=str(error) if isinstance(error,SyncError) else '同步暂不可用，稍后重试。')
        atomic(Path(state)/'token-sync-status.json',status)
        if config.get('view','all')!='local':
            try:
                cloud=json.loads((Path(state)/'token-sync-cache.json').read_text(encoding='utf-8'))
                return with_local_quota(dict(cloud,partial=True,sync_stale=True,sync_connected=False,source='多端 Codex 日志（离线缓存）'),local)
            except (OSError,ValueError,TypeError):pass
        return dict(local,sync_connected=False,source='本机 Codex 日志（多端同步暂不可用）')


def state_events(config,token,stop):
    """Bounded SSE decoder. Authorization never enters URLs or event payloads."""
    url,opener=connection(config)
    headers={'Accept':'text/event-stream','Authorization':'Bearer '+token,'Cache-Control':'no-cache'}
    with opener.open(Request(url+'/v3/events',headers=headers),timeout=20) as response:
        if response.headers.get_content_type()!='text/event-stream':raise SyncError('推送响应类型无效')
        data=[];size=0
        while not stop():
            line=response.readline(8*1024*1024+1)
            if not line:raise SyncError('推送连接已断开')
            if len(line)>8*1024*1024:raise SyncError('推送消息过大')
            if line in (b'\n',b'\r\n'):
                if data:
                    value=json.loads(b'\n'.join(data))
                    if not isinstance(value,dict) or value.get('schema')!=2 or not isinstance(value.get('sessions'),list):raise SyncError('推送快照无效')
                    yield value
                data=[];size=0
            elif line.startswith(b'data:'):
                part=line[5:].strip();size+=len(part)
                if size>8*1024*1024:raise SyncError('推送消息过大')
                data.append(part)
