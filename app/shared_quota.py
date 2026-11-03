"""Bounded quota backfill through the same HTTPS channel as Token records."""
import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import closing
from quota_history import migrate,import_step,store
from log_catalog import LogCatalog

def upload(state,home,config,token,request,stop=lambda:False,cycle=None):
    key=hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:16]
    path=Path(state)/('shared-quota-'+key+'.sqlite3')
    target=hashlib.sha256((config['url']+'\0'+config['device_id']).encode()).hexdigest()
    with closing(sqlite3.connect(path,timeout=10)) as db,db:
        migrate(db)
        db.execute('CREATE TABLE IF NOT EXISTS sent(target TEXT,stamp REAL,deadline REAL,remaining REAL,payload TEXT,PRIMARY KEY(target,stamp,deadline,remaining))')
        catalog=LogCatalog(home);progress=import_step(db,catalog.discover(check=True),stop,seconds=.6)
        if cycle:store(db,cycle['through'],cycle['reset_at'],cycle['remaining'],'live',cycle.get('plan',''),cycle.get('start') if cycle.get('start_source')=='detected' else None,cycle.get('reset_kind',''))
        rows=db.execute('''SELECT q.stamp,q.deadline,q.remaining,q.plan,q.boundary,q.reset_kind FROM quota_observations q
          LEFT JOIN sent s ON s.target=? AND s.stamp=q.stamp AND s.deadline=q.deadline AND s.remaining=q.remaining
          WHERE s.payload IS NULL OR s.payload!=json_array(q.plan,q.boundary,q.reset_kind) ORDER BY q.stamp LIMIT 1000''',(target,)).fetchall()
        observations=[dict(zip(('stamp','deadline','remaining','plan','boundary','reset_kind'),row)) for row in rows]
        if observations:
            ack=request(config,'/v2/quotas',dict(observations=observations),token)
            if ack.get('accepted')!=len(rows):raise OSError('额度同步回执无效')
            db.executemany('INSERT OR REPLACE INTO sent VALUES(?,?,?,?,json_array(?,?,?))',[(target,r[0],r[1],r[2],r[3],r[4],r[5]) for r in rows])
    return bool(progress['pending'] or progress['errors'] or catalog.errors or len(rows)==1000)
