"""Exercise the actual local orchestrator without launching or stopping any pet."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import build_local as local

class LocalWorkflowTests(unittest.TestCase):
    def test_safe_print_escapes_text_for_legacy_console_encodings(self):
        class AsciiConsole:
            encoding='ascii'
            def __init__(self):self.value=''
            def write(self,text):
                text.encode('ascii')
                self.value+=text
                return len(text)
            def flush(self):pass
        console=AsciiConsole()
        with patch('sys.stdout',console):local.safe_print('构建应用目录')
        self.assertIn(r'\u6784\u5efa',console.value)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'app').mkdir();(self.root/'app/example.py').write_text('answer=42')
        self.stage=self.root/'release/BailongEnhanced';self.stage.mkdir(parents=True);(self.stage/'BailongEnhanced.exe').write_bytes(b'compiled-placeholder')
        self.proof=dict(version=local.VERSION,executableSha256=local.sha(self.stage/'BailongEnhanced.exe'),tlsRuntime=dict(passed=True,certificateVerification=True,hostnameVerification=True,offline=True))
        self.patch=patch.object(local,'ROOT',self.root);self.patch.start()
        receipt=self.root/'本地实装/回归验收/current-regressions.json';receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(dict(passed=True,scope='full',expectedModules=['test_local_workflow','test_release_retention','test_release_version'],modules=3,tests=1,sourceHashes=local.source_hashes())),encoding='utf-8')
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_verified_local_deploy_has_lock_ready_validation_and_no_package_command(self):
        lock=Mock();lock.tryLock.return_value=True
        result=dict(current='new',previous='old',backup='backup',executable='new.exe')
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch('installer.DATA',self.root/'user-data'),patch('installer.startup_preference',return_value=False),patch('directory_deploy.deploy_directory',return_value=result) as deploy,patch.object(local,'verify_installed',return_value=dict(passed=True)) as verify:
            self.assertEqual(local.install_verified(self.proof,self.stage),0)
        deploy.assert_called_once_with(self.stage,False);verify.assert_called_once_with(result);lock.unlock.assert_called_once()
        report=local.read(self.root/'本地实装/最终验收.json');self.assertEqual(report['regression']['tests'],1)
    def test_existing_same_version_package_does_not_fail_after_deploy(self):
        (self.root/'release'/('old-'+local.VERSION+'.zip')).write_bytes(b'previous')
        lock=Mock();lock.tryLock.return_value=True
        result=dict(current='new',previous='old',backup='backup',executable='new.exe')
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch('installer.DATA',self.root/'user-data'),patch('installer.startup_preference',return_value=False),patch('directory_deploy.deploy_directory',return_value=result),patch.object(local,'verify_installed',return_value=dict(passed=True)):
            self.assertEqual(local.install_verified(self.proof,self.stage),0)
    def test_targeted_receipt_cannot_authorize_deploy(self):
        path=self.root/'本地实装/回归验收/current-regressions.json';value=local.read(path);value['scope']='targeted';path.write_text(json.dumps(value),encoding='utf8')
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaises(ValueError):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_unknown_test_module_cannot_write_full_receipt(self):
        import subprocess,sys
        real=Path(__file__).parent
        result=subprocess.run([sys.executable,str(real/'quality_check.py'),'audit-invalid','nonexistent_test_module'],cwd=real,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Unknown test modules',result.stdout+result.stderr)
    def test_changed_source_or_lock_collision_prevents_deploy(self):
        (self.root/'app/example.py').write_text('answer=43')
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaises(ValueError):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_deploy_verified_rejects_changed_executable_before_stop_or_build(self):
        path=self.root/'本地实装/构建验收.json';path.write_text(json.dumps(self.proof))
        (self.stage/'BailongEnhanced.exe').write_bytes(b'changed')
        lock=Mock();lock.tryLock.return_value=True
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch.object(local,'verify_code'),patch.object(local,'install_verified') as install,patch.object(local.subprocess,'run') as build,self.assertRaises(ValueError):local.main(['--deploy-verified'])
        build.assert_not_called();install.assert_not_called()
    def test_default_build_calls_application_only_and_preserves_verified_handoff(self):
        with patch.object(local.subprocess,'run') as run,patch.object(local,'verify_code',return_value=dict(passed=True)),patch.object(local,'verify_tls_runtime',return_value=self.proof['tlsRuntime']),patch.object(local,'native_matrix',return_value=[]),patch.object(local,'snapshot_source',return_value=self.root/'snapshot'),patch.object(local,'install_verified',return_value=0) as deploy:
            self.assertEqual(local.build_and_deploy(SimpleNamespace(build_only=False)),0)
        command=run.call_args.args[0];self.assertEqual(Path(command[1]).name,'build_release.py');self.assertNotIn('--package',command)
        self.assertEqual(deploy.call_args.args[0]['executableSha256'],local.sha(self.stage/'BailongEnhanced.exe'))
        self.assertFalse(deploy.call_args.args[0]['fullInstallerGenerated'])
    def test_missing_frozen_tls_proof_cannot_authorize_deploy(self):
        del self.proof['tlsRuntime']
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaisesRegex(ValueError,'TLS'):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_ssl_runtime_data_is_bundled_and_missing_required_file_stops_build(self):
        from build_release import ssl_runtime_data
        module=self.root/'ssl.py';module.write_text("file='codex-rejected-cas.pem'")
        with self.assertRaises(OSError):ssl_runtime_data(module)
        pem=module.with_name('codex-rejected-cas.pem');pem.write_bytes(b'public certificate data')
        self.assertEqual(ssl_runtime_data(module),['--add-data',str(pem)+';.'])
        pem.unlink();module.write_text('standard ssl implementation');self.assertEqual(ssl_runtime_data(module),[])

if __name__=='__main__':unittest.main()
