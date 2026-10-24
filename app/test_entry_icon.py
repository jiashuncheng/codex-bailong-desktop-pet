"""Real Windows shortcut serialization, isolated from installed entry points."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from installer import shortcut_script,entry_script,ps_string

@unittest.skipUnless(sys.platform=='win32','Windows shell shortcuts')
class EntryIconTests(unittest.TestCase):
 def test_replaces_old_arguments_and_sets_icon_in_chinese_path(self):
  with tempfile.TemporaryDirectory(prefix='bailong-entry-') as folder:
   root=Path(folder)/"中文 空格's";root.mkdir();link=root/'nested/白龙.lnk';link.parent.mkdir()
   exe=Path(os.environ['WINDIR'])/'System32/notepad.exe'
   seed="$s=New-Object -ComObject WScript.Shell;$l=$s.CreateShortcut("+ps_string(link)+");$l.TargetPath="+ps_string(exe)+";$l.Arguments='--quit';$l.Save();"
   script=seed+shortcut_script(exe,[ps_string(link)])+"\n$l=$s.CreateShortcut("+ps_string(link)+");@{target=$l.TargetPath;args=$l.Arguments;icon=$l.IconLocation;cwd=$l.WorkingDirectory}|ConvertTo-Json -Compress"
   result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,check=True)
   data=json.loads(result.stdout);self.assertEqual(data['args'],'');self.assertEqual(data['icon'].casefold(),(str(exe)+',0').casefold());self.assertEqual(data['cwd'].casefold(),str(exe.parent).casefold())
 def test_upgrade_keeps_one_managed_desktop_alias_and_preserves_unrelated_links(self):
  with tempfile.TemporaryDirectory(prefix='bailong-alias-') as folder:
   base=Path(folder)/'Programs'/'BailongEnhanced';old_exe=base/'versions'/'0.8.7-test'/'BailongEnhanced.exe';new_exe=base/'versions'/'0.8.8-test'/'BailongEnhanced.exe';old_exe.parent.mkdir(parents=True);new_exe.parent.mkdir(parents=True);old_exe.write_bytes(b'old');new_exe.write_bytes(b'new')
   desktop=Path(folder)/'Desktop';start=Path(folder)/'StartMenu'/'Programs';desktop.mkdir();start.mkdir(parents=True)
   shell="$s=New-Object -ComObject WScript.Shell;";owned=desktop/'白龙桌宠.lnk';main=desktop/'白龙桌宠增强版.lnk';menu=start/'白龙桌宠增强版.lnk';unrelated=desktop/'OtherPet.lnk'
   for path,target in ((owned,old_exe),(unrelated,Path(os.environ['WINDIR'])/'System32/notepad.exe')):
    script=shell+"$l=$s.CreateShortcut("+ps_string(path)+");$l.TargetPath="+ps_string(target)+";$l.Save()"
    subprocess.run(['powershell.exe','-NoProfile','-Command',script],check=True,capture_output=True)
   script="$desktop="+ps_string(desktop)+";$startmenu="+ps_string(start)+";"+entry_script(new_exe,'$desktop','$startmenu')
   script+=";@{main=$s.CreateShortcut("+ps_string(main)+").TargetPath;menu=$s.CreateShortcut("+ps_string(menu)+").TargetPath;old=(Test-Path -LiteralPath "+ps_string(owned)+");unrelated=(Test-Path -LiteralPath "+ps_string(unrelated)+")}|ConvertTo-Json -Compress"
   result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,check=True);data=json.loads(result.stdout)
   self.assertEqual(Path(data['main']),new_exe);self.assertEqual(Path(data['menu']),new_exe);self.assertFalse(data['old']);self.assertTrue(data['unrelated'])

 def test_save_error_is_nonzero(self):
  with tempfile.TemporaryDirectory() as folder:
   blocker=Path(folder)/'file';blocker.write_text('blocked')
   script=shortcut_script(Path(sys.executable),[ps_string(blocker/'bad.lnk')])
   result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True)
   self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
