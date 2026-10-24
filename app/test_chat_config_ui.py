"""Isolated editor/send regression checks; never use real credentials or APIs."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QDialog
from chat_window import ProviderDialog,ChatWindow
from chat_config import CHAT_DEFAULT,load_chat_config,load_provider_key,save_chat_config
from desktop_core import atomic_json
from desktop_services import SecretStore

APP=QApplication.instance() or QApplication([])


class ChatConfigUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.windows=[]
    def tearDown(self):
        for window in reversed(self.windows):
            if isinstance(window,ChatWindow):window.shutdown()
            window.deleteLater()
        APP.processEvents();self.temp.cleanup()
    def seed(self):
        config=copy.deepcopy(CHAT_DEFAULT)
        config.update(active='a',providers=[dict(id='a',name='Test service',base_url='http://localhost:1234/v1',model='test-model',timeout=90)])
        atomic_json(self.root/'chat.json',config);return config
    def dialog(self):
        dialog=ProviderDialog(self.root,embedded=True);self.windows.append(dialog);return dialog
    def chat(self):
        pet=QWidget();pet.settings={};pet.manifest={};self.windows.append(pet)
        chat=ChatWindow(pet,self.root,embedded=True);self.windows.append(chat);return chat
    def test_broken_documents_open_safely_and_cannot_be_overwritten(self):
        for raw in ('[]','{"providers":','{"providers":[{"id":"x","model":6}]}','{"history_chars":"many"}'):
            with self.subTest(raw=raw):
                path=self.root/'chat.json';path.write_text(raw,encoding='utf-8');dialog=self.dialog()
                self.assertTrue(dialog.load_error);self.assertIn('原文件已保留',dialog.status.text())
                dialog.fields['base_url'].setText('http://localhost/v1');dialog.fields['model'].setText('test');dialog.save();dialog.add();dialog.remove_confirmed('x')
                self.assertEqual(path.read_text(encoding='utf-8'),raw)
                self.assertFalse((self.root/'credentials.dpapi.json').exists())
    def test_broken_credentials_block_editor_even_with_no_provider(self):
        path=self.root/'credentials.dpapi.json';path.write_text('{broken',encoding='utf-8')
        dialog=self.dialog();self.assertTrue(dialog.load_error)
        dialog.fields['base_url'].setText('http://localhost/v1');dialog.fields['model'].setText('test');dialog.save()
        self.assertEqual(path.read_text(encoding='utf-8'),'{broken');self.assertFalse((self.root/'chat.json').exists())
    def test_unreadable_config_is_not_treated_as_new_install(self):
        self.seed()
        with patch('chat_window.load_chat_config',side_effect=OSError('无法读取 chat.json')):dialog=self.dialog()
        self.assertTrue(dialog.load_error);self.assertTrue(all(not button.isEnabled() for button in dialog.mutation_buttons))
    def test_invalid_draft_never_replaces_active_saved_configuration(self):
        self.seed();before=(self.root/'chat.json').read_bytes();dialog=self.dialog();dialog.add()
        for address,model,field in (('','test','base_url'),('bad-address','test','base_url'),('http://localhost/v1',' ','model'),('https://api.example/v1/responses','test','base_url')):
            with self.subTest(address=address,model=model):
                dialog.fields['base_url'].setText(address);dialog.fields['model'].setText(model);dialog.show();APP.processEvents();dialog.save()
                self.assertEqual((self.root/'chat.json').read_bytes(),before)
                self.assertIn('配置尚未保存',dialog.status.text());self.assertNotEqual(dialog.result(),QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.focusWidget(),dialog.fields[field])
    def test_missing_legacy_address_opens_and_can_be_edited(self):
        config=self.seed();config['providers'][0].pop('base_url');atomic_json(self.root/'chat.json',config)
        dialog=self.dialog();self.assertFalse(dialog.load_error);dialog.save();self.assertIn('请填写',dialog.status.text())
        dialog.fields['base_url'].setText('http://localhost/custom');dialog.save();self.assertEqual(load_chat_config(self.root)['providers'][0]['base_url'],'http://localhost/custom')
    def test_endpoint_preview_matches_base_and_full_endpoint_without_guessing_v1(self):
        dialog=self.dialog()
        for address,expected in (('http://localhost:1234','http://localhost:1234/chat/completions'),('https://api.example/custom/v2','https://api.example/custom/v2/chat/completions'),('https://api.example/v1/chat/completions/','https://api.example/v1/chat/completions')):
            dialog.fields['base_url'].setText(address);self.assertEqual(dialog.endpoint.text(),expected)
        dialog.fields['base_url'].setText('https://sk-secret@api.example/v1');self.assertNotIn('sk-secret',dialog.endpoint.text())
    @unittest.skipUnless(os.name=='nt','DPAPI uses current Windows account')
    def test_save_blank_key_keeps_secret_and_displays_only_presence(self):
        config=self.seed();SecretStore(self.root/'credentials.dpapi.json').put('a','isolated-legacy-key')
        dialog=self.dialog();self.assertIn('已保存密钥',dialog.key_status.text());self.assertEqual(dialog.fields['key'].text(),'')
        self.assertNotIn('isolated-legacy-key',dialog.key_status.text());dialog.fields['model'].setText('new-model');dialog.save()
        saved=load_chat_config(self.root);self.assertEqual(saved['providers'][0]['model'],'new-model');self.assertEqual(load_provider_key(self.root,saved['providers'][0]),'isolated-legacy-key')
    @unittest.skipUnless(os.name=='nt','DPAPI uses current Windows account')
    def test_failed_commit_preserves_usable_previous_service_and_editable_draft(self):
        config=self.seed();SecretStore(self.root/'credentials.dpapi.json').put('a','isolated-old-key');dialog=self.dialog()
        dialog.fields['model'].setText('new-model');dialog.fields['key'].setText('isolated-new-key')
        with patch('chat_config.atomic_json',side_effect=OSError('disk full')):dialog.save()
        saved=load_chat_config(self.root);self.assertEqual(saved['providers'][0]['model'],'test-model');self.assertEqual(load_provider_key(self.root,saved['providers'][0]),'isolated-old-key')
        self.assertEqual(dialog.fields['model'].text(),'new-model');self.assertEqual(dialog.fields['key'].text(),'isolated-new-key')
        dialog.save();saved=load_chat_config(self.root);self.assertEqual(load_provider_key(self.root,saved['providers'][0]),'isolated-new-key')
    @unittest.skipUnless(os.name=='nt','DPAPI uses current Windows account')
    def test_clear_is_confirmed_and_does_not_save_other_drafts_or_revive_key(self):
        config=self.seed();SecretStore(self.root/'credentials.dpapi.json').put('a','isolated-old-key');dialog=self.dialog();dialog.fields['model'].setText('pending-model')
        dialog.clear_key();dialog.confirmation.cancel();self.assertEqual(load_provider_key(self.root,config['providers'][0]),'isolated-old-key')
        dialog.clear_key();dialog.confirmation.confirm();saved=load_chat_config(self.root)
        self.assertEqual(saved['providers'][0]['model'],'test-model');self.assertEqual(load_provider_key(self.root,saved['providers'][0]),'')
        self.assertEqual(dialog.fields['model'].text(),'pending-model');dialog.save();saved=load_chat_config(self.root)
        self.assertEqual(saved['providers'][0]['model'],'pending-model');self.assertEqual(load_provider_key(self.root,saved['providers'][0]),'')
    def test_invalid_send_does_not_start_network_or_lose_input(self):
        config=self.seed();config['providers'][0]['base_url']='https://api.example/v1/responses';atomic_json(self.root/'chat.json',config)
        chat=self.chat();chat.input.setPlainText('preserve my message')
        with patch('chat_window.ChatStream') as stream:chat.send();stream.assert_not_called()
        self.assertEqual(chat.input.toPlainText(),'preserve my message');self.assertFalse(chat.busy);self.assertEqual(chat.session['messages'],[])
        self.assertIn('Chat Completions',chat.status.text())
    def test_corrupt_config_or_credentials_send_fails_safely(self):
        config=self.seed();chat=self.chat();chat.input.setPlainText('preserve my message')
        (self.root/'chat.json').write_text('[]',encoding='utf-8')
        with patch('chat_window.ChatStream') as stream:chat.send();stream.assert_not_called()
        self.assertIn('原文件和输入已保留',chat.status.text());self.assertEqual(chat.input.toPlainText(),'preserve my message')
        atomic_json(self.root/'chat.json',config);(self.root/'credentials.dpapi.json').write_text('{broken',encoding='utf-8')
        with patch('chat_window.ChatStream') as stream:chat.send();stream.assert_not_called()
        self.assertIn('原文件和输入已保留',chat.status.text());self.assertEqual(chat.input.toPlainText(),'preserve my message')
    def test_embedded_save_returns_to_chat_without_claiming_connection_was_tested(self):
        chat=self.chat();chat.input.setPlainText('draft');chat.provider();dialog=chat.provider_dialog
        dialog.fields['base_url'].setText('http://localhost/v1');dialog.fields['model'].setText('test');dialog.save()
        self.assertEqual(chat.pages.currentWidget(),chat.chat_body);self.assertEqual(chat.input.toPlainText(),'draft');self.assertIn('尚未验证连通',chat.status.text())


if __name__=='__main__':unittest.main()
