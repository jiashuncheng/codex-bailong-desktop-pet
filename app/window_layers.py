"""Repair only the relative order of our own windows, without activation."""
import sys
from PySide6.QtCore import QObject,QEvent,QTimer,Qt
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import isValid


def windows_below(lower,upper,api=None):
    if api is None:
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('user32',use_last_error=True)
        api.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT];api.GetWindow.restype=wintypes.HWND
        api.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    # GW_HWNDPREV walks towards the front. Leave already correct windows alone.
    cursor=upper
    for _ in range(256):
        cursor=api.GetWindow(cursor,3)
        if not cursor:return
        if cursor==lower:
            api.SetWindowPos(lower,upper,0,0,0,0,0x0001|0x0002|0x0010|0x0200)
            return


def mac_below(lower,upper):
    from AppKit import NSWindowBelow,NSWindowAbove
    import Quartz
    from mac_native import native_window
    a,b=native_window(lower),native_window(upper)
    if a is None or b is None:return
    # NSApplication.orderedWindows omits Qt's nonactivating NSPanel windows.
    # WindowServer order includes them; only our two window IDs are used.
    rows=Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,Quartz.kCGNullWindowID) or []
    numbers=[int(w['kCGWindowNumber']) for w in rows]
    an,bn=int(a.windowNumber()),int(b.windowNumber())
    if an in numbers and bn not in numbers and b.isVisible():
        # A newly exposed nonactivating child panel may not yet be in the
        # onscreen order. Present it relative to its own visible host only.
        b.orderWindow_relativeTo_(NSWindowAbove,an)
    elif an in numbers and bn in numbers and numbers.index(an)<numbers.index(bn):
        a.orderWindow_relativeTo_(NSWindowBelow,bn)


class WindowLayers(QObject):
    def __init__(self,pet):
        super().__init__(pet);self.pet=pet;self.busy=False;self.closed=False
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.sync)
        QApplication.instance().installEventFilter(self);self.request()

    def request(self):
        if not self.closed and not self.busy and not self.timer.isActive():self.timer.start(0)

    def shutdown(self):
        self.closed=True;self.timer.stop();QApplication.instance().removeEventFilter(self)

    def apply_flags(self):
        pet=self.pet;b=pet.bubble
        windows=[w for w in (pet,b,getattr(b,'report',None)) if w is not None and isValid(w)]
        visible=[w.isVisible() for w in windows]
        b._changing_window_flags=True
        try:
            for w,shown in zip(windows,visible):
                top=pet.settings['on_top']
                if bool(w.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=top:
                    w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top)
                if w is pet:
                    through=pet.settings.get('mouse_through',False)
                    if bool(w.windowFlags()&Qt.WindowType.WindowTransparentForInput)!=through:
                        w.setWindowFlag(Qt.WindowType.WindowTransparentForInput,through)
                if shown and not w.isVisible():w.show()
        finally:b._changing_window_flags=False
        self.request()

    def eventFilter(self,obj,event):
        if event.type() in (QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.WinIdChange,
                QEvent.Type.WindowActivate,QEvent.Type.ZOrderChange,QEvent.Type.MouseButtonPress):
            if isinstance(obj,QWidget):
                window=obj.window();report=getattr(self.pet.bubble,'report',None)
                if window in (self.pet,self.pet.bubble,report):self.request()
        return False

    def sync(self):
        if self.closed or self.busy or not isValid(self.pet):return
        if QApplication.platformName()=='offscreen' or sys.platform not in ('darwin','win32'):return
        self.busy=True
        try:
            report=getattr(self.pet.bubble,'report',None)
            windows=[w for w in (self.pet,self.pet.bubble,report) if w is not None and isValid(w) and w.isVisible()]
            if sys.platform=='darwin':
                from mac_native import set_level
                top=self.pet.settings.get('on_top',True) and not self.pet._video_yielded
                for w in windows:set_level(w,top)
                for lower,upper in zip(windows,windows[1:]):mac_below(lower,upper)
            else:
                for lower,upper in zip(windows,windows[1:]):windows_below(int(lower.winId()),int(upper.winId()))
        finally:self.busy=False
