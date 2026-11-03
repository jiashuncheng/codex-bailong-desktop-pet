"""Create our borderless Qt panels without activating the application.

Qt 6.9.2 preserves NonactivatingPanel, but does not add it when constructing
QNSPanel. Supply it to the original initializer, rather than changing an
existing NSPanel's style and assuming WindowServer activation changed too.
Only this process's borderless QNSPanel constructor is adapted. Native file
dialogs, titled panels and QNSWindow are unaffected. Keep the flag for the
window's lifetime; explicit editor navigation activates the app separately.

References: Apple's NSWindow.StyleMask.nonactivatingPanel and Qt 6.9.2's
qcocoawindow.mm (windowStyleMask/createNSWindow), qnswindow.mm (initializer).
"""

_constructor = None
_SELECTOR = b'initWithContentRect:styleMask:backing:defer:screen:platformWindow:'
_SIGNATURE = b'@@:{CGRect={CGPoint=dd}{CGSize=dd}}QQB@^v'


def install_nonactivating_panels():
    """Install once, before constructing the pet or any of its panels.

    This Qt-specific bridge is checked against the pinned source runtime.
    Refuse an unknown ABI instead of risking an invalid native call.
    """
    global _constructor
    if _constructor is not None:
        return
    import objc
    from AppKit import NSWindowStyleMaskNonactivatingPanel, NSWindowStyleMaskTitled
    panel = objc.lookUpClass('QNSPanel')
    initializer = panel.initWithContentRect_styleMask_backing_defer_screen_platformWindow_
    if initializer.signature != _SIGNATURE:
        raise RuntimeError('Unsupported QNSPanel initializer ABI')
    original = panel.instanceMethodForSelector_(_SELECTOR)

    def initialize(self, rect, style, backing, defer, screen, platform_window):
        if not style & NSWindowStyleMaskTitled:
            style |= NSWindowStyleMaskNonactivatingPanel
        return original(self, rect, style, backing, defer, screen, platform_window)

    replacement = objc.selector(initialize, selector=_SELECTOR, signature=_SIGNATURE)
    objc.classAddMethods(panel, [replacement])
    # Retain both the original IMP and the Python callback for the app lifetime.
    _constructor = (original, replacement)
