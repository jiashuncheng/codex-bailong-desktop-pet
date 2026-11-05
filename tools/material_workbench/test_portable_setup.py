from pathlib import Path
from io import BytesIO
import hashlib,tempfile,unittest
from config_store import normalize,source_root
from download_models import download

class PortableSetupTests(unittest.TestCase):
    def test_checkout_discovery_on_all_platforms_without_personal_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'app').mkdir();(root/'run_source.py').touch()
            tool=root/'tools/material_workbench';tool.mkdir(parents=True)
            self.assertEqual(source_root(tool),root.resolve())
            for platform in ('win32','darwin','linux'):
                cfg=normalize({},tool,platform=platform,home=root/'home')
                self.assertEqual(Path(cfg['app_root']),root.resolve())
                self.assertTrue(Path(cfg['input_dir']).is_absolute())
                self.assertEqual(cfg['extra_scale'],1)
    def test_relative_path_configuration_resolves_from_config_not_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=normalize({'input_dir':'./input','output_dir':'./output'},Path(temp))
            self.assertEqual(Path(cfg['input_dir']),Path(temp).resolve()/'input')
            self.assertEqual(Path(cfg['output_dir']),Path(temp).resolve()/'output')
    def test_model_download_is_verified_and_repeat_is_noop(self):
        payload=b'fixture model';entry=dict(url='https://example.invalid/model',bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'models/model.onnx';calls=[]
            def opened(*args,**kwargs):calls.append(args);return BytesIO(payload)
            self.assertTrue(download(entry,target,opened));self.assertFalse(download(entry,target,opened))
            self.assertEqual(len(calls),1);self.assertEqual(target.read_bytes(),payload)
    def test_failed_download_preserves_previous_model_and_cleans_temp(self):
        entry=dict(url='https://example.invalid/model',bytes=4,sha256='0'*64)
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'model.onnx';target.write_bytes(b'previous')
            for payload in (b'bad',b'toolong'):
                with self.assertRaises(ValueError):download(entry,target,lambda *a,**k:BytesIO(payload))
                self.assertEqual(target.read_bytes(),b'previous')
                self.assertEqual(list(Path(temp).glob('*.tmp')),[])
