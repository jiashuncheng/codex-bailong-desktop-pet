"""Conservative macOS fullscreen-video detection with no title or URL collection."""
import threading
import time
from PySide6.QtCore import QObject, Signal, Qt, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from mac_native import set_level

PLAYERS = {'org.videolan.vlc', 'io.mpv', 'com.colliderli.iina', 'com.apple.QuickTimePlayerX'}
BROWSERS = {'com.apple.Safari', 'com.google.Chrome', 'org.mozilla.firefox',
            'com.microsoft.edgemac', 'com.brave.Browser', 'company.thebrowser.Browser'}


def ax_value(element, name, default=None):
    import Quartz as Q
    error, value = Q.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == Q.kAXErrorSuccess else default


def video_node(root):
    import Quartz as Q
    pending = [(root, 0)]
    visited = 0
    while pending and visited < 160:
        node, depth = pending.pop()
        visited += 1
        # Explicit media roles only; ordinary browser F11 is insufficient evidence.
        role = str(ax_value(node, 'AXRole', '')).casefold()
        subrole = str(ax_value(node, 'AXSubrole', '')).casefold()
        description = str(ax_value(node, 'AXRoleDescription', '')).casefold()
        if role in ('axvideo', 'axvideoplayer') or subrole in ('axvideo', 'axvideoplayer') or description in ('video', '视频', '影片'):
            return True
        if depth < 7:
            children = ax_value(node, Q.kAXChildrenAttribute, []) or []
            pending.extend((child, depth + 1) for child in list(children)[:24])
    return False


def probe_video():
    import objc
    import Quartz as Q
    from AppKit import NSWorkspace
    with objc.autorelease_pool():
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return dict(video=False, reason='no_foreground')
        bundle = str(app.bundleIdentifier() or '')
        if bundle not in PLAYERS | BROWSERS:
            return dict(video=False, reason='ordinary_app')
        if not Q.AXIsProcessTrusted():
            return dict(video=False, reason='accessibility_required')
        element = Q.AXUIElementCreateApplication(app.processIdentifier())
        Q.AXUIElementSetMessagingTimeout(element, .2)
        window = ax_value(element, Q.kAXFocusedWindowAttribute)
        if window is None or not ax_value(window, 'AXFullScreen', False):
            return dict(video=False, reason='not_fullscreen')
        video = bundle in PLAYERS or video_node(window)
        return dict(video=video, reason='fullscreen_video' if video else 'fullscreen_without_video', pid=app.processIdentifier())


class MacVideoYield(QObject):
    observed = Signal(object)

    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.stop = threading.Event()
        self.reason = 'starting'
        self.last_sample = {}
        self.last_error = None
        self.native_applied = False
        self.attention_override = False
        self.frame = None
        self.changed = {}
        self.observed.connect(self.accept, Qt.ConnectionType.QueuedConnection)
        self.indicator = pet.bubble.status_indicator
        self.indicator.changed.connect(self.reconcile)
        self.worker = threading.Thread(target=self.run, name='BailongMacVideo', daemon=True)
        self.worker.start()
        self.queued = False
        QApplication.instance().installEventFilter(self)

    def run(self):
        while not self.stop.is_set():
            try:
                frame = probe_video()
            except Exception as error:
                frame = dict(video=False, reason='probe_error', error=type(error).__name__)
            if not self.stop.is_set():
                self.observed.emit(frame)
            self.stop.wait(1.2)

    def accept(self, frame):
        if self.stop.is_set():
            return
        self.frame = frame
        self.reason = frame['reason']
        self.last_sample = dict(frame, at=time.time())
        self.last_error = frame.get('error')
        self.reconcile()

    def reconcile(self):
        top = bool(self.pet.settings.get('on_top'))
        enabled = top and bool(self.pet.settings.get('video_fullscreen_yield'))
        detected = bool(self.frame and self.frame.get('video'))
        self.attention_override = bool(enabled and detected and self.indicator.unread)
        yielding = enabled and detected and not self.attention_override and not self.stop.is_set()
        changed = yielding != self.pet._video_yielded
        self.pet._video_yielded = yielding
        integration = getattr(self.pet, 'mac_integration', None)
        applied = []
        if integration:
            for widget in QApplication.topLevelWidgets():
                if widget.isVisible() and integration.owned(widget):
                    applied.append(set_level(widget, top and not yielding))
        self.native_applied = bool(yielding and applied and all(applied))
        if changed and integration:
            integration.refresh()

    def eventFilter(self, obj, event):
        if (self.frame and event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange)
                and isinstance(obj, QWidget) and not self.queued):
            self.queued = True
            QTimer.singleShot(0, self.reconcile_later)
        return False

    def reconcile_later(self):
        self.queued = False
        if not self.stop.is_set():
            self.reconcile()

    def shutdown(self):
        self.stop.set()
        self.frame = None
        try:
            self.indicator.changed.disconnect(self.reconcile)
        except (TypeError, RuntimeError):
            pass
        self.reconcile()
        QApplication.instance().removeEventFilter(self)
