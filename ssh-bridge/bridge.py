"""Standalone SSH-to-Bailong adapter. The installed pet is never modified."""
import argparse
import signal
import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = {'thinking', 'working', 'responding', 'waiting'}
# Deadlines cover SSH negotiation AND uploading the stdin collector.
STARTUP_TIMEOUT = 12.0
HEARTBEAT_TIMEOUT = 10.0
RETRY_DELAYS = (.5, 1., 2., 5.)
POLL_SECONDS = .2

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def stamp():
    return datetime.now(timezone.utc).isoformat()

class Writer:
    def __init__(self, codex_home, state_dir, host):
        self.root = Path(codex_home)/'archived_sessions'/('bailong-remote-'+host)
        self.state_dir, self.host = Path(state_dir), host
        self.sessions = {}
        self.disconnected = False
        self.last_success = None
        self.server = ''
        self.recover_existing()

    def recover_existing(self):
        # After a forced termination, invalidate only this bridge's unfinished
        # status logs before accepting fresh SSH evidence.
        for path in self.root.glob('rollout-remote-*.jsonl'):
            if path.is_symlink() or not path.is_file(): continue
            try:
                with path.open('rb') as stream:
                    header=json.loads(stream.readline(16384))
                    if (header.get('payload') or {}).get('originator')!='BailongSSHBridge': continue
                    stream.seek(max(0,path.stat().st_size-16384))
                    lines=stream.read().splitlines()
                    last=json.loads(lines[-1]) if lines else {}
                p=last.get('payload') or {}
                if p.get('type') not in ('task_complete','task_completed','turn_aborted','task_aborted','turn_cancelled'):
                    self.event(path,'turn_aborted')
            except (OSError,ValueError,IndexError):
                continue

    def emit(self, path, kind, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(dict(timestamp=stamp(), type=kind, payload=payload), ensure_ascii=False)+'\n')

    def event(self, path, typ, **values):
        self.emit(path, 'event_msg', dict(type=typ, **values))

    def apply(self, snapshot):
        if not snapshot or not snapshot.get('available'):
            self.disconnect()
            return
        now = time.monotonic()
        active_count = 0
        seen = set()
        for s in snapshot.get('sessions', [])[:48]:
            if not isinstance(s, dict) or s.get('state') not in ACTIVE | {'complete','interrupted','idle'}: continue
            raw = str(s.get('id', ''))
            if not raw or len(raw) > 100: continue
            sid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'bailong-ssh://'+self.host+'/'+raw))
            seen.add(sid)
            old = self.sessions.get(sid)
            if not old and s['state'] not in ACTIVE: continue
            path = self.root/('rollout-remote-'+sid+'.jsonl')
            new = old is None
            turn = str(s.get('turn',''))[:200]
            title = '['+self.host+'] '+str(s.get('title') or '服务器任务')[:70]
            if new:
                if not path.exists():
                    self.emit(path, 'session_meta', dict(id=sid, source='bailong_ssh_bridge', originator='BailongSSHBridge', remote_host=self.host, remote_session=raw))
                old = dict(path=path, state='idle', turn='', signature=None, emitted=0, title='')
            else:
                path = old['path']
            if s['state'] in ACTIVE:
                active_count += 1
                if old['state'] not in ACTIVE or old['turn'] != turn:
                    self.event(path, 'task_started', turn_id=turn)
                if old['title'] != title or old['turn'] != turn or old['state'] not in ACTIVE:
                    # The pet consumes this title; its usage scanner does not
                    # count response-item user messages or invent token usage.
                    self.emit(path, 'response_item', dict(type='message', role='user', content=[dict(type='input_text', text=title)]))
                    old['signature'] = None
                signature = (s['state'], s.get('activity'), s.get('display'), s.get('summary'))
                if signature != old['signature'] or now-old['emitted'] >= 15:
                    activity = s.get('activity','')
                    if s['state']=='thinking':
                        self.emit(path, 'response_item', dict(type='reasoning', summary=[]))
                    elif activity=='compact':
                        self.event(path, 'compaction_started')
                    elif activity in ('execute','edit','read','research','tool'):
                        name = {'execute':'exec_command','edit':'apply_patch','read':'read_file','research':'web_search','tool':'remote_tool'}[activity]
                        self.emit(path, 'response_item', dict(type='function_call', name=name, call_id='remote-status'))
                    else:
                        text = str(s.get('summary') or s.get('display') or '正在处理任务')[:160]
                        # Public commentary only. No commands, tool results,
                        # reasoning text, credentials or token counters copied.
                        self.emit(path, 'response_item', dict(type='message', role='assistant', phase='final_answer' if s['state']=='responding' else 'commentary', content=[dict(type='output_text', text=text)]))
                    old.update(signature=signature, emitted=now)
            elif old['state'] in ACTIVE | {'offline'}:
                self.event(path, 'task_complete' if s['state']=='complete' and turn==old['turn'] else 'turn_aborted', turn_id=old['turn'])
            old.update(state=s['state'], turn=turn, title=title)
            self.sessions[sid] = old
        for sid, old in self.sessions.items():
            if sid not in seen and old['state'] in ACTIVE:
                self.event(old['path'], 'turn_aborted', turn_id=old['turn'])
                old['state'] = 'interrupted'
        # An offline turn may finish while SSH is down. Reconcile it once.
        for old in self.sessions.values():
            if old['state']=='offline':
                self.event(old['path'], 'turn_aborted', turn_id=old['turn'])
                old['state']='interrupted'
        self.disconnected = False
        self.last_success = stamp()
        self.server = snapshot.get('host','')
        self.status(True, active_count, self.server)

    def status(self, connected, active, server='', reason='', attempt=0, retry_in=0):
        atomic(self.state_dir/'status.json', dict(connected=connected, ssh_host=self.host,
            server=server or self.server, active=active, updated=stamp(), bridge_pid=os.getpid(),
            remote_log_directory=str(self.root), last_success=self.last_success,
            reason=reason, reconnect_attempt=attempt, retry_in=retry_in))

    def disconnect(self, reason='disconnected', attempt=0, retry_in=0):
        if not self.disconnected:
            for old in self.sessions.values():
                if old['state'] in ACTIVE:
                    # Keep the real title and last known operation. Offline is
                    # neither active, awaiting user input, nor a completed task.
                    self.event(old['path'], 'bridge_disconnected', turn_id=old['turn'])
                    old['state'] = 'offline'
            self.disconnected = True
        self.status(False, 0, reason=reason, attempt=attempt, retry_in=retry_in)

class Bridge:
    def __init__(self, host, ssh_config, writer, stop_handle=None, stop_path=None):
        self.host, self.ssh_config, self.writer = host, ssh_config, writer
        self.stop_handle, self.process = stop_handle, None
        self.stop_path=stop_path

    def stopped(self):
        return bool((self.stop_handle and self.stop_handle.is_set()) or (self.stop_path and self.stop_path.exists()))

    def command(self):
        ssh = ('/usr/bin/ssh' if os.name!='nt' else shutil.which('ssh'))
        if not ssh:raise OSError('未找到 OpenSSH 客户端，请先安装系统 SSH 客户端。')
        config_args=['-F',str(self.ssh_config)] if self.ssh_config.is_file() else []
        return [ssh,*config_args,'-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                '-o','ConnectionAttempts=1','-o','ConnectTimeout=8',
                '-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2',self.host,'python3 -u -']

    def close_process(self):
        process=self.process
        if process is None:return
        # OpenSSH ProxyCommand is a child process on Windows; terminate only
        # descendants of this connection so failed retries cannot leak tunnels.
        children=[]
        if os.name=='nt':
            import psutil
            try:children=psutil.Process(process.pid).children(recursive=True)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        if process.poll() is None:
            process.terminate()
            try:process.wait(1)
            except subprocess.TimeoutExpired:process.kill();process.wait(1)
        for child in reversed(children):
            try:child.terminate()
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass

    def run(self, once=False):
        resource = Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'remote_codex_agent.py'
        source = resource.read_bytes()
        args=self.command();attempt=0
        while not self.stopped():
            messages = queue.Queue(maxsize=8);cancelled=threading.Event()
            reason='transport_error';received=False
            try:
                self.process = subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)
                # Negotiation can block stdin.write on Windows. Never upload
                # on the watchdog thread: start the deadline at process launch.
                def receive(process, output, cancel):
                    def publish(obj):
                        while not cancel.is_set():
                            try:output.put(obj,timeout=POLL_SECONDS);return
                            except queue.Full:pass
                    try:
                        process.stdin.write(source);process.stdin.close()
                        for line in iter(process.stdout.readline,b''):
                            if cancel.is_set():break
                            try:
                                obj=json.loads(line)
                                if isinstance(obj,dict) and obj.get('schema')==1:publish(obj)
                            except (ValueError,UnicodeError):pass
                    except (OSError,ValueError):pass
                    finally:
                        publish(None)
                        for stream in (process.stdin,process.stdout):
                            try:stream.close()
                            except (OSError,ValueError):pass
                thread=threading.Thread(target=receive,args=(self.process,messages,cancelled),daemon=True)
                thread.start();last=time.monotonic()
                while not self.stopped():
                    try:obj=messages.get(timeout=POLL_SECONDS)
                    except queue.Empty:
                        if time.monotonic()-last >= (HEARTBEAT_TIMEOUT if received else STARTUP_TIMEOUT):
                            reason='heartbeat_timeout' if received else 'startup_timeout';break
                        if self.process.poll() is not None:reason='ssh_exit';break
                        continue
                    if obj is None:reason='ssh_exit';break
                    if not obj.get('available'):
                        reason='collector_unavailable';break
                    last=time.monotonic();received=True;attempt=0
                    self.writer.apply(obj)
                    if once:return 0
            except (OSError,ValueError):
                reason='transport_error'
            finally:
                cancelled.set();self.close_process()
            if self.stopped():
                self.writer.disconnect(reason='stopped');break
            if once:
                self.writer.disconnect(reason=reason);return 2
            delay=RETRY_DELAYS[min(attempt,len(RETRY_DELAYS)-1)];attempt+=1
            self.writer.disconnect(reason=reason,attempt=attempt,retry_in=delay)
            end=time.monotonic()+delay
            while not self.stopped() and time.monotonic()<end:
                time.sleep(min(POLL_SECONDS,max(0,end-time.monotonic())))
        return 0


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
    from platform_support import data_dir
    from process_lock import process_lock
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--codex-home')
    parser.add_argument('--state-dir')
    args=parser.parse_args()
    config_path=Path(os.environ.get('BAILONG_BRIDGE_CONFIG') or data_dir()/'bridge-config.json')
    config=json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    host=config.get('ssh_host') or 'unconfigured'
    if not isinstance(host,str) or not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in host):
        raise ValueError('Invalid SSH alias')
    state=Path(args.state_dir or data_dir()/'ssh-bridge')
    state.mkdir(parents=True,exist_ok=True)
    pidfile=state/'process.json'
    if args.stop:
        import psutil
        try:
            saved=json.loads(pidfile.read_text());process=psutil.Process(saved['pid'])
            expected=str(Path(__file__).resolve())
            if expected in process.cmdline() and abs(process.create_time()-saved['created'])<.01:
                atomic(state/'stop-request.json',saved)
                try:process.wait(6)
                except psutil.TimeoutExpired:
                    process.terminate()
                    try:process.wait(6)
                    except psutil.TimeoutExpired:raise RuntimeError('SSH 桥接仍在退出，请稍后重试。')
        except (OSError,ValueError,KeyError,psutil.NoSuchProcess,psutil.AccessDenied):pass
        return 0
    if not config.get('enabled') or host=='unconfigured':
        print('SSH 回传未启用，请在桌宠设置 → 连接与数据中配置。')
        return 0
    lock=process_lock(state/'bridge.lock',blocking=False)
    try:lock.__enter__()
    except BlockingIOError:return 0
    stop_path=state/'stop-request.json';stop_path.unlink(missing_ok=True)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    import psutil
    atomic(pidfile,dict(pid=os.getpid(),created=psutil.Process().create_time()))
    from codex_connection import data_home
    home=Path(args.codex_home or config.get('codex_home') or data_home())
    writer=Writer(home,state,host)
    try:
        writer.status(False,0)
        return Bridge(host,Path(config.get('ssh_config') or Path.home()/'.ssh/config'),writer,stop,stop_path).run(args.once)
    except Exception as exc:
        atomic(state/'error.json',dict(error=str(exc),updated=stamp()))
        return 1
    finally:
        pidfile.unlink(missing_ok=True)
        lock.__exit__(None,None,None)

if __name__=='__main__':
    raise SystemExit(main())
