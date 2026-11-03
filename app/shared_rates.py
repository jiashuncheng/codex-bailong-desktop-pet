"""Small, expiring output-rate observations; stable session IDs prevent double counting."""
import math,time

def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS shared_rates(device TEXT,session TEXT,stamp REAL,rate REAL,interval REAL,expires REAL,name TEXT,PRIMARY KEY(device,session))')

def validate(rows,now):
    from shared_sync_store import identity,public_text
    if not isinstance(rows,list) or len(rows)>128:raise ValueError('invalid rates')
    result=[];seen=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'session','sampled_at','rate','interval','expires','name'}:raise ValueError('invalid rate fields')
        sid=identity(r['session'])
        if sid in seen:raise ValueError('duplicate rate')
        seen.add(sid)
        stamp,rate,interval,expires=(r[k] for k in ('sampled_at','rate','interval','expires'))
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (stamp,rate,interval,expires)):raise ValueError('invalid rate number')
        if not 0<=rate<1e9 or not .1<=interval<=300 or not now-300<=stamp<=now+5 or not stamp<=expires<=stamp+180:raise ValueError('invalid rate interval')
        if expires>now:result.append((sid,stamp,rate,interval,expires,public_text(r['name'],160)))
    return result

def replace(db,device,rows):
    old=db.execute('SELECT session,stamp,rate,interval,expires,name FROM shared_rates WHERE device=? ORDER BY session',(device,)).fetchall()
    if sorted(rows)==old:return False
    db.execute('DELETE FROM shared_rates WHERE device=?',(device,))
    db.executemany('INSERT INTO shared_rates VALUES(?,?,?,?,?,?,?)',[(device,*r) for r in rows]);return True

def snapshot(db,now):
    rows=db.execute('''SELECT r.session,r.stamp,r.rate,r.interval,r.expires,r.name,coalesce(nullif(d.label,''),d.origin) FROM shared_rates r
        JOIN shared_devices d ON d.device=r.device WHERE r.expires>? AND d.ready=1 AND d.seen>? ORDER BY r.stamp DESC,r.device''',(now,now-90)).fetchall()
    unique={}
    for sid,stamp,rate,interval,expires,name,origin in rows:
        if sid not in unique:unique[sid]=dict(session=sid,sampled_at=stamp,rate=rate,interval=interval,expires_at=expires,name=name,source_label=origin,waiting=now-stamp>12)
    details=list(unique.values())
    return dict(scope='all',metric='observed_output',rate=sum(r['rate'] for r in details) if details else None,sessions=len(details),details=details)

def wire(value,now=None):
    from shared_state import wire_id,public
    now=time.time() if now is None else now;mono=time.monotonic();rows=[]
    for r in value.get('details',[]):
        stamp=r.get('sampled_at');interval=r.get('interval');expires=r.get('expires');rate=r.get('rate')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (stamp,interval,expires,rate)):continue
        # Wall-clock expiry follows the source sample, never receipt/replay time.
        deadline=stamp+max(12.,min(180.,interval*2.5))
        if deadline<=now or expires<=mono:continue
        rows.append(dict(session=wire_id(r['session']),sampled_at=stamp,rate=rate,interval=interval,expires=deadline,name=public(r.get('name',''),160)))
    return rows

def local(value):
    from conversation_sources import source_title
    now=time.time();mono=time.monotonic();details=[]
    for r in value.get('details',[]):
        if r['expires_at']>now:details.append(dict(r,expires=mono+r['expires_at']-now,name=source_title(r.get('name') or '会话',r.get('source_label',''))))
    return dict(value,details=details,rate=sum(r['rate'] for r in details) if details else None,sessions=len(details),expires=min((r['expires'] for r in details),default=None))
