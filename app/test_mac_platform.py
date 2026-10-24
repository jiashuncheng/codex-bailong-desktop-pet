"""Mac adapter regressions; no real SSH, Keychain, account or login-item writes."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import msgspec
from platform_support import data_dir, server_name, ROOT
from mac_services import launch_agent, secret_account
from desktop_services import SecretStore
from codex_live_status import LiveStatusReader, Frames


class MacPathsTests(unittest.TestCase):
    def test_mac_data_is_separate_from_source(self):
        with patch.dict(os.environ, {}, clear=True), patch('sys.platform', 'darwin'):
            self.assertEqual(data_dir(), Path.home() / 'Library/Application Support/BailongMac')
            self.assertNotEqual(data_dir().parent, ROOT)

    def test_explicit_data_override_and_isolated_legacy_tests(self):
        with patch.dict(os.environ, {'BAILONG_DATA_DIR': '/tmp/mac-explicit', 'LOCALAPPDATA': '/tmp/legacy'}):
            self.assertEqual(data_dir(), Path('/tmp/mac-explicit').resolve())
        with patch.dict(os.environ, {'LOCALAPPDATA': '/tmp/legacy'}):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('BAILONG_DATA_DIR', None)
                self.assertEqual(data_dir(), Path('/tmp/legacy/BailongEnhanced'))

    def test_singleton_is_scoped_to_data_folder(self):
        with patch.dict(os.environ, {'BAILONG_DATA_DIR': '/tmp/mac-a'}):
            a = server_name()
            self.assertEqual(server_name(), a)
        with patch.dict(os.environ, {'BAILONG_DATA_DIR': '/tmp/mac-b'}):
            self.assertNotEqual(a, server_name())

    def test_launch_agent_uses_argument_array_and_current_source(self):
        value = launch_agent()
        self.assertIn(str(ROOT / 'launch.py'), value['ProgramArguments'])
        self.assertEqual(value['ProgramArguments'][-1], '--autostart')
        self.assertNotIn('/bin/sh', value['ProgramArguments'])
        self.assertFalse(value.get('KeepAlive', False))

    def test_secret_marker_never_contains_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(Path(folder) / 'secrets.json')
            with patch('sys.platform', 'darwin'), patch('mac_services.keychain_put') as put, patch('mac_services.keychain_get', return_value='test-secret'):
                store.put('provider', 'test-secret')
                put.assert_called_once_with(secret_account(store.path, 'provider'), 'test-secret')
                self.assertNotIn('test-secret', store.path.read_text())
                self.assertEqual(store.get('provider'), 'test-secret')
                store.put('provider', '')
                self.assertNotIn('provider', store.read())

    def test_keychain_failure_keeps_old_index(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(Path(folder) / 'secrets.json')
            store.path.write_text('{"old":"macOS-Keychain"}')
            with patch('sys.platform', 'darwin'), patch('mac_services.keychain_put', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    store.put('new', 'must-not-be-written')
            self.assertEqual(store.read(), {'old': 'macOS-Keychain'})


class MacBridgeTests(unittest.TestCase):
    def test_ssh_is_opt_in_and_alias_is_not_a_command(self):
        from mac_bridge import read_config, save_config
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'BAILONG_DATA_DIR': folder}):
            self.assertFalse(read_config().get('enabled'))
            with self.assertRaises(ValueError):
                save_config(True, 'host; touch /tmp/should-not-exist')
            with self.assertRaises(ValueError):
                save_config(True, '')
            save_config(True, 'gpu-test')
            self.assertEqual(read_config(), dict(enabled=True, ssh_host='gpu-test'))


class UnixIPCTests(unittest.TestCase):
    def test_fragmented_frames_are_reassembled(self):
        raw = msgspec.json.encode(dict(type='response', result=dict(clientId='fake')))
        packet = struct.pack('<I', len(raw)) + raw
        frames = Frames()
        self.assertEqual(list(frames.feed(packet[:3])), [])
        self.assertEqual(list(frames.feed(packet[3:7])), [])
        self.assertEqual(list(frames.feed(packet[7:])), [raw])

    def test_unix_subscription_projects_lifecycle_and_clears_on_disconnect(self):
        sid = '12345678-1234-4234-8234-123456789012'
        with tempfile.TemporaryDirectory(prefix='bm-') as folder:
            path = str(Path(folder) / 'ipc.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            server.listen(1)
            server.settimeout(4)
            errors = []
            def send(connection, obj):
                raw = msgspec.json.encode(obj)
                connection.sendall(struct.pack('<I', len(raw)) + raw)
            def receive(connection):
                frames = Frames()
                while True:
                    data = connection.recv(65536)
                    if not data:
                        raise OSError('closed')
                    for raw in frames.feed(data):
                        return json.loads(raw)
            def serve():
                try:
                    with server.accept()[0] as peer:
                        peer.settimeout(4)
                        self.assertEqual(receive(peer)['method'], 'initialize')
                        send(peer, dict(type='response', method='initialize', result=dict(clientId='fake-client')))
                        self.assertEqual(receive(peer)['method'], 'thread-stream-following-changed')
                        send(peer, dict(type='broadcast', method='thread-stream-state-changed', version=11,
                                        params=dict(conversationId=sid, hostId='local', change=dict(
                                            type='snapshot', revision=1, conversationState=dict(
                                                turns=[dict(turnId='fake-turn', status='inProgress')],
                                                threadRuntimeStatus=dict(type='active', activeFlags=['waitingOnApproval']))))))
                        # Wait for reader cleanup/unfollow; close never exposes a real account.
                        try:receive(peer)
                        except OSError:pass
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            stop = threading.Event()
            got = threading.Event()
            waiting = []
            def notify(session, reason, turn):
                waiting.append(reason)
                if reason:
                    got.set()
                    stop.set()
            reader = LiveStatusReader(stop, lambda *_: None, notify)
            reader.set_targets([sid])
            with patch.dict(os.environ, {'BAILONG_IPC': path}), patch('sys.platform', 'darwin'):
                reader.start()
                self.assertTrue(got.wait(5), reader.health_snapshot())
                stop.set()
                reader.join(3)
            server.close()
            thread.join(2)
            self.assertFalse(reader.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(waiting, ['approval', ''])


class SourceUpdateTests(unittest.TestCase):
    def test_mac_controller_cannot_download_windows_updates(self):
        from PySide6.QtWidgets import QApplication
        from update_controller import UpdateController
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch('sys.platform', 'darwin'):
            controller = UpdateController('0.7.9', Path(folder), allow_auto=False)
            controller.configure(True)
            self.assertFalse(controller.enabled)
            with patch('update_controller.UpdateJob') as job:
                self.assertFalse(controller.check())
                self.assertFalse(controller.download_install())
                job.assert_not_called()
            self.assertTrue(controller.shutdown())


class KeyboardFocusTests(unittest.TestCase):
    def test_passive_flags_allow_mouse_but_reject_keyboard(self):
        from PySide6.QtCore import Qt
        from pet import FLAGS
        self.assertTrue(FLAGS & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertFalse(FLAGS & Qt.WindowType.WindowTransparentForInput)

    def test_only_explicit_editor_navigation_enables_keyboard(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QWidget
        from mac_native import set_keyboard_input
        app = QApplication.instance() or QApplication([])
        widget = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        widget.show()
        for editing in (True, False, True, False):
            set_keyboard_input(widget, editing)
            self.assertEqual(bool(widget.windowHandle().flags() & Qt.WindowType.WindowDoesNotAcceptFocus), not editing)
            self.assertTrue(widget.isVisible())
        widget.close()

    def test_same_native_level_does_not_reorder_window(self):
        from mac_native import set_level
        from unittest.mock import Mock
        window = Mock()
        window.level.return_value = 3
        with patch('mac_native.native_window', return_value=window):
            self.assertTrue(set_level(Mock(), True))
            window.setLevel_.assert_not_called()
            set_level(Mock(), False)
            window.setLevel_.assert_called_once_with(0)

    def test_focus_return_never_overrides_users_new_application(self):
        from mac_native import release_application_focus
        from unittest.mock import Mock
        front = Mock()
        front.processIdentifier.return_value = os.getpid() + 100
        previous = Mock()
        with patch('AppKit.NSWorkspace') as workspace, patch('AppKit.NSApplication') as application, patch('mac_native._last_external_application', previous):
            workspace.sharedWorkspace().frontmostApplication.return_value = front
            release_application_focus()
            application.sharedApplication().deactivate.assert_not_called()
            previous.activateWithOptions_.assert_not_called()

    def test_focus_is_returned_only_from_our_own_frontmost_process(self):
        from mac_native import release_application_focus
        from unittest.mock import Mock
        front = Mock()
        front.processIdentifier.return_value = os.getpid()
        previous = Mock()
        previous.isTerminated.return_value = False
        with patch('AppKit.NSWorkspace') as workspace, patch('AppKit.NSApplication') as application, patch('mac_native._last_external_application', previous):
            workspace.sharedWorkspace().frontmostApplication.return_value = front
            release_application_focus()
            application.sharedApplication().deactivate.assert_called_once()
            previous.activateWithOptions_.assert_called_once_with(0)


if __name__ == '__main__':
    unittest.main()
