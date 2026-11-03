"""Ordering corrects siblings only; no activation or global topmost changes."""
import sys,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from window_layers import windows_below,mac_below


class LayerTests(unittest.TestCase):
    def test_windows_moves_lower_behind_upper_without_activation(self):
        api=SimpleNamespace(GetWindow=Mock(side_effect=[99,10]),SetWindowPos=Mock())
        windows_below(10,20,api)
        api.SetWindowPos.assert_called_once_with(10,20,0,0,0,0,0x213)
    def test_windows_does_not_reorder_already_correct_windows(self):
        api=SimpleNamespace(GetWindow=Mock(side_effect=[99,0]),SetWindowPos=Mock())
        windows_below(10,20,api);api.SetWindowPos.assert_not_called()
    def test_mac_only_moves_the_lower_window_relative_to_our_upper(self):
        a=SimpleNamespace(windowNumber=lambda:10,orderWindow_relativeTo_=Mock())
        b=SimpleNamespace(windowNumber=lambda:20,orderWindow_relativeTo_=Mock())
        framework=SimpleNamespace(NSWindowBelow=-1,NSWindowAbove=1)
        quartz=SimpleNamespace(kCGWindowListOptionOnScreenOnly=1,kCGNullWindowID=0,
            CGWindowListCopyWindowInfo=Mock(return_value=[{'kCGWindowNumber':10},{'kCGWindowNumber':20}]))
        with patch.dict(sys.modules,{'AppKit':framework,'Quartz':quartz}),patch('mac_native.native_window',side_effect=[a,b]):
            mac_below(object(),object())
        a.orderWindow_relativeTo_.assert_called_once_with(-1,20);b.orderWindow_relativeTo_.assert_not_called()
        quartz.CGWindowListCopyWindowInfo.return_value=[{'kCGWindowNumber':20},{'kCGWindowNumber':10}];a.orderWindow_relativeTo_.reset_mock()
        with patch.dict(sys.modules,{'AppKit':framework,'Quartz':quartz}),patch('mac_native.native_window',side_effect=[a,b]):mac_below(object(),object())
        a.orderWindow_relativeTo_.assert_not_called()
    def test_new_mac_panel_is_presented_relative_to_its_host_without_activation(self):
        a=SimpleNamespace(windowNumber=lambda:10,orderWindow_relativeTo_=Mock())
        b=SimpleNamespace(windowNumber=lambda:20,isVisible=lambda:True,orderWindow_relativeTo_=Mock())
        framework=SimpleNamespace(NSWindowBelow=-1,NSWindowAbove=1)
        quartz=SimpleNamespace(kCGWindowListOptionOnScreenOnly=1,kCGNullWindowID=0,
            CGWindowListCopyWindowInfo=lambda *args:[{'kCGWindowNumber':10}])
        with patch.dict(sys.modules,{'AppKit':framework,'Quartz':quartz}),patch('mac_native.native_window',side_effect=[a,b]):mac_below(object(),object())
        b.orderWindow_relativeTo_.assert_called_once_with(1,10)
        a.orderWindow_relativeTo_.assert_not_called()
    def test_mac_top_level_matches_qt_without_changing_keyboard_policy(self):
        from mac_native import set_level
        window=Mock();window.level.return_value=3
        framework=SimpleNamespace(NSModalPanelWindowLevel=8,NSNormalWindowLevel=0)
        with patch.dict(sys.modules,{'AppKit':framework}),patch('mac_native.native_window',return_value=window):set_level(object(),True)
        window.setLevel_.assert_called_once_with(8)
        window.makeKeyWindow.assert_not_called();window.makeKeyAndOrderFront_.assert_not_called()
