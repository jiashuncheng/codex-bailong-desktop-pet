"""Editor identity shared by the window icon and the desktop shortcut."""
from pathlib import Path
import sys
from PySide6.QtGui import QIcon

APP_ID='Bailong.MaterialEditor'
SHORTCUT_NAME='白龙素材编辑器'
BASE=Path(__file__).resolve().parent

def icon_path():
    names=('bailong-editor-v2.ico','bailong-editor-v2.png','bailong-editor.ico','bailong-editor.png') if sys.platform=='win32' else ('bailong-editor-v2.png','bailong-editor-v2.ico','bailong-editor.png','bailong-editor.ico')
    return next((BASE/'icons'/name for name in names if (BASE/'icons'/name).is_file()),BASE/'icons/bailong-editor.png')

def editor_icon():return QIcon(str(icon_path()))

def configure_native_identity():
    if sys.platform=='win32':
        import ctypes
        # This process has a separate taskbar identity from the desktop pet.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
