"""Cross-platform launch, locking and non-destructive source synchronization."""
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
from subprocess import CompletedProcess
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load_tool(name,path):
    spec=spec_from_file_location(name,ROOT/path);module=module_from_spec(spec);spec.loader.exec_module(module);return module

class SourcePlatformTests(unittest.TestCase):
    def test_source_readiness_handles_real_venv_child_pid(self):
        import json,time
        tool=load_tool('source_launcher_ready','launch.py')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();state_file=root/'ready.json';entry=root/'run_source.py'
            entry.write_text('import os,json,time\nfrom pathlib import Path\nPath('+repr(str(state_file))+').write_text(json.dumps(dict(pid=os.getpid(),source_run=True)))\ntime.sleep(3)\n',encoding='utf-8')
            process=subprocess.Popen([sys.executable,str(entry)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5
                while not state_file.exists() and time.monotonic()<deadline:time.sleep(.01)
                state=json.loads(state_file.read_text())
                with patch.object(tool,'ROOT',root):self.assertTrue(tool.started_source_is_ready(state,process,Path(sys.executable)))
            finally:process.wait(timeout=6)

    def test_bootstrap_outputs_chinese_with_an_english_console_encoding(self):
        code="import runpy;runpy.run_path('launch.py',run_name='bootstrap_probe');print('\\u4e2d\\u6587')"
        env=dict(os.environ,PYTHONIOENCODING='cp1252',PYTHONUTF8='0')
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
        self.assertEqual(result.stdout.decode('utf-8').strip(),'中文')

    def test_fresh_checkout_can_reuse_hd_when_light_preference_has_no_files(self):
        from test_material_store import MaterialStoreTests
        fixture=MaterialStoreTests('test_fresh_default_light_and_missing_hd_preference_falls_back');fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.store.import_hd(fixture.source)
        (fixture.base/'quality/action.webp').unlink()
        tool=load_tool('prepare_cached_hd','tools/prepare_source_assets.py')
        with patch('material_store.MaterialStore',return_value=fixture.store):self.assertEqual(tool.main(),0)
        self.assertEqual(fixture.store.current,'hd')

    def test_existing_light_preference_is_preserved_when_files_are_complete(self):
        from test_material_store import MaterialStoreTests
        fixture=MaterialStoreTests('test_fresh_default_light_and_missing_hd_preference_falls_back');fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.store.import_hd(fixture.source)
        tool=load_tool('prepare_cached_light','tools/prepare_source_assets.py')
        with patch('material_store.MaterialStore',return_value=fixture.store):self.assertEqual(tool.main(),0)
        self.assertEqual(fixture.store.current,'light')

    def test_windows_keeps_existing_data_and_singleton(self):
        import platform_support as p
        with patch('sys.platform','win32'),patch.dict('os.environ',{'LOCALAPPDATA':str(ROOT/'fixture-local')}):
            self.assertEqual(p.data_dir(),ROOT/'fixture-local/BailongEnhanced')
            self.assertEqual(p.server_name(),'bailong-enhanced-local-v1')
            with patch.object(Path,'exists',return_value=True):
                self.assertIn('.venv/Scripts/python.exe',p.python_command()[0].replace('\\','/'))

    def test_lock_prevents_second_bridge_or_launcher(self):
        from process_lock import process_lock
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'worker.lock'
            with process_lock(path):
                with self.assertRaises(BlockingIOError):
                    with process_lock(path,blocking=False):self.fail('second lock acquired')
            with process_lock(path,blocking=False):pass

    def test_dirty_checkout_never_stops_or_overwrites_pet(self):
        tool=load_tool('source_sync_dirty','tools/sync_source.py')
        with patch.object(tool,'git',return_value=CompletedProcess([],0,' M app/desktop.py\n','')),patch.object(tool.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'未提交'):tool.main()
            run.assert_not_called()

    def test_divergent_checkout_never_resets_or_stops_pet(self):
        tool=load_tool('source_sync_diverged','tools/sync_source.py')
        def git(*args,**kwargs):
            value=''
            if args==('remote','get-url','origin'):value='git@github.com:jiashuncheng/codex-bailong-desktop-pet.git'
            if args[0]=='symbolic-ref':value='personal'
            return CompletedProcess([],1 if args[0]=='merge-base' else 0,value,'')
        with patch.object(tool,'git',side_effect=git),patch.object(tool.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'分叉'):tool.main()
            run.assert_not_called()

    def test_update_only_fast_forwards_and_restarts(self):
        tool=load_tool('source_sync_ff','tools/sync_source.py');calls=[]
        def git(*args,**kwargs):
            calls.append(args)
            value={'remote':'https://github.com/jiashuncheng/codex-bailong-desktop-pet.git','symbolic-ref':'personal'}.get(args[0],'')
            if args[0]=='rev-parse':value='old' if args[1]=='HEAD' else 'new'
            return CompletedProcess([],0,value,'')
        with patch.object(tool,'git',side_effect=git),patch.object(tool.subprocess,'run') as run:
            self.assertEqual(tool.main(),0)
            self.assertIn(('merge','--ff-only','FETCH_HEAD'),calls)
            self.assertEqual([c.args[0][-1] for c in run.call_args_list],['stop','start'])

if __name__=='__main__':unittest.main()
