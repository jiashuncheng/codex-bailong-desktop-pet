"""Small public session snapshots and monotonic read receipts over shared HTTPS."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from session_read_state import session_id

import weakref
_READ_WAKES=weakref.WeakValueDictionary()

ACTIVE={'thinking','working','responding','waiting'}

def hashed(value):return hashlib.sha256(str(value).encode()).hexdigest()

def wire_id(value):
    value=session_id(value)
    return value if re.fullmatch('[0-9a-f]{64}',value) else hashed(value)

def wire_turn(value):
    value=str(value)
    return value if re.fullmatch('[0-9a-f]{64}',value) else hashed(value)

def origin_name(config=None):
    chosen=(config or {}).get('origin')
    if chosen in ('win','wsl','mac','gpu228'):return chosen
    if sys.platform=='win32':return 'win'
    if sys.platform=='darwin':return 'mac'
    if os.environ.get('WSL_DISTRO_NAME') or 'microsoft' in __import__('platform').release().lower():return 'wsl'
    raise ValueError('请在采集器配置中设置真实来源：win、wsl、mac 或 gpu228。')

def public(value,limit=180):
    from shared_sync_store import public_text
    text=str(value or '')
    text=re.sub(r'<(?:environment_context|INSTRUCTIONS|in-app-browser-context|external_codex_apps_open_page)[\s\S]*?</[^>]+>','',text)
    return public_text(text[:20000],20000)[:limit]

def remember_reads(state,keys):
    """Only explicit acknowledgement/read evidence calls this; expiry does not."""
    path=Path(state)/'shared-read-outbox.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=2)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS reads(session TEXT,turn TEXT,stamp REAL,PRIMARY KEY(session,turn))')
        db.executemany('INSERT OR IGNORE INTO reads VALUES(?,?,?)',[(wire_id(s),wire_turn(t),time.time()) for s,t in keys if s and t])

    wake=_READ_WAKES.get(str(Path(state).resolve()))
    if wake:wake.set()

def pending_reads(state):
    path=Path(state)/'shared-read-outbox.sqlite3'
    if not path.exists():return []
    with closing(sqlite3.connect(path,timeout=2)) as db:
        return [dict(session=s,turn=t) for s,t in db.execute('SELECT session,turn FROM reads ORDER BY stamp LIMIT 512')]

def acknowledge_reads(state,rows):
    if not rows:return
    with closing(sqlite3.connect(Path(state)/'shared-read-outbox.sqlite3',timeout=2)) as db,db:
        db.executemany('DELETE FROM reads WHERE session=? AND turn=?',[(r['session'],r['turn']) for r in rows])

class SessionCollector:
    """Reuse the same provenance/turn reducer as the desktop, no raw log upload."""
    def __init__(self,home):
        from enhanced_core import RolloutTail
        self.tail=RolloutTail(home);self.aliases={};self.turns={};self.started=time.time()
        from live_rate import LiveOutputRate
        self.output_rate=LiveOutputRate();self.token_changed=threading.Event()
        def observe(sid,payload,stamp,**kw):
            self.output_rate.ingest(sid,payload,stamp,**kw)
            if payload.get('type')=='token_count' and not kw.get('historical'):self.token_changed.set()
        self.tail.rate_observer=observe
        self.last_catalog=0;self.names={};self.tail.catalog.interval=1
    def snapshot(self):
        from session_read_state import conversation_names,active_conversations,terminal_conversations,restore_active_turns
        from enhanced_core import Session
        now=time.time()
        seeds=active_conversations(self.tail.home)
        self.tail.set_pins([e['session'] for e in seeds]);self.tail.poll()
        restore_active_turns(self.tail.home,self.tail.reducer,seeds)
        items=self.tail.reducer.sessions
        pairs=[(s,v.turn) for s,v in items.items() if not v.source_subagent and not v.done and v.turn]
        for sid,turn,status in terminal_conversations(self.tail.home,pairs):
            alias=next((s for s in items if session_id(s)==sid),sid)
            self.tail.reducer.terminate(alias,status,turn)
        ids=[session_id(s) for s,v in items.items() if not v.source_subagent]
        if now-self.last_catalog>=3:
            self.names=conversation_names(self.tail.home,ids);self.last_catalog=now
        return self.render()
    def render(self):
        now=time.time();items=self.tail.reducer.sessions
        stamps={}
        for path,f in self.tail.files.items():
            try:stamps[session_id(f['sid'])]=max(stamps.get(session_id(f['sid']),0),path.stat().st_mtime)
            except OSError:pass
        result=[];self.aliases={};self.turns={}
        previous=getattr(self,'previous',{});current={}
        for sid,s in items.items():
            if s.source_subagent or not s.provenance_known or s.source_kind=='ssh' or not s.turn:continue
            local=session_id(sid);stamp=stamps.get(local)
            if not stamp or now-stamp>86400:continue
            key=hashed(local);turn=hashed(s.turn);self.aliases[key]=local;self.turns[(key,turn)]=s.turn
            state='waiting' if s.waiting_reason and not s.done else 'working' if s.compacting else s.state
            if s.done and state not in ('complete','interrupted'):state='idle'
            if s.runtime_turn==s.turn and s.runtime_active is False and not s.done:state='idle'
            display=s.display or {'thinking':'正在思考','working':'正在处理任务','responding':'正在整理回复','complete':'任务已完成','waiting':'等待操作'}.get(state,'等待任务')
            if now-stamp>900 and state in ACTIVE and not (s.runtime_active is True and s.runtime_turn==s.turn):state='offline';display='任务状态待确认'
            title=public(self.names.get(local) or '会话 '+local[-6:],160)
            # Generic operation labels or already public assistant progress only;
            # don't expose the user prompt used internally as a fallback title.
            summary=public(s.public_summary or display,180)
            thread=local if re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',local) else ''
            row=dict(thread=thread,session=key,turn=turn,state=state,title=title,summary=summary,display=public(display,100))
            fingerprint=json.dumps(row,sort_keys=True)
            old=previous.get(key)
            updated=old[1] if old and old[0]==fingerprint else max(min(now,stamp),now if old else 0,old[1]+.000001 if old else 0)
            current[key]=(fingerprint,updated);row['updated']=updated;result.append(row)
        self.previous=current
        return result[:128],self.tail.health.get('state') not in ('unavailable','unknown')

class SharedWorker(threading.Thread):
    def __init__(self,state,home,stop,emit=None):
        super().__init__(name='BailongSharedState',daemon=True)
        self.state=Path(state);self.home=Path(home);self.stop=stop;self.emit=emit or (lambda e:None)
        self.collector=SessionCollector(home);self.last={};self.remote=set();self.routes={}
        self.connected=False;self.has_shared=False;self.push_connected=False
        self.wake=threading.Event();_READ_WAKES[str(self.state.resolve())]=self.wake
        self.local_lock=threading.Lock();self.local=None;self.renderer=SessionCollector(home)
        self.apply_lock=threading.RLock();self.epoch=None;self.revision=-1;self.last_snapshot=None
        self.rates=[];self.usage_wake=threading.Event();self.token_wake=threading.Event();self.usage_key=None
        self.listener=None;self.sent=None;self.last_sent=0.;self.last_poll=0.;self.last_status=0.;self.last_received=None
    def update_rates(self,value):
        from shared_rates import wire
        rows=wire(value)
        with self.local_lock:
            changed=rows!=self.rates;self.rates=rows
        if changed:self.wake.set()
    def update_local(self,tail,names):
        # Invoked only by the desktop activity thread. Copy public fields before
        # the network thread accesses them; IPC idleness/waiting is retained.
        self.renderer.tail=tail;self.renderer.names=dict(names)
        rows,ready=self.renderer.render()
        value=(rows,ready,dict(self.renderer.aliases),dict(self.renderer.turns))
        with self.local_lock:
            changed=self.local!=value;self.local=value
        if changed:self.wake.set()
    def local_snapshot(self):
        with self.local_lock:value=self.local
        if value is not None:return value
        rows,ready=self.collector.snapshot()
        self.update_rates(self.collector.output_rate.snapshot())
        if self.collector.token_changed.is_set():
            self.collector.token_changed.clear();self.token_wake.set()
        return rows,ready,dict(self.collector.aliases),dict(self.collector.turns)
    def status(self,error=None):
        from token_sync import atomic
        if time.monotonic()-self.last_status<.5 and not error:return
        self.last_status=time.monotonic()
        atomic(self.state/'shared-state-status.json',dict(connected=self.connected,checked=time.time(),origin=getattr(self,'origin',''),
            sessions=len((self.last_snapshot or {}).get('sessions',[])),mode='push' if self.push_connected else 'poll',push_connected=self.push_connected,
            revision=self.revision,stream_id=self.epoch,last_received=self.last_received,accounting_ready=getattr(self,'accounting',False),error=error))
    def accept(self,value,stream_new=False):
        from token_sync import atomic
        if value.get('schema')!=2 or not isinstance(value.get('sessions'),list):raise OSError('共享状态格式无效')
        with self.apply_lock:
            epoch=value.get('stream_id');revision=value.get('revision')
            if epoch is not None and type(revision) is int:
                if epoch!=self.epoch:
                    if self.epoch is not None and not stream_new:return False
                    self.epoch=epoch;self.revision=-1
                if revision<self.revision:return False
                if revision==self.revision:
                    self.connected=True;self.status();return False
                self.revision=revision
            self.connected=True;self.has_shared=True;self.last_snapshot=value;self.last_received=time.time()
            atomic(self.state/'shared-state-cache.json',value)
            key=(epoch,value.get('usage_revision'))
            if key!=self.usage_key and key[1] is not None:self.usage_key=key;self.usage_wake.set()
            from token_sync import read_config
            if read_config(self.state).get('view','all')=='all' and 'live_output_rate' in value:
                from shared_rates import local
                self.emit(dict(kind='live_output_rate',value=local(value['live_output_rate'])))
            self.emit(dict(kind='shared_connected'));self.publish(value);self.status()
        return True
    def once(self,force=False):
        from token_sync import read_config,token_for,request
        config=read_config(self.state)
        if not config.get('enabled'):
            self.connected=False;self.push_connected=False
            return None
        token=token_for(self.state,config);self.origin=origin_name(config)
        if __import__('codex_connection').is_wsl_source(self.home):self.origin='wsl'
        sessions,ready,aliases,turns=self.local_snapshot()
        with self.apply_lock:self.aliases=aliases;self.turns=turns
        reads=pending_reads(self.state)
        try:
            status=json.loads((self.state/'token-sync-status.json').read_text(encoding='utf-8'))
            accounting=bool(status.get('connected') and not status.get('more') and not status.get('scan_errors'))
        except (OSError,ValueError):accounting=False
        self.accounting=accounting
        with self.local_lock:rates=list(self.rates)
        payload=dict(origin=self.origin,label=public(config.get('device_name') or self.origin,40),sessions=sessions,reads=reads,ready=ready,accounting_ready=accounting,rates=rates)
        signature=json.dumps(payload,sort_keys=True)
        if force or signature!=self.sent or time.monotonic()-self.last_sent>=20:
            value=request(config,'/v2/state',payload,token,timeout=5)
            if value.get('schema')!=2:raise OSError('共享状态格式无效')
            acknowledge_reads(self.state,reads);self.sent=signature;self.last_sent=time.monotonic()
            self.accept(value);self.connected=True
        elif not self.push_connected and time.monotonic()-self.last_poll>=5:
            self.last_poll=time.monotonic();value=request(config,'/v2/state',token=token,timeout=5);self.accept(value,stream_new=True)
        self.status()
        return self.last_snapshot
    def listen(self):
        from token_sync import read_config,token_for,state_events
        delay=1
        while not self.stop.is_set():
            config=read_config(self.state)
            if not config.get('enabled'):
                self.stop.wait(1);continue
            try:
                first=True
                for value in state_events(config,token_for(self.state,config),lambda:self.stop.is_set() or not read_config(self.state).get('enabled')):
                    if not read_config(self.state).get('enabled'):break
                    self.push_connected=True;self.accept(value,stream_new=first);first=False;delay=1
                    if self.stop.is_set():break
            except (OSError,ValueError,KeyError,TypeError):pass
            self.push_connected=False;self.wake.set();self.status()
            self.stop.wait(delay);delay=min(20,delay*2)
    def publish(self,value):
        own=getattr(self,'aliases',{});turns=getattr(self,'turns',{});active=sum(r['state'] in ACTIVE for r in value['sessions'])
        now=time.time();names={};sources={};current=set()
        read_set={(r['session'],r['turn']) for r in value.get('reads',[])}
        receipt=[]
        for row in value['sessions']:
            key=row['session'];sid=own.get(key,key);turn=turns.get((key,row['turn']),row['turn'])
            if row.get('thread'):self.routes[sid]=row['thread']
            label=row.get('source_label') or row['origin']
            current.add(sid);names[sid]=row['title'];sources[sid]=dict(source_kind='local' if key in own else 'ssh',source_label=label)
            detail=row['display']+(' · '+row['summary'] if row.get('summary') and row['summary']!=row['display'] else '')
            event=dict(kind='status',session=sid,turn=turn,state=row['state'],title=row['title'],conversation_name=row['title'],display=detail,text=detail,active=active,source_kind=sources[sid]['source_kind'],source_label=label,shared=True)
            signature=json.dumps(row,sort_keys=True)
            if self.last.get(key)!=signature:
                if row['state']=='complete' and now-row['updated']<120 and (key,row['turn']) not in read_set:
                    self.emit(dict(event,kind='complete'))
                self.emit(event);self.last[key]=signature
        for sid in self.remote-current:self.emit(dict(kind='status',session=sid,state='idle',display='来源已结束此会话',shared=True))
        self.remote=current
        self.emit(dict(kind='conversation_names',names=names,sources=sources))
        for r in value.get('reads',[]):
            sid=own.get(r['session'],r['session']);turn=turns.get((r['session'],r['turn']),r['turn']);receipt.append((sid,turn))
        if receipt:self.emit(dict(kind='read_receipts',seen=receipt,shared=True))
    def refresh_usage(self):
        from token_sync import read_config,fetch_snapshot
        while not self.stop.is_set():
            if not self.usage_wake.wait(.5):continue
            self.usage_wake.clear()
            try:
                if read_config(self.state).get('enabled') and read_config(self.state).get('view','all')=='all':
                    value=fetch_snapshot(self.state)
                    if value.get('stream_id')==self.epoch:self.emit(dict(kind='token_usage',snapshot=value,shared=True))
            except (OSError,ValueError,KeyError,sqlite3.Error):pass
            self.stop.wait(1)
    def run(self):
        threading.Thread(target=self.refresh_usage,name='BailongUsageEvents',daemon=True).start()
        try:self.once(force=True)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):pass
        self.listener=threading.Thread(target=self.listen,name='BailongStateEvents',daemon=True);self.listener.start()
        while not self.stop.is_set():
            self.wake.clear()
            try:self.once()
            except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
                self.connected=self.push_connected
                self.status('会话上报暂不可用，稍后重试')
            # Local change detection never performs a periodic network upload.
            # Desktop events wake immediately; headless logs are checked locally.
            self.wake.wait(.5 if self.local is None else 1.)
