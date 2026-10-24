import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import test_material_store as fixtures
from material_controller import MaterialController,MaterialPanel
from material_store import MaterialError
APP=QApplication.instance() or QApplication([])

def until(check):
    end=time.monotonic()+5
    # Pump Qt and explicitly yield the Python interpreter to the QThread job.
    # A tight sequence of Qt waits can starve Python workers on hosted macOS.
    while not check() and time.monotonic()<end:APP.processEvents();time.sleep(.005)
    return check()

class MaterialControllerTests(unittest.TestCase):
    def test_unstarted_player_resize_during_hidden_material_switch(self):
        from stream_player import StreamPlayer
        player=StreamPlayer();self.assertIsNone(player.resize(308));player.close()
    def setUp(self):
        self.fixture=fixtures.MaterialStoreTests('test_fresh_default_light_and_missing_hd_preference_falls_back');self.fixture.setUp()
        self.store=self.fixture.store;self.store.import_hd(self.fixture.source)
        self.c=MaterialController(self.store);self.panel=MaterialPanel(self.c)
    def tearDown(self):
        self.c.shutdown();until(lambda:self.c.job is None);self.panel.close();self.panel.deleteLater();APP.processEvents();self.fixture.tearDown()
    def test_ready_only_after_worker_verification_and_pending_blocks_new_request(self):
        ready=[];self.c.ready.connect(lambda *args:ready.append(args))
        self.assertTrue(self.c.request('hd'));self.assertFalse(self.c.request('hd'))
        self.assertTrue(until(lambda:self.c.job is None));self.assertEqual(len(ready),1)
        self.assertEqual(self.store.current,'light');self.assertEqual(self.c.state['phase'],'pending');self.assertFalse(self.c.request('hd'))
        self.store.activate(*ready[0]);self.c.applied();self.assertEqual(self.c.snapshot()['current'],'hd')
    def test_settings_offer_cache_switch_and_do_not_commit_draft_selection(self):
        self.panel.choice.setCurrentIndex(1);self.assertEqual(self.panel.action.text(),'切换画质');self.assertTrue(self.panel.action.isEnabled())
        self.assertEqual(self.store.current,'light');self.assertFalse(self.store.preference.exists())
    def test_local_hd_selection_describes_fallback_and_switches(self):
        root=self.store.import_local_hd(self.fixture.source);self.store.activate('local_hd',root)
        panel=MaterialPanel(self.c)
        self.assertEqual(panel.choice.currentData(),'local_hd')
        self.assertIn('本地高清',panel.summary.text())
        self.assertFalse(panel.action.isEnabled())
        panel.close();panel.deleteLater()
    def test_failed_download_keeps_current_and_allows_retry(self):
        with patch.object(self.store,'ensure',side_effect=MaterialError('尚未公开发布')):
            self.c.request('hd');self.assertTrue(until(lambda:self.c.job is None))
        self.assertEqual(self.c.state['phase'],'error');self.assertIn('尚未公开发布',self.panel.message.text());self.assertEqual(self.store.current,'light')
        self.assertTrue(self.c.request('hd'));self.assertTrue(until(lambda:self.c.job is None));self.assertEqual(self.c.state['phase'],'pending')
    def test_shutdown_cancels_and_waits_for_worker_without_activating(self):
        import threading
        started=threading.Event()
        def block(tier,cancel,progress):
            started.set()
            end=time.monotonic()+2
            while not cancel() and time.monotonic()<end:time.sleep(.01)
            return self.store.tier_root('hd')
        with patch.object(self.store,'ensure',side_effect=block):
            self.c.request('hd');self.assertTrue(started.wait(1));self.assertFalse(self.c.shutdown());self.assertTrue(until(lambda:self.c.job is None))
        self.assertEqual(self.store.current,'light');self.assertEqual(self.c.state['phase'],'verifying')

if __name__=='__main__':unittest.main()
