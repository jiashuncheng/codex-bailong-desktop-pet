"""Read-only Codex account adapter. No prompts, token generation or resets."""
import json, os, queue, shutil, subprocess, threading, time, sys, ctypes
from pathlib import Path
from datetime import datetime
from version import VERSION

class QuotaFailure(RuntimeError):
    def __init__(self,message,code,phase='request',retryable=False):
        super().__init__(message);self.code=code;self.phase=phase;self.retryable=retryable

def classify_error(message,phase='request'):
    lower=message.lower()
    if any(s in lower for s in ('unauthorized','401','not authenticated','not logged','sign in','please log','token expired')):
        return QuotaFailure('Codex登录状态已失效，请在Codex中重新登录。','authentication',phase)
    if any(s in lower for s in ('error sending request','timed out','timeout','connection','dns','tls','certificate','502','503','504','temporarily')):
        return QuotaFailure('网络连接暂时失败，请检查网络或代理后再试。','network',phase,True)
    return QuotaFailure('额度服务暂未返回结果，请稍后再试。','service',phase)

def log_attempt(attempt,seconds,error=None,log_path=None):
    if log_path is False:return
    # Program directories and shared resources are immutable deployment payloads.
    root=__import__('platform_support').data_dir()
    path=Path(log_path) if log_path else root/'额度查询日志.jsonl'
    event={'time':datetime.now().isoformat(timespec='seconds'),'attempt':attempt,'seconds':round(seconds,3),'result':'success' if error is None else error.code}
    if error:event['phase']=error.phase
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        lines=path.read_text(encoding='utf-8').splitlines()[-199:] if path.exists() else []
        path.write_text('\n'.join(lines+[json.dumps(event,ensure_ascii=False)])+'\n',encoding='utf-8')
    except OSError:pass

def read_quota(timeout=20,cancel=None,attempts=2,log_path=None):
    for attempt in range(1,attempts+1):
        started=time.monotonic()
        try:
            try:result=_read_quota_once(timeout,cancel)
            except OSError:raise QuotaFailure('额度连接暂时中断，请稍后再试。','connection_io','transport',True)
            log_attempt(attempt,time.monotonic()-started,log_path=log_path);return result
        except QuotaFailure as error:
            log_attempt(attempt,time.monotonic()-started,error,log_path)
            if not error.retryable or attempt==attempts or (cancel and cancel.is_set()):raise
            if cancel:
                if cancel.wait(.8):raise QuotaFailure('额度查询已取消','cancelled')
            else:time.sleep(.8)

def find_codex():
    from codex_connection import find_executable
    return find_executable()


def _read_quota_once(timeout=20, cancel=None):
    executable = find_codex()
    from codex_connection import child_environment
    frozen_windows=sys.platform=='win32' and getattr(sys,'frozen',False)
    if frozen_windows:ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        process = subprocess.Popen([executable, 'app-server'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=child_environment(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    finally:
        if frozen_windows:ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
    messages = queue.Queue()
    def receive():
        for line in process.stdout:
            try: messages.put(json.loads(line))
            except ValueError: pass
        messages.put(None)
    threading.Thread(target=receive, daemon=True).start()
    deadline = time.monotonic() + timeout
    def send(message):
        process.stdin.write(json.dumps(message)+'\n'); process.stdin.flush()
    def result(request_id):
        while time.monotonic() < deadline:
            if cancel and cancel.is_set():raise QuotaFailure('额度查询已取消','cancelled')
            try: message = messages.get(timeout=min(.1,max(.01, deadline-time.monotonic())))
            except queue.Empty: continue
            phase='initialize' if request_id==1 else 'rate_limits'
            if message is None: raise QuotaFailure('额度连接暂时中断，请稍后再试。','connection_closed',phase,True)
            if message.get('id') == request_id:
                if 'error' in message: raise classify_error(message['error'].get('message','额度读取失败'),phase)
                return message['result']
        raise QuotaFailure('额度加载超时，请检查网络或代理后再试。','timeout','initialize' if request_id==1 else 'rate_limits',True)
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'bailong_pet','title':'白龙桌宠','version':VERSION}}})
        result(1); send({'method':'initialized'})
        send({'id':2,'method':'account/rateLimits/read'})
        return result(2)
    finally:
        if process.poll() is None: process.terminate()
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired: process.kill();process.wait()
        process.stdin.close();process.stdout.close()

def quota_windows(data,allow_empty=False):
    buckets = data.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or data.get('rateLimits')
    if not bucket: raise RuntimeError('当前账户没有可读取的 Codex 额度。')
    windows=[]
    for key in ('primary','secondary'):
        window=bucket.get(key)
        if not window: continue
        minutes=window.get('windowDurationMins')
        name={300:'5小时',10080:'一周'}.get(minutes, f'{minutes}分钟' if minutes else '额度窗口')
        used=window.get('usedPercent')
        remaining=None if used is None else max(0,min(100,100-float(used)))
        windows.append({'name':name,'remaining':remaining,'resetsAt':window.get('resetsAt')})
    if not windows and not allow_empty: raise RuntimeError('服务器暂未提供额度窗口。')
    return windows
