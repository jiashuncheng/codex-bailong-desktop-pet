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
        self.last_catalog=0;self.names={}
    def snapshot(self):
        from session_read_state import conversation_names,active_conversations,terminal_conversations
        from enhanced_core import Session
        now=time.time()
        seeds=active_conversations(self.tail.home)
        self.tail.set_pins([e['session'] for e in seeds]);self.tail.poll()
        for e in seeds:
            if not any(session_id(s)==e['session'] for s in self.tail.reducer.sessions):
                self.tail.reducer.sessions[e['session']]=Session(title=e['title'],state='working',turn=e['turn'],done=False,provenance_known=True)
        items=self.tail.reducer.sessions
        pairs=[(s,v.turn) for s,v in items.items() if not v.source_subagent and not v.done and v.turn]
        for sid,turn,status in terminal_conversations(self.tail.home,pairs):
            alias=next((s for s in items if session_id(s)==sid),sid)
            self.tail.reducer.terminate(alias,status,turn)
        ids=[session_id(s) for s,v in items.items() if not v.source_subagent]
        if now-self.last_catalog>=3:
            self.names=conversation_names(self.tail.home,ids);self.last_catalog=now
        stamps={}
        for path,f in self.tail.files.items():
            try:stamps[session_id(f['sid'])]=max(stamps.get(session_id(f['sid']),0),path.stat().st_mtime)
            except OSError:pass
        result=[];self.aliases={};self.turns={}
        for sid,s in items.items():
            if s.source_subagent or not s.provenance_known or s.source_kind=='ssh' or not s.turn:continue
            local=session_id(sid);stamp=stamps.get(local)
            if not stamp or now-stamp>86400:continue
            key=hashed(local);turn=hashed(s.turn);self.aliases[key]=local;self.turns[(key,turn)]=s.turn
            state=s.state
            if s.done and state not in ('complete','interrupted'):state='idle'
            if s.runtime_turn==s.turn and s.runtime_active is False and not s.done:state='idle'
            display=s.display or {'thinking':'正在思考','working':'正在处理任务','responding':'正在整理回复','complete':'任务已完成','waiting':'等待操作'}.get(state,'等待任务')
            if now-stamp>900 and state in ACTIVE:state='offline';display='任务状态待确认'
            title=public(self.names.get(local) or '会话 '+local[-6:],160)
            # Generic operation labels or already public assistant progress only;
            # don't expose the user prompt used internally as a fallback title.
            summary=public(s.public_summary or display,180)
            thread=local if re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',local) else ''
            result.append(dict(thread=thread,session=key,turn=turn,updated=min(now,stamp),state=state,title=title,summary=summary,display=public(display,100)))
        return result[:128],self.tail.health.get('state') not in ('unavailable','unknown')

class SharedWorker(threading.Thread):
    def __init__(self,state,home,stop,emit=None):
        super().__init__(name='BailongSharedState',daemon=True)
        self.state=Path(state);self.home=Path(home);self.stop=stop;self.emit=emit or (lambda e:None)
        self.collector=SessionCollector(home);self.last={};self.remote=set();self.connected=False;self.has_shared=False;self.routes={}
    def once(self):
        from token_sync import read_config,token_for,request,atomic
        config=read_config(self.state)
        if not config.get('enabled'):return None
        token=token_for(self.state,config)
        sessions,ready=self.collector.snapshot();reads=pending_reads(self.state)
        # The collector heartbeat and Token backfill completeness have separate
        # clocks. Publish the latter explicitly for account-capacity calculations.
        try:
            status=json.loads((self.state/'token-sync-status.json').read_text(encoding='utf-8'))
            accounting=bool(status.get('connected') and not status.get('more') and not status.get('scan_errors'))
        except (OSError,ValueError):accounting=False
        payload=dict(origin=origin_name(config),sessions=sessions,reads=reads,ready=ready,accounting_ready=accounting)
        value=request(config,'/v2/state',payload,token,timeout=5)
        if value.get('schema')!=2 or not isinstance(value.get('sessions'),list):raise OSError('共享状态格式无效')
        acknowledge_reads(self.state,reads);self.connected=True;self.has_shared=True
        atomic(self.state/'shared-state-cache.json',value)
        atomic(self.state/'shared-state-status.json',dict(connected=True,checked=time.time(),origin=payload['origin'],sessions=len(value['sessions']),accounting_ready=accounting))
        self.emit(dict(kind='shared_connected'))
        self.publish(value)
        return value
    def publish(self,value):
        own=self.collector.aliases;turns=self.collector.turns;active=sum(r['state'] in ACTIVE for r in value['sessions'])
        now=time.time();names={};sources={};current=set()
        read_set={(r['session'],r['turn']) for r in value.get('reads',[])}
        receipt=[]
        for row in value['sessions']:
            key=row['session'];sid=own.get(key,key);turn=turns.get((key,row['turn']),row['turn'])
            if key in own:continue # The local reducer is authoritative on this client.
            if row.get('thread'):self.routes[sid]=row['thread']
            current.add(sid);names[sid]=row['title'];sources[sid]=dict(source_kind='ssh',source_label=row['origin'])
            detail=row['display']+(' · '+row['summary'] if row.get('summary') and row['summary']!=row['display'] else '')
            event=dict(kind='status',session=sid,turn=turn,state=row['state'],title=row['title'],conversation_name=row['title'],display=detail,text=detail,active=active,source_kind='ssh',source_label=row['origin'],shared=True)
            signature=json.dumps(row,sort_keys=True)
            if self.last.get(key)!=signature:
                # Reconnecting doesn't announce old completions; seen keys are
                # durable locally and centrally scoped to the exact turn.
                if row['state']=='complete' and now-row['updated']<120 and (key,row['turn']) not in read_set:
                    self.emit(dict(event,kind='complete'))
                self.emit(event);self.last[key]=signature
        for sid in self.remote-current:self.emit(dict(kind='status',session=sid,state='idle',display='来源已结束此会话',shared=True))
        self.remote=current
        self.emit(dict(kind='conversation_names',names=names,sources=sources))
        for r in value.get('reads',[]):
            sid=own.get(r['session'],r['session']);turn=turns.get((r['session'],r['turn']),r['turn']);receipt.append((sid,turn))
        if receipt:self.emit(dict(kind='read_receipts',seen=receipt,shared=True))
    def run(self):
        while not self.stop.is_set():
            try:self.once()
            except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
                from token_sync import atomic
                self.connected=False
                atomic(self.state/'shared-state-status.json',dict(connected=False,checked=time.time(),error='共享状态暂不可用，稍后重试'))
                for sid in self.remote:self.emit(dict(kind='status',session=sid,state='offline',display='同步中断，等待重连',shared=True,source_kind='ssh'))
            self.stop.wait(5)
