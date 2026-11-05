"""Create one identifiable Windows desktop shortcut using the existing runtime."""
from pathlib import Path
import argparse,json,os,subprocess,sys
from config_store import load_config
from branding import APP_ID,SHORTCUT_NAME,icon_path

BASE=Path(__file__).resolve().parent

def quote(value):return "'"+str(value).replace("'","''")+"'"

def install(desktop=None):
    if sys.platform!='win32':raise RuntimeError('此入口创建Windows快捷方式；macOS请使用仓库的素材工作台.command。')
    cfg=load_config(BASE/'配置.json');python=Path(cfg.get('python',sys.executable))
    pythonw=python.with_name('pythonw.exe')
    if not pythonw.is_file():pythonw=Path(sys.executable).with_name('pythonw.exe')
    launcher=BASE/'启动.py';icon=icon_path()
    if not pythonw.is_file() or not launcher.is_file() or not icon.is_file():raise RuntimeError('找不到编辑器启动文件、Python环境或图标，请先准备素材工作台环境。')
    destination=quote(Path(desktop).resolve()) if desktop else "[Environment]::GetFolderPath('Desktop')"
    description='白龙素材编辑器：剪辑、拼接、抠图、大小与位置校准、导出。 ['+APP_ID+']'
    script=f'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$editorDesktop={destination}
if (-not (Test-Path -LiteralPath $editorDesktop -PathType Container)) {{ throw 'Desktop directory does not exist' }}
$editorLinkPath=Join-Path $editorDesktop {quote(SHORTCUT_NAME+'.lnk')}
$editorShell=New-Object -ComObject WScript.Shell
$editorLink=$editorShell.CreateShortcut($editorLinkPath)
if ((Test-Path -LiteralPath $editorLinkPath) -and $editorLink.Description -notlike '*{APP_ID}*') {{ throw 'An unrelated shortcut already uses this name; no file was changed' }}
$editorLink.TargetPath={quote(pythonw)}
$editorLink.Arguments={quote('"'+str(launcher)+'"')}
$editorLink.WorkingDirectory={quote(BASE)}
$editorLink.IconLocation={quote(str(icon)+',0')}
$editorLink.Description={quote(description)}
$editorLink.WindowStyle=1
$editorLink.Save()
$editorVerified=$editorShell.CreateShortcut($editorLinkPath)
@{{shortcut=$editorLinkPath;target=$editorVerified.TargetPath;arguments=$editorVerified.Arguments;workingDirectory=$editorVerified.WorkingDirectory;icon=$editorVerified.IconLocation}} | ConvertTo-Json -Compress
'''
    completed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8-sig',creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
    if completed.returncode:raise RuntimeError(completed.stderr.strip() or '创建快捷方式失败')
    result=json.loads(completed.stdout.strip())
    if Path(result['target']).resolve()!=pythonw.resolve() or result['arguments']!='"'+str(launcher)+'"':raise RuntimeError('快捷方式目标核对失败')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--desktop',type=Path,help='Optional destination for controlled installation checks')
    args=parser.parse_args();print(json.dumps(install(args.desktop),ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())
