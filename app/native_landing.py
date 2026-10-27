"""Synchronously publish an existing handoff raster to our layered HWND.

QWidget.repaint() before the first platform Expose can be a no-op. DwmFlush
does not deliver that Qt event. This uses the already prepared premultiplied
raster, without a nested event loop or a second animation clock.
"""
import ctypes,sys
from ctypes import wintypes as w
from functools import lru_cache
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

class Header(ctypes.Structure):
    _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),
              ('compression',w.DWORD),('image_size',w.DWORD),('x',w.LONG),('y',w.LONG),('used',w.DWORD),('important',w.DWORD)]
class BitmapInfo(ctypes.Structure):
    _fields_=[('header',Header),('colors',w.DWORD*1)]
class Blend(ctypes.Structure):
    _fields_=[('op',w.BYTE),('flags',w.BYTE),('alpha',w.BYTE),('format',w.BYTE)]

@lru_cache(maxsize=1)
def api():
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    user.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)];user.GetClientRect.restype=w.BOOL
    user.UpdateLayeredWindow.argtypes=[w.HWND,w.HDC,ctypes.POINTER(w.POINT),ctypes.POINTER(w.SIZE),w.HDC,
        ctypes.POINTER(w.POINT),w.DWORD,ctypes.POINTER(Blend),w.DWORD]
    user.UpdateLayeredWindow.restype=w.BOOL
    gdi.CreateCompatibleDC.argtypes=[w.HDC];gdi.CreateCompatibleDC.restype=w.HDC
    gdi.CreateDIBSection.argtypes=[w.HDC,ctypes.POINTER(BitmapInfo),w.UINT,ctypes.POINTER(ctypes.c_void_p),w.HANDLE,w.DWORD]
    gdi.CreateDIBSection.restype=w.HBITMAP
    gdi.SelectObject.argtypes=[w.HDC,w.HANDLE];gdi.SelectObject.restype=w.HANDLE
    gdi.DeleteObject.argtypes=[w.HANDLE];gdi.DeleteObject.restype=w.BOOL
    gdi.DeleteDC.argtypes=[w.HDC];gdi.DeleteDC.restype=w.BOOL
    return user,gdi

def publish(widget,pixmap):
    if sys.platform!='win32' or QApplication.platformName()!='windows':return False
    user,gdi=api();hwnd=int(widget.winId())
    if pixmap is None:
        rect=w.RECT()
        if not user.GetClientRect(hwnd,ctypes.byref(rect)):raise ctypes.WinError(ctypes.get_last_error())
        image=QImage(max(1,rect.right),max(1,rect.bottom),QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
    else:image=pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():return False
    width,height=image.width(),image.height()
    info=BitmapInfo(Header(40,width,-height,1,32,0,width*height*4,0,0,0,0))
    dc=gdi.CreateCompatibleDC(None)
    if not dc:raise ctypes.WinError(ctypes.get_last_error())
    bitmap=None;previous=None
    try:
        bits=ctypes.c_void_p();bitmap=gdi.CreateDIBSection(dc,ctypes.byref(info),0,ctypes.byref(bits),None,0)
        if not bitmap or not bits.value:raise ctypes.WinError(ctypes.get_last_error())
        previous=gdi.SelectObject(dc,bitmap)
        if previous in (None,0,ctypes.c_void_p(-1).value):
            previous=None;raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(bits.value,bytes(image.constBits()),width*height*4)
        size=w.SIZE(width,height);source=w.POINT(0,0);blend=Blend(0,0,255,1)
        if not user.UpdateLayeredWindow(hwnd,None,None,ctypes.byref(size),dc,ctypes.byref(source),0,ctypes.byref(blend),2):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    finally:
        if previous:gdi.SelectObject(dc,previous)
        if bitmap:gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)
