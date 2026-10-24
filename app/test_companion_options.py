import os,tempfile,unittest,io,json,urllib.error,time
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from desktop import DesktopPet
from codex_startup import ExitGate
from app_updates import check_release,API,REPOSITORY,release_without_api,UpdateError
APP=QApplication.instance() or QApplication([])
class Changes(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name);self.patches=[patch(m+'.'+k,r/('settings.json' if k=='CONFIG' else '')) for m in ('desktop','enhanced') for k in ('CONFIG','STATE_DIR')]
  for p in self.patches:p.start()
  self.pet=DesktopPet(monitor=False);self.pet.apply_settings(dict(wandering=False,random_actions=False,drag_physics=False),save=False);self.pet.bubble.size_transition.complete();APP.processEvents()
 def tearDown(self):
  self.pet.close();APP.processEvents()
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def test_hidden_panel_stays_hidden_after_data_and_message(self):
  p=self.pet;p.apply_settings({'bubble':False},save=False)
  p.bubble.message('test');p.position_bubble();p.bubble.size_transition.complete();APP.processEvents();self.assertFalse(p.bubble.isVisible())
  p.apply_settings({'bubble':True},save=False);p.bubble.size_transition.complete();APP.processEvents();self.assertTrue(p.bubble.isVisible())
 def test_detached_panel_keeps_anchor_when_pet_moves(self):
  p=self.pet;p.apply_settings({'panel_detached':True},save=False);p.bubble.size_transition.complete();APP.processEvents();before=p.bubble.pos()
  p.move(p.x()-50,p.y()-30);p.position_bubble();self.assertEqual(p.bubble.pos(),before)
  p.bubble.show_status(True);p.bubble.size_transition.complete();p.position_bubble();self.assertEqual(p.bubble.geometry(),p.card_geometry(p.bubble.content.size()))
 def test_pet_and_panel_can_each_be_dragged_without_moving_the_other(self):
  p=self.pet;p.apply_settings(dict(panel_detached=True,no_move=False,drag_physics=False),save=False);b=p.bubble;b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
  def drag(widget,delta):
   start=widget.mapToGlobal(widget.rect().center());end=start+delta
   for kind,pos,button,buttons in [(QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseMove,end,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseButtonRelease,end,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)]:
    APP.sendEvent(widget,QMouseEvent(kind,QPointF(widget.mapFromGlobal(pos)),QPointF(pos),button,buttons,Qt.KeyboardModifier.NoModifier))
    if widget is p and kind==QEvent.Type.MouseMove:self.assertTrue(b.isVisible())
  panel_before=b.pos();pet_before=p.pos();drag(p,QPoint(-25,-20));APP.processEvents();self.assertNotEqual(p.pos(),pet_before);self.assertEqual(b.pos(),panel_before)
  pet_before=p.pos();panel_before=b.pos();drag(b,QPoint(-30,-25));APP.processEvents();self.assertEqual(p.pos(),pet_before);self.assertNotEqual(b.pos(),panel_before);self.assertIsInstance(p.settings['card_anchor'],dict)
 def test_hiding_panel_from_editor_does_not_reopen_editor_on_data(self):
  from PySide6.QtWidgets import QWidget
  p=self.pet;b=p.bubble;b.show_page('settings',QWidget());b.size_transition.complete();b.size_transition.release_landing()
  p.apply_settings({'bubble':False},save=False);b.message('new data');b.size_transition.complete();APP.processEvents();self.assertEqual(b.panel_page,'status');self.assertFalse(b.isVisible())
 def test_glide_uses_precise_16ms_scheduler(self):
  p=self.pet;p.throwing=True;p.motion_timer.start();p.schedule_movement();self.assertEqual(p.motion_timer.interval(),16);self.assertEqual(p.motion_timer.timerType(),Qt.TimerType.PreciseTimer)
 def test_exit_gate_requires_seen_and_three_confirmed_absences(self):
  g=ExitGate()
  for _ in range(5):self.assertFalse(g.observe(set()))
  self.assertFalse(g.observe({(1,1)}));self.assertFalse(g.observe(set()));self.assertFalse(g.observe(None));self.assertFalse(g.observe(set()));self.assertFalse(g.observe(set()));self.assertTrue(g.observe(set()))
  g.reset();self.assertFalse(g.observe({(2,2)}));self.assertFalse(g.observe(set()));self.assertFalse(g.observe({(3,3)}))
class DownloadFallback(unittest.TestCase):
 def test_api_limit_falls_back_to_same_repo_verified_full_package(self):
  tag='v0.8.6';name='bailong-desktop-pet-0.8.6-windows-x64.zip';sha='a'*64;calls=[]
  class Response(io.BytesIO):
   headers={'Content-Range':'bytes 0-0/1234'}
   def geturl(self):return 'https://github.com/'+REPOSITORY+'/releases/tag/'+tag
  def fetch(url,headers=None):
   calls.append(url)
   if url==API:raise urllib.error.HTTPError(API,429,'limit',{},None)
   if url.endswith('SHA256SUMS.txt'):return Response((sha+'  '+name+'\n').encode())
   return Response(b'')
  r=check_release('0.8.5',fetch);self.assertEqual((r.version,r.sha256,r.size,r.kind),('0.8.6',sha,1234,'full'));self.assertTrue(r.download_url.startswith('https://github.com/'+REPOSITORY+'/releases/download/'))
 def test_fallback_rejects_missing_checksum(self):
  class Response(io.BytesIO):
   def geturl(self):return 'https://github.com/other/repo/releases/tag/v0.8.6'
  with self.assertRaises(UpdateError):release_without_api(lambda *args:Response(b''))
if __name__=='__main__':unittest.main()
