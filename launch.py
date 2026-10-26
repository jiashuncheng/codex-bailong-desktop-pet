"""Bootstrap dependencies and manage only this source edition's processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import venv

os.environ.setdefault('PYTHONUTF8','1')
os.environ.setdefault('PYTHONIOENCODING','utf-8')
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
from platform_support import data_dir, MAC_VERSION
from process_lock import process_lock

def environment_python():
    return ROOT/('.venv/Scripts/python.exe' if sys.platform=='win32' else '.venv/bin/python')

def background_options():
    return dict(creationflags=0x08000200) if sys.platform=='win32' else dict(start_new_session=True)


def ensure_environment():
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError('需要 Python 3.12 或 3.13。可在 python.org 安装，或设置 BAILONG_PYTHON。')
    python = environment_python()
    if not python.is_file():
        print('正在为本工程创建独立 Python 环境…', flush=True)
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform!='win32').create(ROOT / '.venv')
    requirements = ROOT / 'requirements-source.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    receipt = ROOT / '.venv/.bailong-requirements.sha256'
    valid = receipt.is_file() and receipt.read_text().strip() == digest
    if valid:
        check = subprocess.run([str(python), '-c',
                                'import PySide6,PIL,psutil,msgspec; '+('import AppKit,Quartz,Security' if sys.platform=='darwin' else 'import comtypes')],
                               capture_output=True, timeout=20)
        valid = check.returncode == 0
    if not valid:
        print('正在安装 / 核对本机运行依赖（首次需要联网）…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        '--no-cache-dir', '-r', str(requirements)], check=True)
        receipt.write_text(digest + '\n')
    return python


def read_runtime():
    try:
        return json.loads((data_dir() / 'runtime.json').read_text())
    except (OSError, ValueError):
        return {}


def is_running(state, python):
    pid = state.get('pid')
    if not isinstance(pid, int) or pid <= 1 or not state.get('source_run'):
        return False
    script = ('import json,psutil,sys; '
              'p=psutil.Process(int(sys.argv[1])); '
              'print(json.dumps(p.cmdline()))')
    found = subprocess.run([str(python), '-c', script, str(pid)], capture_output=True, text=True, timeout=5)
    if found.returncode:
        return False
    try:
        return str(ROOT / 'run_source.py') in json.loads(found.stdout)
    except ValueError:
        return False


def stop_pet(python):
    # Graceful, app-owned local socket. Never kill an unverified or reused PID.
    previous=read_runtime().get('pid')
    subprocess.run([str(python), str(ROOT / 'run_source.py'), '--quit'], check=True, timeout=35)
    if not isinstance(previous,int) or previous<=1:return
    # A new checkout can replace an older source directory. Wait for that
    # recorded pet too, so it releases the shared local server before restart.
    wait_script='''import psutil,sys
from pathlib import Path
try:
 p=psutil.Process(int(sys.argv[1]))
 if any(Path(a).name.lower() in ('run_source.py','enhanced.py','bailongenhanced.exe') for a in p.cmdline()):p.wait(25)
except psutil.NoSuchProcess:pass
'''
    subprocess.run([str(python),'-c',wait_script,str(previous)],check=True,timeout=30)


def bridge_config():
    try:
        value = json.loads((data_dir() / 'bridge-config.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def bridge_action(python, stop=False):
    entry = ROOT / 'ssh-bridge/bridge.py'
    if stop:
        subprocess.run([str(python), str(entry), '--stop'], check=True, timeout=10)
        return
    if not bridge_config().get('enabled'):
        return
    logdir = data_dir() / 'logs'
    logdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, BAILONG_BRIDGE_CONFIG=str(data_dir() / 'bridge-config.json'))
    with (logdir / 'ssh-bridge.log').open('a') as output:
        subprocess.Popen([str(python), str(entry)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                         stdout=output, stderr=output, **background_options())


def started_source_is_ready(state, process, python):
    if not state.get('source_run'):
        return False
    # Windows venv python.exe can retain its own PID while the actual Python
    # child writes runtime.json. Verify this project's real source process.
    return state.get('pid') == process.pid or is_running(state, python)


def start_pet(python, autostart=False):
    if autostart and is_running(read_runtime(), python):
        return
    subprocess.run([str(python),str(ROOT/'tools/prepare_source_assets.py')],check=True)
    stop_pet(python)
    bridge_action(python, stop=True)
    bridge_action(python)
    logdir = data_dir() / 'logs'
    logdir.mkdir(parents=True, exist_ok=True)
    with (logdir / 'stdout.log').open('a') as out, (logdir / 'stderr.log').open('a') as err:
        process = subprocess.Popen([str(python), str(ROOT / 'run_source.py')], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   **background_options())
    end = time.monotonic() + 35
    while time.monotonic() < end:
        state = read_runtime()
        if started_source_is_ready(state, process, python):
            print('白龙桌宠源码版已启动。修改源码后，再次双击“一键启动”即可重启生效。')
            print('菜单栏白龙图标可打开设置、找回人物或退出。')
            return
        if process.poll() is not None:
            raise RuntimeError('启动失败，请查看 ' + str(data_dir() / 'error.log') + ' 和 logs/stderr.log。')
        time.sleep(.25)
    raise RuntimeError('进程仍在启动，尚未收到就绪记录。请查看 ' + str(logdir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status', 'setup', 'settings',
                                          'bridge-restart', 'local-hd', 'update', 'check', 'diagnose'), nargs='?', default='start')
    parser.add_argument('--autostart', action='store_true')
    args = parser.parse_args()
    if sys.platform not in ('darwin','win32'):
        raise RuntimeError('请在 Windows 或 macOS 上运行此工程。')
    if args.action in ('stop', 'status') and not environment_python().exists():
        print('尚未安装运行环境，桌宠未运行。')
        return 0
    python = ensure_environment()
    if args.action=='update':
        return subprocess.run([str(python),str(ROOT/'tools/sync_source.py')]).returncode
    if args.action == 'setup':
        print('运行环境已准备好。双击“一键启动.command”即可运行。')
        return 0
    state = data_dir()
    state.mkdir(parents=True, exist_ok=True)
    if sys.platform!='win32':state.chmod(0o700)
    with process_lock(state/'.launcher.lock'):
        if args.action == 'start':
            start_pet(python, args.autostart)
        elif args.action == 'stop':
            stop_pet(python)
            bridge_action(python, stop=True)
            print('桌宠与本工程 SSH 回传已停止。')
        elif args.action == 'status':
            print('正在运行' if is_running(read_runtime(), python) else '未运行')
        elif args.action == 'settings':
            if not is_running(read_runtime(), python):
                start_pet(python)
            subprocess.run([str(python), str(ROOT / 'run_source.py'), '--settings'], check=True)
        elif args.action == 'bridge-restart':
            bridge_action(python, stop=True)
            bridge_action(python)
            print('SSH 配置已应用。连接结果可在桌宠状态区和数据目录 ssh-bridge/status.json 查看。')
        elif args.action == 'local-hd':
            subprocess.run([str(python),str(ROOT/'tools/import_local_hd.py')],check=True)
            start_pet(python)
        elif args.action == 'diagnose':
            subprocess.run([str(python), str(ROOT / 'tools/check_mac.py'), '--connection'], check=True)
        elif args.action == 'check':
            subprocess.run([str(python), str(ROOT / 'tools/check_mac.py')], check=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('操作未完成：' + str(error), file=sys.stderr)
        raise SystemExit(1)
