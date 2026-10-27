"""Silent balloon notifications on the existing Qt tray icon, never a second icon."""
import ctypes
import os
from ctypes import wintypes as w


class GUID(ctypes.Structure):
    _fields_=[('a',w.DWORD),('b',w.WORD),('c',w.WORD),('d',ctypes.c_ubyte*8)]


class NotifyData(ctypes.Structure):
    _fields_=[('cbSize',w.DWORD),('hWnd',w.HWND),('uID',w.UINT),('uFlags',w.UINT),
              ('uCallbackMessage',w.UINT),('hIcon',w.HICON),('szTip',w.WCHAR*128),
              ('dwState',w.DWORD),('dwStateMask',w.DWORD),('szInfo',w.WCHAR*256),
              ('uTimeout',w.UINT),('szInfoTitle',w.WCHAR*64),('dwInfoFlags',w.DWORD),
              ('guidItem',GUID),('hBalloonIcon',w.HICON)]


def qt_tray_window():
    """Locate only this process's Qt 6 tray receiver (Qt uses icon UID zero)."""
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.EnumWindows.argtypes=[callback,w.LPARAM];user.EnumWindows.restype=w.BOOL
    user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    found=[]
    @callback
    def visit(hwnd,unused):
        pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value!=os.getpid():return True
        name=ctypes.create_unicode_buffer(256);title=ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd,name,len(name));user.GetWindowTextW(hwnd,title,len(title))
        if name.value.endswith('TrayIconMessageWindowClass') and title.value=='QTrayIconMessageWindow':found.append(hwnd)
        return True
    user.EnumWindows(visit,0)
    return found[0] if len(found)==1 else None


class SilentNotifier:
    def __init__(self,hwnd=None):
        self.data=NotifyData()
        self.data.cbSize=ctypes.sizeof(NotifyData)
        self.data.uID=0
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.shell.Shell_NotifyIconW.argtypes=[w.DWORD,ctypes.POINTER(NotifyData)]
        self.shell.Shell_NotifyIconW.restype=w.BOOL

    def show(self,title,text):
        if os.environ.get('BAILONG_ISOLATED')=='1':return False
        hwnd=qt_tray_window()
        if not hwnd:return False
        self.data.hWnd=hwnd
        self.data.uFlags=0x10|0x80  # NIF_INFO | NIF_SHOWTIP; modify Qt's icon only
        self.data.szInfoTitle=title[:63]
        self.data.szInfo=text[:255]
        self.data.dwInfoFlags=0x01|0x10|0x80  # INFO | NOSOUND | RESPECT_QUIET_TIME
        return bool(self.shell.Shell_NotifyIconW(1,ctypes.byref(self.data)))

    def close(self):
        # The Qt tray owns its lifecycle and Explorer restart recovery.
        pass
