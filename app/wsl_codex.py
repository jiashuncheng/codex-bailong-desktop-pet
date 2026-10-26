"""Windows host adapter for an explicitly selected WSL Codex installation."""
import hashlib,json,os,re,shutil,subprocess,threading,time
from pathlib import Path,PurePosixPath,PureWindowsPath

class WslError(RuntimeError):pass
_cache={};_lock=threading.Lock()

def executable():
    path=shutil.which('wsl.exe')
    if not path:raise WslError('未找到 WSL，请先安装 WSL 和 Linux 发行版。')
    return path

def decode(raw):
    if isinstance(raw,str):return raw
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16',errors='replace')
    return raw.decode('utf-16-le' if b'\0' in raw else 'utf-8',errors='replace').lstrip('\ufeff')

def distributions(running=False):
    command=[executable(),'--list',*(['--running'] if running else []),'--quiet']
    try:done=subprocess.run(command,capture_output=True,timeout=6,creationflags=0x08000000 if os.name=='nt' else 0)
    except (OSError,subprocess.TimeoutExpired) as error:raise WslError('WSL 检测失败或超时，请先确认发行版能够启动。') from error
    if done.returncode:raise WslError('WSL 尚未安装完成或没有可用发行版。')
    return [line.strip() for line in decode(done.stdout).splitlines() if line.strip()]

def running(distro,force=False):
    # Worker-only probe; no process launch or UNC access belongs in paint/UI paths.
    now=time.monotonic()
    with _lock:cached=_cache.get('running')
    if cached and not force and now-cached[0]<5:return distro.casefold() in cached[1]
    try:names={name.casefold() for name in distributions(True)}
    except WslError:names=set()
    with _lock:_cache['running']=(now,names)
    return distro.casefold() in names

def distro_name(value):
    name=str(value).strip()
    if not name or name.startswith('-') or name in ('.','..') or any(c in name for c in '\\/:\0\r\n'):raise ValueError('请选择有效的 WSL 发行版。')
    return name

def linux_path(value):
    value=str(value)
    if not value.startswith('/') or value.startswith('//') or any(c in value for c in '\\\0\r\n') or '..' in PurePosixPath(value).parts:raise ValueError('WSL 数据目录应为绝对 Linux 路径，例如 /home/user/.codex。')
    return str(PurePosixPath(value))

def unc(distro,home):
    return '\\\\wsl$\\'+distro_name(distro)+linux_path(home).replace('/','\\')

def unc_parts(value):
    path=PureWindowsPath(str(value));parts=path.parts
    if not parts:return None
    match=re.fullmatch(r'\\\\(wsl\$|wsl\.localhost)\\([^\\]+)\\?',parts[0],re.I)
    if not match:return None
    return match[2],'/'+('/'.join(parts[1:]))

def identity(home):
    parsed=unc_parts(home)
    return 'wsl:'+parsed[0].casefold()+':'+parsed[1] if parsed else os.path.normcase(str(Path(home).resolve()))

def base_command(values):
    name=distro_name(values.get('wsl_distro',''))
    user=str(values.get('wsl_user','')).strip()
    if user and (user.startswith('-') or any(c in user for c in '/\\\0\r\n')):raise ValueError('Linux 用户名无效。')
    return [executable(),'--distribution',name,*(['--user',user] if user else []),'--exec']

def verify_share(distro,home):
    """Called on the validation worker, never on GUI startup or paint."""
    shared=Path(unc(distro,home))
    try:
        if not shared.is_dir():raise OSError('WSL share unavailable')
        next(shared.iterdir(),None)
    except OSError as error:raise ValueError('Windows 无法读取该 WSL 数据目录；请检查 WSL 文件共享和 Linux 用户目录权限。') from error

def command(values,*args,require_running=True):
    if require_running and not running(values['wsl_distro'],force=True):raise WslError('所选 WSL 发行版未运行，请先启动后重试。')
    home=linux_path(values['wsl_home']);cli=values.get('wsl_cli') or 'codex'
    if cli.lower().endswith('.exe') or (cli!='codex' and (not cli.startswith('/') or any(c in cli for c in '\\\0\r\n'))):raise WslError('请填写 Linux 内的 Codex CLI 路径。')
    # A login shell supplies Linux proxy/environment settings. User values are
    # positional parameters, never interpolated into shell code or saved secrets.
    script='export CODEX_HOME="$1"; if [ -n "$2" ]; then export PATH="$2"; fi; shift 2; cd "$HOME" || exit 1; exec "$@"'
    return [*base_command(values),'sh','-lc',script,'bailong-cli',home,values.get('wsl_path',''),cli,*args]

PROBE=r'''
data=${1:-${CODEX_HOME:-$HOME/.codex}}
cli=$2
if [ -z "$cli" ] || [ "$cli" = codex ]; then cli=$(command -v codex 2>/dev/null); fi
if [ -z "$cli" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
  . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1
  cli=$(command -v codex 2>/dev/null)
fi
if [ -z "$cli" ]; then
  for candidate in "$HOME"/.local/bin/codex "$HOME"/.npm-global/bin/codex "$HOME"/.codex/bin/codex "$HOME"/.vscode-server/extensions/openai.chatgpt-*/bin/linux-*/codex "$HOME"/.vscode-server-insiders/extensions/openai.chatgpt-*/bin/linux-*/codex; do
    if [ -x "$candidate" ] && [ -f "$candidate" ]; then cli=$candidate; break; fi
  done
fi
if [ -n "$cli" ] && [ "${cli#/}" != "$cli" ]; then PATH="${cli%/*}:$PATH"; fi
printf '\n__BAILONG_USER=%s\n__BAILONG_HOME=%s\n__BAILONG_CLI=%s\n__BAILONG_PATH=%s\n' "$(id -un)" "$data" "$cli" "$PATH"
if [ -d "$data" ] && [ -r "$data" ] && { [ -d "$data/sessions" ] || [ -d "$data/archived_sessions" ] || [ -f "$data/auth.json" ] || [ -f "$data/config.toml" ] || [ -f "$data/state_5.sqlite" ]; }; then printf '__BAILONG_READABLE=1\n'; fi
'''

def validate(values):
    values=dict(values);name=distro_name(values.get('wsl_distro',''))
    names=distributions()
    if name not in names:raise ValueError('未找到所选 WSL 发行版，请刷新发行版列表。')
    home=values.get('wsl_home','').strip();cli=values.get('wsl_cli','').strip()
    if home:linux_path(home)
    env=dict(os.environ);env.pop('CODEX_HOME',None)
    try:
        done=subprocess.run([*base_command(values),'sh','-lc',PROBE,'bailong-probe',home,cli],capture_output=True,env=env,timeout=12,creationflags=0x08000000 if os.name=='nt' else 0)
    except (OSError,subprocess.TimeoutExpired) as error:raise ValueError('WSL 环境检测超时，请先在终端确认发行版能正常启动。') from error
    found={}
    for line in decode(done.stdout).splitlines():
        if line.startswith('__BAILONG_') and '=' in line:
            key,value=line.split('=',1);found[key[10:].lower()]=value
    if done.returncode or found.get('readable')!='1':raise ValueError('WSL 数据目录不存在、不可读或尚无 Codex 记录；请确认路径，或先在 Linux 内使用一次 Codex。')
    values.update(source='wsl',wsl_user=found.get('user',''),wsl_home=linux_path(found.get('home','')),wsl_cli=found.get('cli',''),wsl_path=found.get('path',''))
    if not values['wsl_cli'] or values['wsl_cli'].lower().endswith('.exe'):raise ValueError('未找到 Linux Codex CLI，请在该 WSL 发行版内安装，或填写其 Linux 路径。')
    try:result=subprocess.run(command(values,'--version',require_running=False),capture_output=True,timeout=8,creationflags=0x08000000 if os.name=='nt' else 0)
    except (OSError,subprocess.TimeoutExpired) as error:raise ValueError('WSL 内的 CLI 无法运行；请检查 Node 环境和 CLI 路径。') from error
    if result.returncode or not re.search(r'codex(?:-cli)?\s+\d+\.\d+',decode(result.stdout),re.I):raise ValueError('WSL 内的 CLI 未返回可识别的 Codex 版本。')
    verify_share(name,values['wsl_home'])
    with _lock:_cache.clear()
    return values

def state_dir(default,home):
    parsed=unc_parts(home)
    if not parsed:return Path(default)
    key=hashlib.sha256(identity(home).encode()).hexdigest()[:20]
    root=Path(default)/'wsl-sources'/key;root.mkdir(parents=True,exist_ok=True);return root

class LogOnlyLiveReader:
    connected=False
    def __init__(self,*args,**kwargs):pass
    def start(self):pass
    def set_targets(self,*args):pass
    def join(self,*args):pass
    def health_snapshot(self):return dict(state='degraded',code='wsl_logs_only')
