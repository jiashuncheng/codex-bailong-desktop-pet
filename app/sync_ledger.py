"""Portable, content-free cumulative checkpoints for cross-device accounting."""
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from log_catalog import LogCatalog
from token_calendar import counter
from token_analytics import stamp_of,model_name,UNKNOWN


class SyncLedger:
    def __init__(self,path,home):
        self.path=Path(path);self.home=Path(home).resolve();self.catalog=LogCatalog(self.home)
        self.path.parent.mkdir(parents=True,exist_ok=True)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,offset INTEGER,session TEXT,model TEXT,header TEXT,mtime INTEGER,inode INTEGER)')
        columns={r[1] for r in db.execute('PRAGMA table_info(files)')}
        for column in ('mtime','inode'):
            if column not in columns:db.execute('ALTER TABLE files ADD COLUMN '+column+' INTEGER')
        db.execute('CREATE TABLE IF NOT EXISTS records(seq INTEGER PRIMARY KEY AUTOINCREMENT,session TEXT,total INTEGER,stamp REAL,model TEXT,input INTEGER,output INTEGER,UNIQUE(session,total))')
        db.execute('CREATE TABLE IF NOT EXISTS cursors(target TEXT PRIMARY KEY,seq INTEGER)')
        columns={r[1] for r in db.execute('PRAGMA table_info(records)')}
        if 'cached' not in columns:
            for column,kind in [('cached','INTEGER'),('speed','TEXT'),('effort','TEXT')]:db.execute('ALTER TABLE records ADD COLUMN '+column+' '+kind)
            # One bounded replay enriches old counters; a separate target cursor
            # sends the enriched union without changing any v1 acknowledgement.
            db.execute('DELETE FROM files');db.execute('DELETE FROM records');db.execute('DELETE FROM cursors')
        db.execute('CREATE TABLE IF NOT EXISTS scan_context(path TEXT PRIMARY KEY,state TEXT)')
        return db
    def scan(self,stop=lambda:False,budget=4):
        deadline=time.monotonic()+budget;errors=0;more=False;count=0
        with closing(self.connect()) as db,db:
            for path in sorted(self.catalog.discover(check=True)):
                if stop() or time.monotonic()>=deadline:more=True;break
                try:
                    if path.is_symlink():continue
                    stat=path.stat();size=stat.st_size
                    with path.open('rb') as stream:
                        header=stream.readline(4*1024*1024)
                        signature=hashlib.sha256(header).hexdigest()
                        row=db.execute('SELECT offset,session,model,header,mtime,inode FROM files WHERE path=?',(str(path),)).fetchone()
                        offset,sid,model,old_header,mtime,inode=row or (0,'',UNKNOWN,'',None,None)
                        if size<offset or old_header!=signature or inode!=stat.st_ino or (size==offset and mtime!=stat.st_mtime_ns):offset,sid,model=0,'',UNKNOWN
                        if size==offset:continue
                        context_row=db.execute('SELECT state FROM scan_context WHERE path=?',(str(path),)).fetchone()
                        context=json.loads(context_row[0]) if context_row and offset else {}

                        stream.seek(offset);waiting_tail=False
                        while not stop() and time.monotonic()<deadline:
                            line=stream.readline(4*1024*1024)
                            if not line:break
                            if not line.endswith(b'\n'):
                                if len(line)<4*1024*1024:waiting_tail=True;break
                                while line and not line.endswith(b'\n'):line=stream.readline(4*1024*1024)
                                offset=stream.tell();continue
                            offset=stream.tell()
                            if not any(k in line for k in (b'session_meta',b'turn_context',b'token_count')):continue
                            try:o=json.loads(line);p=o.get('payload') or {};kind=o.get('type')
                            except (ValueError,AttributeError):continue
                            if not isinstance(p,dict):continue
                            if kind=='session_meta':
                                identity=p.get('id') or p.get('session_id')
                                sid=hashlib.sha256(identity.encode()).hexdigest() if isinstance(identity,str) and identity and len(identity)<256 else ''
                                model=model_name(p.get('model')) or model
                            elif kind=='turn_context':
                                model=model_name(p.get('model')) or model
                                from quota_workload import context as workload_context
                                workload_context(context,p)
                            elif kind=='event_msg' and p.get('type')=='token_count' and sid:
                                info=p.get('info') or {};usage=info.get('total_token_usage') if isinstance(info,dict) else None
                                if not isinstance(usage,dict):continue
                                a=counter(usage.get('input_tokens'));b=counter(usage.get('output_tokens'));total=counter(usage.get('total_tokens'))
                                if total is None and a is not None and b is not None:total=a+b
                                stamp=stamp_of(o)
                                if total is None or total==0 or total>=2**60 or stamp is None:continue
                                current=model_name(p.get('model')) or model_name(info.get('model')) or model
                                from quota_workload import event_context
                                event_context(context,current,p,info)
                                cached=counter(usage.get('cached_input_tokens'))
                                cached=cached if cached is not None and a is not None and cached<=a else None
                                db.execute('''INSERT INTO records(session,total,stamp,model,input,output,cached,speed,effort) VALUES(?,?,?,?,?,?,?,?,?)
                                    ON CONFLICT(session,total) DO UPDATE SET cached=COALESCE(records.cached,excluded.cached),speed=CASE WHEN COALESCE(records.speed,'')='' THEN excluded.speed ELSE records.speed END,
                                    effort=CASE WHEN COALESCE(records.effort,'')='' THEN excluded.effort ELSE records.effort END''',(sid,total,stamp,current,a,b,cached,context.get('speed',''),context.get('effort','')));count+=1
                        db.execute('INSERT OR REPLACE INTO scan_context VALUES(?,?)',(str(path),json.dumps(context)))
                        more|=offset<size and not waiting_tail
                        db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)',(str(path),offset,sid,model,signature,stat.st_mtime_ns,stat.st_ino))
                except (OSError,ValueError,TypeError):errors+=1
        return dict(more=more,errors=errors+self.catalog.errors,observations=count)
    def batch(self,target,limit=1000,v2=False):
        with closing(self.connect()) as db:
            cursor=db.execute('SELECT seq FROM cursors WHERE target=?',(target,)).fetchone()
            fields=('seq','session','total','stamp','model','input','output')+(('cached','speed','effort') if v2 else ())
            rows=db.execute('SELECT '+','.join(fields)+' FROM records WHERE seq>? ORDER BY seq LIMIT ?',(cursor[0] if cursor else 0,limit)).fetchall()
        return [dict(zip(fields,row)) for row in rows]
    def acknowledge(self,target,seq):
        with closing(self.connect()) as db,db:
            db.execute('INSERT INTO cursors VALUES(?,?) ON CONFLICT(target) DO UPDATE SET seq=MAX(seq,excluded.seq)',(target,seq))
