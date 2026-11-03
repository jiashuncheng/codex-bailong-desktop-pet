"""Versioned shared state, backed by the same authenticated sync database."""
import json
import math
import re
import time
from contextlib import closing

ORIGINS={'win','wsl','mac','gpu228'}
STATES={'thinking','working','responding','waiting','complete','interrupted','idle','offline'}
ACTIVE={'thinking','working','responding','waiting'}

def identity(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('invalid identity')
    return value

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<4102444800:raise ValueError('invalid timestamp')
    return value

def public_text(value,limit):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('invalid public text')
    # Defense in depth; clients also redact before any transmission.
    value=re.sub(r'```[\s\S]*?```','[代码]',value)
    value=re.sub(r'(?i)\b(?:sk-[\w-]{8,}|bearer\s+[\w.-]+|(?:token|password|api[_-]?key|secret)\s*[:=]\s*\S+)','[凭据]',value)
    value=re.sub(r'(?:[A-Za-z]:[\\/]|/(?:home|Users|mnt|etc|opt|tmp)/)[^\s，。；]+','[路径]',value)
    return re.sub(r'\s+',' ',value).strip()

class SharedStore:
    def __init__(self,store):
        self.store=store
        from quota_history import migrate
        from quota_workload import migrate as workload_migrate
        with closing(store.connect()) as db,db:
            migrate(db);workload_migrate(db)
            db.executescript('''
            CREATE TABLE IF NOT EXISTS shared_devices(device TEXT PRIMARY KEY,origin TEXT,seen REAL,ready INTEGER,accounting_ready INTEGER);
            CREATE TABLE IF NOT EXISTS shared_sessions(device TEXT,session TEXT,turn TEXT,origin TEXT,updated REAL,state TEXT,title TEXT,summary TEXT,display TEXT,thread TEXT,PRIMARY KEY(device,session));
            CREATE TABLE IF NOT EXISTS shared_reads(session TEXT,turn TEXT,stamp REAL,PRIMARY KEY(session,turn));
            CREATE TABLE IF NOT EXISTS accounting_devices(device TEXT PRIMARY KEY,ready INTEGER,seen REAL);
            CREATE TABLE IF NOT EXISTS raw_workload(session TEXT,total INTEGER,cached INTEGER,speed TEXT,effort TEXT,PRIMARY KEY(session,total));
            ''')
            if 'label' not in {r[1] for r in db.execute('PRAGMA table_info(shared_devices)')}:
                db.execute("ALTER TABLE shared_devices ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        from state_events import StateEvents
        self.events=StateEvents(self)
    def ingest(self,device,payload,now=None):
        now=time.time() if now is None else now
        if not isinstance(payload,dict) or set(payload)-{'origin','sessions','reads','ready','accounting_ready','rates','label'}:raise ValueError('unexpected state fields')
        label=public_text(payload['label'],40) if 'label' in payload else None
        origin=payload.get('origin');rows=payload.get('sessions');reads=payload.get('reads',[])
        if origin not in ORIGINS or (type(payload.get('ready')) is not bool or type(payload.get('accounting_ready')) is not bool):raise ValueError('invalid source')
        if not isinstance(rows,list) or len(rows)>128 or not isinstance(reads,list) or len(reads)>512:raise ValueError('invalid batch')
        from shared_rates import validate,replace
        rates=validate(payload.get('rates',[]),now) if 'rates' in payload else None
        clean=[];receipt=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)-{'session','turn','updated','state','title','summary','display','thread'} or not {'session','turn','updated','state','title','summary','display'}<=set(row):raise ValueError('unexpected session fields')
            sid=identity(row['session']);turn=identity(row['turn']);stamp=number(row['updated'])
            if stamp>now+120 or row['state'] not in STATES:raise ValueError('invalid state')
            thread=row.get('thread','')
            if not isinstance(thread,str) or (thread and (not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',thread) or __import__('hashlib').sha256(thread.encode()).hexdigest()!=sid)):raise ValueError('invalid navigation identity')
            clean.append((device,sid,turn,origin,stamp,row['state'],public_text(row['title'],200),public_text(row['summary'],240),public_text(row['display'],100),thread))
        for row in reads:
            if not isinstance(row,dict) or set(row)!={'session','turn'}:raise ValueError('invalid read receipt')
            receipt.append((identity(row['session']),identity(row['turn']),now))
        with closing(self.store.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            previous_device=db.execute('SELECT origin,seen,ready,label FROM shared_devices WHERE device=?',(device,)).fetchone()
            label=label if label is not None else previous_device[3] if previous_device else ''
            changed=not previous_device or previous_device[0]!=origin or bool(previous_device[2])!=payload['ready'] or now-previous_device[1]>90 or previous_device[3]!=label
            db.execute('INSERT OR REPLACE INTO shared_presence VALUES(?,?)',(device,int(payload['ready'])))
            db.execute('INSERT OR REPLACE INTO shared_devices(device,origin,seen,ready,accounting_ready,label) VALUES(?,?,?,?,?,?)',(device,origin,now,int(payload['ready']),int(payload['accounting_ready']),label))
            for row in clean:
                old=db.execute('SELECT device,session,turn,origin,updated,state,title,summary,display,thread FROM shared_sessions WHERE device=? AND session=?',(device,row[1])).fetchone()
                accepted=old is None or row[4]>old[4] or (row[4]==old[4] and (old[5] not in ('complete','interrupted') or row[5] in ('complete','interrupted')))
                changed=changed or bool(accepted and tuple(row)!=old)
                db.execute('''INSERT INTO shared_sessions VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(device,session) DO UPDATE SET
                turn=excluded.turn,origin=excluded.origin,updated=excluded.updated,state=excluded.state,title=excluded.title,summary=excluded.summary,display=excluded.display,thread=excluded.thread
                WHERE excluded.updated>shared_sessions.updated OR (excluded.updated=shared_sessions.updated AND
                  (shared_sessions.state NOT IN ('complete','interrupted') OR excluded.state IN ('complete','interrupted')))''',row)
            # A full, healthy collector snapshot is authoritative for membership.
            if payload['ready']:
                wanted={r[1] for r in clean}
                for sid, in db.execute('SELECT session FROM shared_sessions WHERE device=?',(device,)).fetchall():
                    if sid not in wanted:
                        db.execute('DELETE FROM shared_sessions WHERE device=? AND session=?',(device,sid));changed=True
            if rates is not None:changed=replace(db,device,rates) or changed
            before=db.total_changes
            db.executemany('INSERT OR IGNORE INTO shared_reads VALUES(?,?,?)',receipt)
            changed=changed or db.total_changes>before
            if label:db.execute('UPDATE devices SET name=?,last_seen=? WHERE id=?',(label,now,device))
            else:db.execute('UPDATE devices SET last_seen=? WHERE id=?',(now,device))
            db.execute('DELETE FROM shared_reads WHERE stamp<?',(now-90*86400,))
            if changed:self.events.bump(db)
        if changed:self.events.notify()
        return self.snapshot(now)
    def snapshot(self,now=None):
        now=time.time() if now is None else now
        self.events.expire(now)
        with closing(self.store.connect()) as db:
            db.execute('BEGIN')
            revision=self.events.revision(db);usage_revision=self.events.usage_revision(db)
            from shared_rates import snapshot
            rates=snapshot(db,now)
            rows=db.execute('''SELECT s.session,s.turn,s.origin,s.updated,s.state,s.title,s.summary,s.display,d.seen,d.ready,s.device,s.thread
            FROM shared_sessions s JOIN shared_devices d ON d.device=s.device ORDER BY s.updated DESC,
              CASE WHEN s.state IN ('complete','interrupted') THEN 0 ELSE 1 END,d.seen DESC''').fetchall()
            sessions={}
            labels={d:label for d,label in db.execute('SELECT device,label FROM shared_devices')}
            for sid,turn,origin,updated,state,title,summary,display,seen,ready,device,thread in rows:
                if sid in sessions or now-updated>86400:continue
                stale=not ready or now-seen>90
                if stale and state in ACTIVE:state='offline';display='来源离线，等待同步'
                sessions[sid]=dict(session=sid,turn=turn,origin=origin,source_label=labels.get(device) or origin,updated=updated,state=state,title=title,summary=summary,display=display,stale=stale,device_id=device,thread=thread)
            reads=[dict(session=s,turn=t) for s,t in db.execute('SELECT session,turn FROM shared_reads WHERE stamp>? ORDER BY stamp DESC LIMIT 4096',(now-90*86400,))]
            devices=[dict(device_id=d,origin=o,last_seen=s,ready=bool(r)) for d,o,s,r in db.execute('SELECT device,origin,seen,ready FROM shared_devices')]
        return dict(schema=2,usage_revision=usage_revision,live_output_rate=rates,revision=revision,stream_id=self.events.epoch,checked=now,sessions=list(sessions.values())[:256],reads=reads,devices=devices)
    def quotas(self,device,rows):
        from quota_history import valid_sample,store
        if not isinstance(rows,list) or len(rows)>1000:raise ValueError('invalid quota batch')
        clean=[]
        for r in rows:
            if not isinstance(r,dict) or set(r)!={'stamp','deadline','remaining','plan','boundary','reset_kind'}:raise ValueError('invalid quota fields')
            if not valid_sample(r['stamp'],r['deadline'],r['remaining']) or r['stamp']>time.time()+120:raise ValueError('invalid quota')
            if not isinstance(r['plan'],str) or len(r['plan'])>40 or r['reset_kind'] not in ('','natural','extra','changed','refill','capacity','unknown'):raise ValueError('invalid plan')
            boundary=r['boundary']
            if boundary is not None and (type(boundary) not in (int,float) or not math.isfinite(boundary) or not r['deadline']-604800-300<=boundary<=r['stamp']):raise ValueError('invalid boundary')
            clean.append(r)
        with closing(self.store.connect()) as db,db:
            changed=False
            for r in clean:
                old=db.execute('SELECT plan,boundary,reset_kind FROM quota_observations WHERE stamp=? AND deadline=? AND remaining=?',(r['stamp'],r['deadline'],r['remaining'])).fetchone()
                store(db,r['stamp'],r['deadline'],r['remaining'],'log',r['plan'],r['boundary'],r['reset_kind'])
                current=db.execute('SELECT plan,boundary,reset_kind FROM quota_observations WHERE stamp=? AND deadline=? AND remaining=?',(r['stamp'],r['deadline'],r['remaining'])).fetchone()
                changed=changed or old!=current
            if changed:self.events.usage_bump(db)
        if changed:self.events.notify()
        return dict(accepted=len(clean))
    def records(self,device,rows):
        from quota_workload import SPEEDS,EFFORTS,store
        if not isinstance(rows,list) or len(rows)>1000:raise ValueError('invalid batch')
        base=[];extras=[]
        for r in rows:
            if not isinstance(r,dict) or set(r)-{'session','total','stamp','model','input','output','cached','speed','effort'}:raise ValueError('unexpected fields')
            cached=r.get('cached');speed=r.get('speed','');effort=r.get('effort','')
            if cached is not None and (type(cached) is not int or not 0<=cached<= (r.get('input') or 0)):raise ValueError('invalid cache')
            if speed not in ('',*SPEEDS) or effort not in ('',*EFFORTS):raise ValueError('invalid workload')
            base.append({k:v for k,v in r.items() if k not in ('cached','speed','effort')})
            extras.append((r.get('session'),r.get('total'),cached,speed,effort))
        # ingest validates the entire base before writing. Extras were validated above.
        result=self.store.ingest(device,base,notify=False);changed=result['changed']
        with closing(self.store.connect()) as db,db:
            for sid,total,cached,speed,effort in extras:
                old=db.execute('SELECT cached,speed,effort FROM raw_workload WHERE session=? AND total=?',(sid,total)).fetchone()
                vals=(cached,speed,effort)
                if old:
                    conflict=any(a not in (None,'') and b not in (None,'') and a!=b for a,b in zip(old,vals))
                    vals=(-1,'','') if conflict or old[0]==-1 else tuple(a if a not in (None,'') else b for a,b in zip(old,vals))
                changed=changed or old is None or tuple(old)!=vals
                db.execute('INSERT OR REPLACE INTO raw_workload VALUES(?,?,?,?,?)',(sid,total,*vals))
            for sid in {r[0] for r in extras}:
                previous=0;pc=0
                for total,model,cached,speed,effort in db.execute('SELECT r.total,r.model,w.cached,w.speed,w.effort FROM raw r LEFT JOIN raw_workload w ON r.session=w.session AND r.total=w.total WHERE r.session=? ORDER BY r.total',(sid,)).fetchall():
                    dc=cached-pc if cached is not None and pc is not None and cached>=0 and pc>=0 else None
                    store(db,sid+':'+str(total),model,total-previous,dc if dc is not None and dc>=0 else None,dict(speed=speed or '',effort=effort or ''))
                    previous=total;pc=cached
            if changed:self.events.usage_bump(db)
        if changed:self.events.notify()
        return result
    def progress(self,device,ready):
        if type(ready) is not bool:raise ValueError('invalid progress')
        with closing(self.store.connect()) as db,db:
            old=db.execute('SELECT ready FROM accounting_devices WHERE device=?',(device,)).fetchone()
            db.execute('INSERT OR REPLACE INTO accounting_devices VALUES(?,?,?)',(device,int(ready),time.time()))
            changed=ready and (old is None or not old[0])
            if changed:self.events.usage_bump(db)
        if changed:self.events.notify()
        return dict(accepted=True)
    def quota_snapshot(self,db,now=None):
        from quota_history import summarize_cycles,anomaly
        from week_cycle import usage,summarize
        now=time.time() if now is None else now
        # Catch-up flags are explicit; disconnected devices retain data but cannot
        # claim complete account coverage. Legacy devices block comparisons.
        devices=db.execute('SELECT id,last_seen FROM devices').fetchall()
        readiness={d:bool(r and now-s<=900) for d,r,s in db.execute('SELECT device,accounting_ready,seen FROM shared_devices')}
        readiness.update({d:bool(r and now-s<=900) for d,r,s in db.execute('SELECT device,ready,seen FROM accounting_devices')})
        complete=bool(devices) and all(readiness.get(d,False) for d,_ in devices)
        cycles=summarize_cycles(db,now,complete)
        result=dict(quota_history=dict(cycles=cycles,anomaly=anomaly(cycles,now) if complete else None,pending=not complete,partial=not complete,scope='all'),quota_scope='all')
        row=db.execute('SELECT stamp,deadline,remaining,plan,boundary,reset_kind FROM quota_observations WHERE stamp<=? ORDER BY stamp DESC LIMIT 1',(now,)).fetchone()
        if row:
            stamp,deadline,remaining,plan,boundary,kind=row
            cycle=dict(start=boundary if boundary is not None else deadline-604800,through=stamp,remaining=remaining,reset_at=deadline,start_source='detected' if boundary is not None else 'inferred')
            result['week_cycle']=summarize(cycle,*usage(db,cycle),complete,now)
        return result
