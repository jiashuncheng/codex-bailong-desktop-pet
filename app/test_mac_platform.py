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


    def test_corrupt_secret_index_blocks_keychain_access(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SecretStore(Path(folder)/'secrets.json');store.path.write_text('{broken')
            with patch('mac_services.keychain_get') as get, patch('mac_services.keychain_put') as put:
                with self.assertRaises(OSError):store.get('provider')
                with self.assertRaises(OSError):store.put('provider','synthetic-secret')
                get.assert_not_called();put.assert_not_called()
                self.assertEqual(store.path.read_text(),'{broken')

    def test_foreign_ciphertext_is_not_treated_as_mac_key(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SecretStore(Path(folder)/'secrets.json');store.path.write_text('{"provider":"foreign-ciphertext"}')
            with patch('mac_services.keychain_get') as get:
                with self.assertRaises(OSError):store.get('provider')
                get.assert_not_called()

    def test_chat_key_replacement_failure_retains_old_keychain_slot(self):
        import chat_config as config
        from desktop_core import atomic_json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);keys={}
            def put(account,value):
                if value:keys[account]=value
                else:keys.pop(account,None)
            with patch('mac_services.keychain_get',side_effect=lambda account:keys.get(account,'')), patch('mac_services.keychain_put',side_effect=put):
                value=dict(config.CHAT_DEFAULT,active='provider',providers=[dict(id='provider',model='fixture')])
                atomic_json(root/'chat.json',value);SecretStore(root/'credentials.dpapi.json').put('provider','old-synthetic-key')
                with patch('chat_config.atomic_json',side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):config.save_chat_config(root,value,'provider','new-synthetic-key')
                saved=config.load_chat_config(root)
                self.assertEqual(config.load_provider_key(root,saved['providers'][0]),'old-synthetic-key')
                saved=config.save_chat_config(root,value,'provider','new-synthetic-key')
                self.assertEqual(config.load_provider_key(root,saved['providers'][0]),'new-synthetic-key')


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
    def test_nonactivating_constructor_is_scoped_idempotent_and_preserves_arguments(self):
        import mac_panels
        from types import SimpleNamespace
        from unittest.mock import Mock
        panel=Mock();original=Mock(return_value='native-window')
        panel.initWithContentRect_styleMask_backing_defer_screen_platformWindow_.signature=mac_panels._SIGNATURE
        panel.instanceMethodForSelector_.return_value=original
        def selector(callback,**kwargs):return SimpleNamespace(callback=callback,**kwargs)
        with patch.object(mac_panels,'_constructor',None),patch('objc.lookUpClass',return_value=panel),patch('objc.selector',side_effect=selector),patch('objc.classAddMethods') as add:
            mac_panels.install_nonactivating_panels();mac_panels.install_nonactivating_panels()
            add.assert_called_once();callback=add.call_args.args[1][0].callback
            from AppKit import NSWindowStyleMaskNonactivatingPanel as mask
            self.assertEqual(callback('self','rect',14,2,False,'screen','platform'),'native-window')
            original.assert_called_with('self','rect',14|mask,2,False,'screen','platform')
            callback('self','rect',15,2,False,'screen','platform')
            original.assert_called_with('self','rect',15,2,False,'screen','platform')

    def test_unknown_native_constructor_abi_is_not_replaced(self):
        import mac_panels
        from unittest.mock import Mock
        panel=Mock();panel.initWithContentRect_styleMask_backing_defer_screen_platformWindow_.signature=b'unknown'
        with patch.object(mac_panels,'_constructor',None),patch('objc.lookUpClass',return_value=panel),patch('objc.classAddMethods') as add:
            with self.assertRaisesRegex(RuntimeError,'ABI'):mac_panels.install_nonactivating_panels()
            add.assert_not_called()

    def test_activation_requires_explicit_editor_intent_and_preserves_previous_app(self):
        from mac_native import activate_editor
        from types import SimpleNamespace
        from unittest.mock import Mock
        widget=SimpleNamespace(_mac_keyboard_input=False);front=Mock()
        front.processIdentifier.return_value=os.getpid()+100
        with patch('AppKit.NSWorkspace') as workspace,patch('AppKit.NSRunningApplication') as application,patch('mac_native.remember_external_application') as remember:
            workspace.sharedWorkspace().frontmostApplication.return_value=front
            activate_editor(widget);application.currentApplication.assert_not_called()
            widget._mac_keyboard_input=True;activate_editor(widget)
            remember.assert_called_once_with(front)
            application.currentApplication().activateWithOptions_.assert_called_once_with(0)
            application.reset_mock();front.processIdentifier.return_value=os.getpid()
            activate_editor(widget);application.currentApplication.assert_not_called()

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
        window.level.return_value = 8
        with patch('mac_native.native_window', return_value=window):
            self.assertTrue(set_level(Mock(), True))
            window.setLevel_.assert_not_called()
            set_level(Mock(), False)
            window.setLevel_.assert_called_once_with(0)

    def test_pending_explicit_editor_does_not_release_application_focus(self):
        from types import SimpleNamespace
        from mac_native import MacIntegration
        integration=SimpleNamespace(pet=SimpleNamespace(bubble=SimpleNamespace(panel_page='status',_mac_keyboard_input=True)))
        with patch('mac_native.QApplication.activePopupWidget',return_value=None),patch('mac_native.release_application_focus') as release:
            MacIntegration.release_passive_activation(integration);release.assert_not_called()
            integration.pet.bubble._mac_keyboard_input=False
            MacIntegration.release_passive_activation(integration);release.assert_called_once()

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
