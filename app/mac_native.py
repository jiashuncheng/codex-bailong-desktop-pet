"""Native floating panels and alpha hit testing, preserving Qt's Retina geometry."""
import os
import sys
from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget, QMenu

_last_external_application = None


def remember_external_application(application=None):
    global _last_external_application
    from AppKit import NSWorkspace
    application = application or NSWorkspace.sharedWorkspace().frontmostApplication()
    if application is not None and int(application.processIdentifier()) != os.getpid() and not application.isTerminated():
        _last_external_application = application


def release_application_focus():
    from AppKit import NSApplication, NSWorkspace
    application = NSApplication.sharedApplication()
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    # Never override an application the user has already switched to.
    if front is None or int(front.processIdentifier()) != os.getpid():
        return
    application.deactivate()
    previous = _last_external_application
    if previous is not None and not previous.isTerminated():
        # deactivate() alone leaves an accessory Python process frontmost on
        # recent macOS. Hand activation back only while we are still frontmost.
        previous.activateWithOptions_(0)


def native_window(widget):
    import objc
    from ctypes import c_void_p
    if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
        return None
    view = objc.objc_object(c_void_p=c_void_p(int(widget.winId())))
    return view.window()


def set_level(widget, top):
    from AppKit import NSFloatingWindowLevel, NSNormalWindowLevel
    window = native_window(widget)
    if window is not None:
        level = NSFloatingWindowLevel if top else NSNormalWindowLevel
        # AppKit can reorder a panel on setLevel:, even for the same level.
        if window.level() != level:
            window.setLevel_(level)
        return True
    return False


def configure_window(widget, top=True):
    from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces,
                        NSWindowCollectionBehaviorFullScreenAuxiliary,
                        NSWindowCollectionBehaviorStationary,
                        NSWindowCollectionBehaviorIgnoresCycle)
    widget.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
    if hasattr(widget,'_mac_keyboard_input'):
        set_keyboard_input(widget,widget._mac_keyboard_input)
    window = native_window(widget)
    if window is None:
        return
    if window.hidesOnDeactivate():
        window.setHidesOnDeactivate_(False)
    behavior = (NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorFullScreenAuxiliary |
                NSWindowCollectionBehaviorStationary |
                NSWindowCollectionBehaviorIgnoresCycle)
    if window.collectionBehavior() != behavior:
        window.setCollectionBehavior_(behavior)
    if window.hasShadow():
        window.setHasShadow_(False)
    if hasattr(window, 'setBecomesKeyOnlyIfNeeded_'):
        window.setBecomesKeyOnlyIfNeeded_(True)
    set_level(widget, top)


def set_keyboard_input(widget, editing):
    """Only explicit settings/chat navigation may opt into keyboard focus.

    WA_ShowWithoutActivating affects show(), but does not prevent a QNSPanel
    from subsequently becoming key. WindowDoesNotAcceptFocus enforces that
    native restriction and still allows mouse clicks, scrolling and dragging.
    """
    was_editing = getattr(widget, '_mac_keyboard_input', False)
    widget._mac_keyboard_input = bool(editing)
    reject = not editing
    handle = widget.windowHandle()
    if handle is not None:
        if bool(handle.flags() & Qt.WindowType.WindowDoesNotAcceptFocus) != reject:
            handle.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, reject)
    elif bool(widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus) != reject:
        widget.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, reject)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus if editing else Qt.FocusPolicy.NoFocus)
    if reject and was_editing and QApplication.platformName() != 'offscreen':
        window = native_window(widget)
        if window is not None and window.isKeyWindow():
            window.resignKeyWindow()
        if QApplication.activePopupWidget() is None:
            release_application_focus()



def prepare_application(app):
    app.setStyle('Fusion')
    app.setApplicationName('白龙桌宠 Mac')
    app.setOrganizationName('BailongMac')
    if sys.platform == 'darwin' and app.platformName() != 'offscreen':
        remember_external_application()
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


class MacIntegration(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.last_ignore = None
        self.enabled = QApplication.platformName() != 'offscreen'
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update_hit_test)
        if self.enabled:
            from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification, NSWorkspaceApplicationKey
            from Foundation import NSOperationQueue
            self.workspace_center = NSWorkspace.sharedWorkspace().notificationCenter()
            self.workspace_observer = self.workspace_center.addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidActivateApplicationNotification, None, NSOperationQueue.mainQueue(),
                lambda notification: remember_external_application(notification.userInfo().get(NSWorkspaceApplicationKey)))
            QApplication.instance().installEventFilter(self)
            pet.settingsChanged.connect(lambda _: self.refresh())
            self.refresh()
            self.timer.start()
            QTimer.singleShot(0, self.release_passive_activation)

    def release_passive_activation(self):
        # A plain Python process can be promoted by AppKit on its first show.
        # Yield our own activation once; never activate another app by PID.
        if self.pet.bubble.panel_page == 'status' and QApplication.activePopupWidget() is None:
            release_application_focus()

    def owned(self, widget):
        if widget is self.pet or widget is self.pet.bubble:
            return True
        if getattr(widget, '_owner', None) is self.pet:
            return True
        parent = widget.parentWidget()
        while parent:
            if parent in (self.pet, self.pet.bubble):
                return True
            parent = parent.parentWidget()
        return False

    def refresh(self):
        top = self.pet.settings.get('on_top', True) and not self.pet._video_yielded
        for widget in QApplication.topLevelWidgets():
            if self.owned(widget) and not isinstance(widget, QMenu):
                configure_window(widget, top)
        self.last_ignore = None
        self.update_hit_test()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.ApplicationActivate, QEvent.Type.ApplicationStateChange):
            QTimer.singleShot(0, self.release_passive_activation)
        if (event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange)
                and isinstance(obj, QWidget) and obj.isWindow() and not isinstance(obj, QMenu)
                and self.owned(obj)):
            QTimer.singleShot(0, self.refresh)
        return False

    def update_hit_test(self):
        pet = self.pet
        if not pet.isVisible():
            return
        point = pet.mapFromGlobal(QCursor.pos())
        pressed = pet.dragging or getattr(pet, '_pointer_pressed', False)
        ignore = bool(pet.settings.get('mouse_through')) or (not pressed and not pet.alpha_hit(point.x(), point.y()))
        if ignore != self.last_ignore:
            window = native_window(pet)
            if window is not None:
                window.setIgnoresMouseEvents_(ignore)
                self.last_ignore = ignore

    def shutdown(self):
        self.timer.stop()
        if self.enabled:
            QApplication.instance().removeEventFilter(self)
            self.workspace_center.removeObserver_(self.workspace_observer)
