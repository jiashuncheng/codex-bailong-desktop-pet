"""Read-only adapter for versioned desktop unread metadata; no UI guessing."""
import json,re,sqlite3,time
from pathlib import Path
from contextlib import closing

def session_id(value):
    text=str(value);match=re.search(r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$',text)
    return match.group(1).lower() if match else text


def is_subagent_metadata(metadata):
    source=metadata.get('source')
    if isinstance(source,str):
        try:source=json.loads(source)
        except (ValueError,TypeError):pass
    agent=metadata.get('agent_path')
    return (isinstance(source,dict) and 'subagent' in source) or source=='subagent' or (isinstance(agent,str) and bool(agent.strip()) and agent.strip()!='/root')


def subagent_sessions(home,ids):
    """Identify only proven child threads; missing metadata never hides a chat."""
    ids=list(dict.fromkeys(session_id(sid) for sid in ids if sid))
    if not ids:return set()
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            columns={row[1] for row in db.execute('PRAGMA table_info(threads)')}
            fields=[key for key in ('id','source','agent_path') if key in columns]
            if 'id' not in fields or len(fields)<2:return set()
            found=set()
            for start in range(0,len(ids),128):
                chunk=ids[start:start+128];rows=db.execute('SELECT '+','.join(fields)+' FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                found.update(row[0] for row in rows if is_subagent_metadata(dict(zip(fields,row))))
            return found
    except (OSError,sqlite3.Error,ValueError):return set()


_bridge_name_cache={}

def bridge_conversation_names(home,ids):
    """Recover SSH titles from append-only bridge logs, even after restart.

    Cache the last complete record offset so growing logs are read incrementally.
    Only the bridge's own metadata and title records are eligible.
    """
    found={};root=Path(home)/'archived_sessions'
    ids=[sid for sid in ids if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',sid)]
    if not ids:return found
    try:folders=[p for p in root.glob('bailong-remote-*') if p.is_dir() and not p.is_symlink()]
    except OSError:return found
    for folder in folders:
        for sid in ids:
            if sid in found:continue
            path=folder/('rollout-remote-'+sid+'.jsonl')
            try:
                if path.is_symlink():continue
                with path.open('rb') as stream:
                    header_line=stream.readline(16384)
                    header=json.loads(header_line);meta=header.get('payload') or {}
                    if header.get('type')!='session_meta' or meta.get('originator')!='BailongSSHBridge' or meta.get('id')!=sid:continue
                    host=meta.get('remote_host')
                    if not isinstance(host,str) or folder.name!='bailong-remote-'+host:continue
                    prefix='['+host+'] '
                    stat=path.stat();signature=(stat.st_ino,stat.st_size,stat.st_mtime_ns)
                    old=_bridge_name_cache.get(str(path))
                    title='';offset=stream.tell()
                    if old and old['header']==header_line and old['signature']==signature:
                        if old['title']:found[sid]=old['title']
                        continue
                    if old and old['header']==header_line and old['signature'][0]==stat.st_ino and old['signature'][1]<stat.st_size:
                        title=old['title'];offset=old['offset'];stream.seek(offset)
                    while True:
                        line=stream.readline()
                        if not line or not line.endswith(b'\n'):break
                        offset=stream.tell()
                        try:
                            record=json.loads(line);value=record.get('payload') or {}
                            if record.get('type')!='response_item' or value.get('type')!='message' or value.get('role')!='user':continue
                            content=value.get('content')
                            if not isinstance(content,list):continue
                            candidate=' '.join(item.get('text','') for item in content if isinstance(item,dict) and item.get('type')=='input_text' and isinstance(item.get('text'),str)).strip()
                            if candidate.startswith(prefix) and candidate[len(prefix):].strip():title=re.sub(r'\s+',' ',candidate)[:200]
                        except (ValueError,TypeError,AttributeError):continue
                if len(_bridge_name_cache)>=256:_bridge_name_cache.pop(next(iter(_bridge_name_cache)))
                _bridge_name_cache[str(path)]=dict(header=header_line,signature=signature,title=title,offset=offset)
                if title:found[sid]=title
            except (OSError,ValueError,TypeError,AttributeError):continue
    return found


def conversation_names(home,ids):
    """Prefer desktop names; restore missing SSH names from bridge logs."""
    ids=list(dict.fromkeys(session_id(sid) for sid in ids if sid))
    if not ids:return {}
    found={}
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            for start in range(0,len(ids),128):
                chunk=ids[start:start+128];rows=db.execute('SELECT id,name,title FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                found.update({sid:(name or title).strip() for sid,name,title in rows if (name or title or '').strip()})
    except (OSError,sqlite3.Error,ValueError):pass
    found.update(bridge_conversation_names(home,[sid for sid in ids if sid not in found]))
    return found

def read_unread_sessions(home):
    try:
        root=json.loads((Path(home)/'.codex-global-state.json').read_text(encoding='utf-8'))
        data=root.get('electron-thread-read-state-v1') if isinstance(root,dict) else None
        if not isinstance(data,dict) or data.get('version')!=1:return None
        groups=data.get('unreadByIdentity')
        if not isinstance(groups,dict):return None
        found=False;unread=set()
        for hosts in groups.values():
            if not isinstance(hosts,dict):return None
            for host,ids in hosts.items():
                if not host.startswith('local:'):continue
                if not isinstance(ids,list) or not all(isinstance(x,str) for x in ids):return None
                found=True;unread.update(session_id(x) for x in ids)
        return unread if found else None
    except (OSError,ValueError,UnicodeError):return None

def read_tracking_probe(home):
    """Verify current marker shape and an actual read-only publication query."""
    from connection_health import sample
    home=Path(home)
    if read_unread_sessions(home) is None:
        return sample('unavailable','read_schema' if (home/'.codex-global-state.json').exists() else 'read_missing')
    busy=False
    for filename,table,columns in [('state_5.sqlite','thread_read_receipts',('thread_id','last_published_turn')),
                                   ('thread_history_1.sqlite','thread_turns',('thread_id','turn_id','status','rollout_ordinal'))]:
        if not (home/filename).is_file():continue
        try:
            with closing(sqlite3.connect((home/filename).as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                db.execute('SELECT '+','.join(columns)+' FROM '+table+' LIMIT 1').fetchone()
            return sample('available','ok',time.time())
        except sqlite3.OperationalError as error:busy=busy or 'locked' in str(error).lower() or 'busy' in str(error).lower()
        except (OSError,sqlite3.Error):pass
    return sample('degraded' if busy else 'unavailable','database_busy' if busy else 'read_schema')

def seen_completed_turns(home,pending):
    if not pending:return []
    home=Path(home);unread=read_unread_sessions(home)
    if unread is None:return []
    keys=[(session_id(s),str(t)) for s,t in pending if session_id(s) not in unread and t]
    if not keys:return []
    published={}
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            for start in range(0,len(keys),128):
                chunk=keys[start:start+128];slots=','.join('?' for _ in chunk)
                published.update(db.execute('SELECT thread_id,last_published_turn FROM thread_read_receipts WHERE thread_id IN ('+slots+')',[s for s,t in chunk]))
    except (OSError,sqlite3.Error,ValueError):pass
    accepted={(s,t) for s,t in keys if published.get(s)==t}
    # Paginated desktop history can omit or leave stale thread_read_receipts.
    # Verify the exact pending turn, not just the latest turn: a new task can
    # already be running, or a formerly announced completion can settle as
    # failed/interrupted. Stable thread-level read evidence acknowledges those
    # old terminal notices too. Missing/unfinished/unknown turns stay pending.
    fallback=[(s,t) for s,t in keys if (s,t) not in accepted]
    if fallback:
        try:
            with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                terminal=set()
                for start in range(0,len(fallback),128):
                    chunk=fallback[start:start+128];slots=','.join('(?,?)' for _ in chunk)
                    rows=db.execute("WITH pending(thread_id,turn_id) AS (VALUES "+slots+") SELECT a.thread_id,a.turn_id FROM thread_turns a JOIN pending p ON a.thread_id=p.thread_id AND a.turn_id=p.turn_id WHERE a.status IN ('completed','failed','interrupted')",[value for key in chunk for value in key])
                    terminal.update(rows)
            accepted.update(terminal)
        except (OSError,sqlite3.Error,ValueError):pass
    return [key for key in keys if key in accepted]


class ReadAcknowledgements:
    """Wait for stable read evidence; reset on unread, unknown or a new turn."""
    def __init__(self,settle_seconds=4):self.first_read={};self.settle_seconds=settle_seconds
    def poll(self,home,pending,now=None):
        now=time.monotonic() if now is None else now
        candidates=seen_completed_turns(home,pending)
        self.first_read={key:self.first_read.get(key,now) for key in candidates}
        return [key for key in candidates if now-self.first_read[key]>=self.settle_seconds]

def active_conversations(home):
    home=Path(home)
    try:
        with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            active=db.execute("SELECT thread_id,turn_id FROM thread_turns a WHERE status='inProgress' AND rollout_ordinal=(SELECT MAX(rollout_ordinal) FROM thread_turns b WHERE b.thread_id=a.thread_id)").fetchall()
        with closing(sqlite3.connect((home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            eligible={sid:(name or title) for sid,name,title in db.execute("SELECT id,name,title FROM threads WHERE archived=0 AND (agent_path IS NULL OR agent_path='' OR agent_path='/root') AND (COALESCE(name,'')<>'' OR title<>'' OR has_user_event=1)")}
        excluded=subagent_sessions(home,[sid for sid,turn in active])
        eligible={sid:title for sid,title in eligible.items() if sid not in excluded}
        return [dict(kind='status',session=sid,turn=turn,state='working',title=eligible[sid],text='任务正在进行',active=len([x for x,t in active if x in eligible]),historical_snapshot=True) for sid,turn in active if sid in eligible]
    except (OSError,sqlite3.Error,ValueError):return []
