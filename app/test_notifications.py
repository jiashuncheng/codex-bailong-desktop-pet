"""Notification opt-in, silent completion bookkeeping and the manual switch."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from desktop_core import normalized
from status_indicator import StatusIndicator
from enhanced import EnhancedPet
from desktop import DesktopPet

APP=QApplication.instance() or QApplication([])

class NotificationTests(unittest.TestCase):
    def test_defaults_and_explicit_opt_in(self):
        self.assertFalse(normalized({})['notifications'])
        self.assertFalse(normalized({'notifications':'true'})['notifications'])
        self.assertTrue(normalized({'notifications':True})['notifications'])

    def test_muted_completion_is_remembered_across_restart_and_never_replayed(self):
        event=dict(session='task-a',turn='turn-a')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'notifications.json'
            icon=StatusIndicator();icon.set_store(path,Path(folder))
            icon.set_notifications_enabled(False)
            self.assertTrue(icon.notify_complete(event));self.assertFalse(icon.unread)
            self.assertFalse(icon.completion_timer.isActive())
            restored=StatusIndicator();restored.set_store(path,Path(folder))
            self.assertFalse(restored.notify_complete(event))
            self.assertTrue(restored.notify_complete(dict(session='task-a',turn='turn-b')))
            self.assertEqual(restored.visual(),'attention')
            restored.set_notifications_enabled(False)
            self.assertFalse(restored.unread);self.assertNotEqual(restored.visual(),'attention')
            icon.close();restored.close()

    def test_system_delivery_is_opt_in(self):
        pet=SimpleNamespace(settings={},notify_history=[],_tray_shell_enabled=False)
        EnhancedPet.notify(pet,'完成','任务');self.assertFalse(pet.notify_history)
        pet.settings['notifications']=True
        EnhancedPet.notify(pet,'完成','任务');self.assertEqual(len(pet.notify_history),1)

    def test_muted_completion_updates_session_and_quota_without_popup_or_celebration(self):
        icon=StatusIndicator();icon.set_notifications_enabled(False)
        pet=SimpleNamespace(settings={'notifications':False},bubble=SimpleNamespace(
            status_indicator=icon,roster=Mock(items={}),task_updated=Mock()),
            say=Mock(),notify=Mock(),refresh_quota=Mock(),complete_animation=Mock())
        event=dict(kind='complete',session='task-a',turn='turn-a',title='任务')
        DesktopPet.on_activity(pet,event)
        pet.bubble.roster.observe.assert_called_once_with(event)
        pet.refresh_quota.assert_called_once();pet.say.assert_not_called()
        pet.complete_animation.assert_not_called();self.assertFalse(icon.unread)
        icon.close()

    def test_reset_refresh_continues_while_alert_popup_is_muted(self):
        pet=SimpleNamespace(settings={'notifications':False},
            local_reset_evidence=SimpleNamespace(decorate=lambda s:s),
            bubble=Mock(reset_snapshot=None,reset_feed_error=False),position_bubble=Mock(),say=Mock(),notify=Mock(),refresh_quota=Mock())
        with patch('enhanced.locally_reset',return_value=False),patch('enhanced.schedule_text',return_value=''):
            EnhancedPet.on_reset_feed(pet,{'checked':1},[dict(kind='confirmed',title='重置',text='已重置')],True)
        pet.say.assert_not_called();pet.refresh_quota.assert_called_once()

    def test_settings_switch_requires_apply_and_can_turn_back_off(self):
        from test_settings_controls import PetStub
        from desktop_settings import SettingsDialog
        pet=PetStub()
        with patch('desktop_settings.autostart_enabled',return_value=False),patch('codex_startup.enabled',return_value=False):
            dialog=SettingsDialog(pet,embedded=True)
        switch=dialog.fields['notifications'];self.assertFalse(switch.isChecked())
        switch.setChecked(True);self.assertFalse(pet.settings['notifications'])
        dialog.apply();self.assertTrue(pet.settings['notifications'])
        switch.setChecked(False);dialog.apply();self.assertFalse(pet.settings['notifications'])
        dialog.close();pet.close()
