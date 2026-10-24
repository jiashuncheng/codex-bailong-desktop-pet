"""Paths and process identity shared by the macOS source edition."""
import hashlib
import os
import sys
from pathlib import Path

if sys.platform == 'darwin':
    os.environ.setdefault('QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM', '1')

ROOT = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
MAC_VERSION = '0.1.2'


def data_dir():
    override = os.environ.get('BAILONG_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    # Retain the original isolation convention for existing regression tests.
    if os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'BailongEnhanced'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/BailongMac'
    return Path.home() / '.local/share/BailongMac'


def server_name():
    if sys.platform=='win32':return 'bailong-enhanced-local-v1'
    identity = hashlib.sha256(str(data_dir().resolve()).encode()).hexdigest()[:16]
    return 'bailong-mac-' + str(os.getuid()) + '-' + identity


def python_command():
    python = ROOT / ('.venv/Scripts/python.exe' if sys.platform=='win32' else '.venv/bin/python')
    return [str(python if python.exists() else Path(sys.executable)), str(ROOT / 'run_source.py')]
