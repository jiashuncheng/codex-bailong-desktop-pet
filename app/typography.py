"""Bundled Latin numerals and letters, with the existing Chinese fallback."""
import os
import sys
from functools import lru_cache
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase,QGuiApplication

LATIN_FAMILY='Chakra Petch'
FONT_FAMILIES=[LATIN_FAMILY,'PingFang SC','Hiragino Sans GB','Helvetica Neue','sans-serif'] if sys.platform=='darwin' else [LATIN_FAMILY,'Microsoft YaHei UI','Microsoft YaHei','Segoe UI','sans-serif']
FONT_CSS='font-family:'+','.join('"'+name+'"' for name in FONT_FAMILIES)+';font-weight:600;'
ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
FONT_FILE=ROOT/'app/fonts/ChakraPetch-Regular.ttf'
_font_id=None
_font_loaded=False


def register_font():
    global _font_id,_font_loaded
    if _font_id is None and QGuiApplication.instance() is not None:
        # Explicit registration also keeps Chinese fallback available in Qt's
        # offscreen renderer, where system font discovery is unavailable.
        system_fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('msyh.ttc','msyhbd.ttc'):
            if (system_fonts/name).is_file():QFontDatabase.addApplicationFont(str(system_fonts/name))
        if sys.platform=='darwin':
            for path in ('/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Supplemental/Arial Unicode.ttf'):
                if Path(path).is_file():QFontDatabase.addApplicationFont(path)
        _font_id=QFontDatabase.addApplicationFont(str(FONT_FILE))
        _font_loaded=LATIN_FAMILY in QFontDatabase.applicationFontFamilies(_font_id)
    return _font_loaded


def ui_font(px,bold=False):
    register_font()
    return QFont(_font_template(px,bold))


@lru_cache(maxsize=128)
def _font_template(px,bold):
    value=QFont();value.setFamilies(FONT_FAMILIES);value.setPixelSize(px)
    value.setWeight((QFont.Weight.Bold if bold else QFont.Weight.DemiBold) if px<=11 else QFont.Weight.DemiBold if bold else QFont.Weight.Medium)
    value.setStyleStrategy(QFont.StyleStrategy.PreferAntialias|QFont.StyleStrategy.ForceOutline)
    value.setHintingPreference(QFont.HintingPreference.PreferFullHinting if px<=11 else QFont.HintingPreference.PreferNoHinting)
    return value


def install_ui_font(app):
    register_font()
    value=QFont();value.setFamilies(FONT_FAMILIES);value.setPointSize(10)
    app.setFont(value)
