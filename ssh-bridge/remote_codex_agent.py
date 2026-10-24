"""Read-only SSH collector. Runs from stdin using server Python; no installation."""
import json
import os
import re
import socket
import sqlite3
import time
from contextlib import closing
from pathlib import Path

ACTIVE = {'thinking', 'working', 'responding', 'waiting'}

def clean(value, limit=160):
    text = str(value or '')
    text = re.sub(r'<(?:environment_context|INSTRUCTIONS|external_codex_apps_open_page)[\s\S]*?</[^>]+>', '', text)
    text = re.sub(r'```[\s\S]*?```', '[代码]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]+)', '[凭据已隐藏]', text)
    return re.sub(r'\s+', ' ', text).strip()[:limit]

def content(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return clean(' '.join(v.get('text', '') for v in value if isinstance(v, dict)))
    return ''

def operation(name):
    name = str(name).lower()
    if any(v in name for v in ('request_user_input', 'approval')):
        return 'waiting', 'waiting', '等待输入或批准'
    if any(v in name for v in ('apply_patch', 'edit', 'write_file')):
        return 'working', 'edit', '正在编辑文件'
    if any(v in name for v in ('exec_command', 'write_stdin', 'shell', 'terminal', 'commandexecution')):
        return 'working', 'execute', '正在运行命令'
    if any(v in name for v in ('search', 'browse', 'fetch', 'websearch')):
        return 'working', 'research', '正在查找资料'
    if any(v in name for v in ('read', 'list_', 'get_')):
        return 'working', 'read', '正在读取资料'
    return 'working', 'tool', '正在使用工具'

class Collector:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        self.files = {}
        self.live_files = set()
        self.live_checked = 0
        self.process_check_available = False
        self.saved_names = {}

    def live_sessions(self):
        if time.monotonic() - self.live_checked < 15:
            return
        live = set()
        available = False
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit(): continue
            try:
                if proc.stat().st_uid != os.getuid() or (proc/'comm').read_text().strip() != 'codex': continue
                for fd in (proc/'fd').iterdir():
                    try:
                        target = os.readlink(fd)
                        if 'rollout-' in target and target.endswith('.jsonl'): live.add(target)
                    except OSError: pass
                available = True
            except OSError: pass
        self.live_files, self.process_check_available = live, available
        self.live_checked = time.monotonic()

    def apply(self, s, obj):
        p = obj.get('payload') or {}
        if not isinstance(p, dict):
            return
        kind, typ = obj.get('type'), p.get('type')
        if kind == 'turn_context' and p.get('turn_id'):
            s['turn'] = str(p['turn_id'])
        if kind == 'event_msg' and typ in ('task_started', 'turn_started'):
            s.update(state='thinking', activity='thinking', display='正在思考', summary='', turn=str(p.get('turn_id') or obj.get('timestamp') or s['turn']))
        elif kind == 'event_msg' and typ == 'user_message':
            s['title'] = clean(p.get('message'), 80) or s['title']
            s.update(state='thinking', activity='thinking', display='正在思考')
        elif kind == 'event_msg' and typ in ('task_complete', 'task_completed'):
            s.update(state='complete', activity='complete', display='任务已完成')
        elif kind == 'event_msg' and typ in ('turn_aborted', 'task_aborted', 'turn_cancelled'):
            s.update(state='interrupted', activity='interrupted', display='任务已中断')
        elif kind == 'event_msg' and typ in ('context_compaction_started', 'compaction_started'):
            s.update(state='working', activity='compact', display='正在压缩上下文')
        elif kind == 'response_item' and typ == 'reasoning':
            # Only the event type is used; hidden reasoning is never returned.
            s.update(state='thinking', activity='thinking', display='正在思考')
        elif kind == 'response_item' and typ in ('function_call', 'custom_tool_call'):
            state, activity, display = operation(p.get('name', ''))
            s.update(state=state, activity=activity, display=display)
        elif kind == 'response_item' and typ in ('function_call_output', 'custom_tool_call_output'):
            if s['state'] in ACTIVE:
                s.update(state='working', display='工具已返回，继续处理')
        elif kind == 'response_item' and typ == 'message' and p.get('role') == 'assistant':
            text = content(p.get('content'))
            if text:
                final = p.get('phase') in ('final', 'final_answer')
                s.update(state='responding' if final else 'working', activity='reply' if final else 'commentary', display='正在整理回复' if final else '正在处理任务', summary=text)
        elif kind == 'response_item' and typ == 'message' and p.get('role') == 'user':
            s['title'] = content(p.get('content'))[:80] or s['title']
            s.update(state='thinking', activity='thinking', display='正在思考')
        elif kind == 'event_msg' and typ == 'item_completed':
            item = p.get('item') or {}
            if not isinstance(item, dict):
                return
            it = item.get('type')
            if it == 'UserMessage':
                s['title'] = content(item.get('content'))[:80] or s['title']
                s.update(state='thinking', activity='thinking', display='正在思考')
            elif it == 'AgentMessage':
                text = content(item.get('content'))
                if text:
                    final = item.get('phase') in ('final', 'final_answer')
                    s.update(state='responding' if final else 'working', activity='reply' if final else 'commentary', display='正在整理回复' if final else '正在处理任务', summary=text)
            elif it in ('CommandExecution', 'FileChange', 'WebSearch', 'McpToolCall'):
                activity = {'CommandExecution':'execute', 'FileChange':'edit', 'WebSearch':'research', 'McpToolCall':'tool'}[it]
                display = {'execute':'运行了命令', 'edit':'编辑了文件', 'research':'查找了资料', 'tool':'工具已返回'}[activity]
                s.update(state='working', activity=activity, display=display)

    def titles(self):
        explicit, fallback, indexed = {}, {}, {}
        path = self.home / 'state_5.sqlite'
        if path.is_file():
            try:
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as db:
                    columns = {v[1] for v in db.execute('PRAGMA table_info(threads)')}
                    fields = [v for v in ('id', 'name', 'title') if v in columns]
                    if 'id' in fields:
                        for row in db.execute('SELECT '+','.join(fields)+' FROM threads'):
                            record = dict(zip(fields,row));sid=str(record['id'])
                            if str(record.get('name') or '').strip(): explicit[sid]=clean(record['name'],80)
                            if str(record.get('title') or '').strip(): fallback[sid]=clean(record['title'],80)
            except (OSError, sqlite3.Error):
                pass
        index = self.home / 'session_index.jsonl'
        try:
            with index.open('rb') as stream:
                offset=max(0,index.stat().st_size-4*1024*1024);stream.seek(offset)
                if offset: stream.readline()
                for line in stream:
                    try:
                        row=json.loads(line)
                        sid=str(row.get('id') or row.get('session_id') or '')
                        name=row.get('thread_name') or row.get('name')
                        if sid and isinstance(name,str) and name.strip(): indexed[sid]=clean(name,80)
                    except (ValueError,AttributeError): pass
        except OSError: pass
        self.saved_names.update(fallback)
        self.saved_names.update(indexed)
        self.saved_names.update(explicit)
        return dict(self.saved_names)

    def snapshot(self):
        now = time.time()
        self.live_sessions()
        candidates = []
        for path in (self.home / 'sessions').rglob('rollout-*.jsonl'):
            try:
                st = path.stat()
                if now - st.st_mtime < 86400 or str(path) in self.files:
                    candidates.append((st.st_mtime, path, st))
            except OSError:
                pass
        names = self.titles()
        sessions = []
        for modified, path, st in sorted(candidates, reverse=True)[:48]:
            key = str(path)
            try:
                if key not in self.files:
                    with path.open('rb') as stream:
                        meta = json.loads(stream.readline(1024 * 1024)).get('payload', {})
                    source = meta.get('source')
                    if isinstance(source, str):
                        try: source = json.loads(source)
                        except ValueError: pass
                    if source == 'subagent' or isinstance(source, dict) and 'subagent' in source or meta.get('agent_path') not in (None, '', '/root'):
                        continue
                    sid = str(meta.get('id') or path.stem[-36:])
                    start = max(0, st.st_size - 1024 * 1024)
                    self.files[key] = dict(offset=start, buffer=b'', skip=bool(start), state=dict(id=sid, title=names.get(sid) or '服务器任务 ' + sid[-6:], turn='restored-'+sid, state='idle', activity='', display='等待任务', summary=''))
                f = self.files[key]
                if st.st_size < f['offset']:
                    f.update(offset=0, buffer=b'', skip=False)
                with path.open('rb') as stream:
                    stream.seek(f['offset'])
                    raw = stream.read(4 * 1024 * 1024)
                    f['offset'] = stream.tell()
                lines = (f['buffer'] + raw).split(b'\n')
                f['buffer'] = lines.pop()
                if len(f['buffer']) > 4 * 1024 * 1024:
                    f['buffer'] = b''; f['skip'] = True
                if f['skip'] and lines:
                    lines.pop(0); f['skip'] = False
                for line in lines:
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict): self.apply(f['state'], obj)
                    except (ValueError, AttributeError, TypeError):
                        pass
                s = dict(f['state'], updated=modified)
                s['title'] = names.get(s['id']) or s['title']
                if s['state'] in ACTIVE and self.process_check_available and key not in self.live_files and now-modified > 90:
                    s.update(state='interrupted', display='进程已退出，状态待确认', summary='')
                if s['state'] in ACTIVE or now - modified < 900:
                    sessions.append(s)
            except (OSError, ValueError, AttributeError):
                continue
        return dict(schema=1, host=socket.gethostname(), timestamp=now, sessions=sessions, available=(self.home / 'sessions').is_dir())

def main():
    collector = Collector()
    while True:
        print(json.dumps(collector.snapshot(), ensure_ascii=False), flush=True)
        time.sleep(3)

if __name__ == '__main__':
    main()
