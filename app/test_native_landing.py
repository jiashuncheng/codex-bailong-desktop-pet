"""Native submission uses premultiplied pixels and releases all GDI handles."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import ctypes,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap,QColor
import native_landing as native

APP=QApplication.instance() or QApplication([])

class NativeLandingTests(unittest.TestCase):
    def setUp(self):
        self.buffer=(ctypes.c_ubyte*16)();self.user=Mock();self.gdi=Mock()
        self.gdi.CreateCompatibleDC.return_value=88;self.gdi.SelectObject.return_value=99
        def dib(dc,info,usage,pointer,section,offset):
            ctypes.cast(pointer,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.addressof(self.buffer)
            return 77
        self.gdi.CreateDIBSection.side_effect=dib;self.user.UpdateLayeredWindow.return_value=True
        self.widget=SimpleNamespace(winId=lambda:123)
        self.image=QPixmap(2,2);self.image.fill(QColor(100,50,20,128))
    def test_sync_submission_publishes_premultiplied_bgra_and_cleans_gdi(self):
        with patch.object(native.QApplication,'platformName',return_value='windows'),patch.object(native,'api',return_value=(self.user,self.gdi)):
            self.assertTrue(native.publish(self.widget,self.image))
        self.assertEqual(list(self.buffer[:4]),[10,25,50,128])
        args=self.user.UpdateLayeredWindow.call_args.args
        self.assertEqual(args[0],123);self.assertEqual(args[-1],2)
        self.assertEqual(args[-2]._obj.alpha,255);self.assertEqual(args[-2]._obj.format,1)
        self.gdi.SelectObject.assert_any_call(88,99);self.gdi.DeleteObject.assert_called_once_with(77);self.gdi.DeleteDC.assert_called_once_with(88)
    def test_submission_failure_still_releases_bitmap_and_dc(self):
        self.user.UpdateLayeredWindow.return_value=False
        with patch.object(native.QApplication,'platformName',return_value='windows'),patch.object(native,'api',return_value=(self.user,self.gdi)):
            with self.assertRaises(OSError):native.publish(self.widget,self.image)
        self.gdi.DeleteObject.assert_called_once_with(77);self.gdi.DeleteDC.assert_called_once_with(88)
    def test_bitmap_allocation_failure_releases_only_the_dc(self):
        self.gdi.CreateDIBSection.side_effect=None;self.gdi.CreateDIBSection.return_value=None
        with patch.object(native.QApplication,'platformName',return_value='windows'),patch.object(native,'api',return_value=(self.user,self.gdi)):
            with self.assertRaises(OSError):native.publish(self.widget,self.image)
        self.gdi.DeleteObject.assert_not_called();self.gdi.DeleteDC.assert_called_once_with(88)
    def test_non_native_environment_does_not_call_win32(self):
        with patch.object(native.QApplication,'platformName',return_value='offscreen'),patch.object(native,'api') as api:
            self.assertFalse(native.publish(self.widget,self.image));api.assert_not_called()

if __name__=='__main__':unittest.main()
