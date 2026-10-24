"""Run the editable Mac edition, without a frozen application or installer."""
import os
import sys
from pathlib import Path

if sys.platform == 'darwin':
    os.environ.setdefault('QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM', '1')

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'app'))
os.environ.setdefault('PYTHONUNBUFFERED', '1')
if sys.platform=='darwin':os.environ['PATH'] = os.environ.get('PATH', '/usr/bin:/bin') + ':/opt/homebrew/bin:/usr/local/bin'
if '--check-dependencies' in sys.argv:
    import PySide6, PIL, msgspec, psutil
    if sys.platform=='darwin':import AppKit,Quartz,Security
    raise SystemExit(0)
if sys.platform not in ('darwin','win32') and '--allow-test-platform' not in sys.argv:
    raise SystemExit('此启动入口适用于 Windows 和 macOS。')
import runpy
runpy.run_path(str(root / 'app/enhanced.py'), run_name='__main__')
