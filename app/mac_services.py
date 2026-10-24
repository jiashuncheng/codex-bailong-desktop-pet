"""macOS application discovery, LaunchAgent preferences, and Keychain secrets."""
import hashlib
import os
import plistlib
import subprocess
from pathlib import Path
from platform_support import ROOT, data_dir

LABEL = 'local.bailong.mac.source'
KEYCHAIN_SERVICE = 'local.bailong.mac.chat'


def codex_apps():
    roots = [Path('/Applications'), Path.home() / 'Applications']
    override = os.environ.get('BAILONG_CODEX_APP')
    candidates = ([Path(override).expanduser()] if override else [])
    candidates += [base / name for base in roots for name in ('Codex.app', 'ChatGPT.app')]
    return [p for p in candidates if p.is_dir()]


def codex_cli_candidates():
    for app in codex_apps():
        resources = app / 'Contents/Resources'
        for relative in ('codex', 'codex-cli/bin/codex', 'codex-cli/codex-path/codex',
                         'codex-cli/CodexCLI.app/Contents/MacOS/codex'):
            path = resources / relative
            if path.is_file() and os.access(path, os.X_OK):
                yield path


def codex_desktop_open():
    from AppKit import NSWorkspace
    import objc
    with objc.autorelease_pool():
        return any(str(app.bundleIdentifier() or '') in ('com.openai.codex', 'com.openai.chat')
                   for app in NSWorkspace.sharedWorkspace().runningApplications())


def open_codex(session=None):
    if session is not None:
        from desktop_services import codex_conversation_url
        target = codex_conversation_url(session)
        args = ['/usr/bin/open', target]
    else:
        apps = codex_apps()
        if not apps:
            raise OSError('未找到 Codex / ChatGPT 应用，请先安装并打开 Codex。')
        args = ['/usr/bin/open', '-a', str(apps[0])]
    try:
        result = subprocess.run(args, capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        raise OSError('唤起 Codex 超时，请稍后重试。') from None
    if result.returncode:
        raise OSError('无法打开 Codex 会话，请确认此 Mac 的 Codex 支持会话链接。')


def launch_agent_path():
    return Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')


def launch_agent():
    python = ROOT / '.venv/bin/python'
    return dict(Label=LABEL, ProgramArguments=[str(python), str(ROOT / 'launch.py'), 'start', '--autostart'],
                WorkingDirectory=str(ROOT), RunAtLoad=True, ProcessType='Interactive',
                EnvironmentVariables=dict(BAILONG_DATA_DIR=str(data_dir())),
                StandardOutPath=str(data_dir() / 'autostart.log'),
                StandardErrorPath=str(data_dir() / 'autostart-error.log'))


def autostart_enabled():
    try:
        saved = plistlib.loads(launch_agent_path().read_bytes())
        return saved.get('ProgramArguments') == launch_agent()['ProgramArguments']
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def set_autostart(enabled):
    path = launch_agent_path()
    domain = 'gui/' + str(os.getuid())
    target = domain + '/' + LABEL
    subprocess.run(['/bin/launchctl', 'bootout', target], capture_output=True, timeout=10)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(plistlib.dumps(launch_agent()))
    temp.chmod(0o600)
    temp.replace(path)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], capture_output=True, timeout=10)
    if result.returncode:
        path.unlink(missing_ok=True)
        raise OSError('登录启动注册失败，请确认当前用户有权写入 LaunchAgents。')
    subprocess.run(['/bin/launchctl', 'enable', target], capture_output=True, timeout=10)


def secret_account(path, name):
    # Stable while source updates or moves; credentials belong to the data folder.
    return hashlib.sha256((str(Path(path).resolve()) + '\0' + name).encode()).hexdigest()


def keychain_get(account):
    import Security as S
    query = {S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: KEYCHAIN_SERVICE,
             S.kSecAttrAccount: account, S.kSecReturnData: True, S.kSecMatchLimit: S.kSecMatchLimitOne}
    status, value = S.SecItemCopyMatching(query, None)
    if status == S.errSecItemNotFound:
        return ''
    if status != S.errSecSuccess:
        raise OSError('无法读取 macOS 钥匙串（错误码 ' + str(status) + '）。')
    return bytes(value).decode('utf-8')


def keychain_put(account, value):
    import Security as S
    query = {S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: KEYCHAIN_SERVICE,
             S.kSecAttrAccount: account}
    if not value:
        status = S.SecItemDelete(query)
    else:
        attributes = {S.kSecValueData: value.encode('utf-8')}
        status = S.SecItemUpdate(query, attributes)
        if status == S.errSecItemNotFound:
            status, _ = S.SecItemAdd(query | attributes, None)
    if status not in (S.errSecSuccess, S.errSecItemNotFound):
        raise OSError('无法保存 macOS 钥匙串（错误码 ' + str(status) + '）。')
