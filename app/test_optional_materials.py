import hashlib,io,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from material_store import MaterialStore,MaterialError
from material_removal import removal_plan,remove_animations

class OptionalMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='bailong-optional-'));self.app=self.root/'program';self.state=self.root/'state'
        (self.app/'app').mkdir(parents=True);self.state.mkdir()
        self.payload={'素材清单.json':b'{"idle":{},"variants":[]}','idle.webp':b'fixture-animation'}
        files=[dict(path=k,bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in self.payload.items()]
        self.catalog=dict(schema=1,tiers={t:dict(id=t+'fixture',files=files,bytes=sum(f['bytes'] for f in files)) for t in ('light','hd')})
        (self.app/'app/material_catalog.json').write_text(json.dumps(self.catalog),encoding='utf-8')
        self.store=MaterialStore(self.app,self.state)
    def response(self,*args):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            for k,v in self.payload.items():z.writestr(k,v)
        result=io.BytesIO(data.getvalue());result.headers={'Content-Length':str(len(data.getvalue()))};return result
    def test_missing_media_is_card_only_and_light_can_download(self):
        self.assertIsNone(self.store.current)
        root=self.store.ensure('light',opener=self.response);self.store.activate('light',root)
        self.assertEqual(MaterialStore(self.app,self.state).current,'light')
        self.assertTrue(self.store.available('light'))
    def test_explicit_removal_preference_survives_restart_and_download_reverses_it(self):
        root=self.store.ensure('light',opener=self.response);self.store.activate('light',root)
        plan=removal_plan(self.store);called=[]
        # Do not actually remove even test files: verify each exact managed path.
        remove_animations(self.store,plan,unlink=lambda p:called.append(p))
        self.assertEqual(called,[root/'idle.webp']);self.assertIsNone(MaterialStore(self.app,self.state).current)
        self.store.activate('light',root);self.assertEqual(MaterialStore(self.app,self.state).current,'light')
    def test_changed_or_out_of_scope_removal_plan_rejected_before_deletion(self):
        root=self.store.ensure('light',opener=self.response);self.store.activate('light',root)
        plan=removal_plan(self.store);plan[0]['name']='../outside.webp'
        with self.assertRaises(MaterialError):remove_animations(self.store,plan,unlink=lambda p:self.fail('deleted'))
        self.assertFalse(self.store.card_only)
    def test_confirmed_removal_failure_leaves_safe_card_only_mode(self):
        root=self.store.ensure('light',opener=self.response);self.store.activate('light',root)
        with self.assertRaises(OSError):
            remove_animations(self.store,removal_plan(self.store),unlink=lambda p:(_ for _ in ()).throw(OSError('locked')))
        self.assertIsNone(MaterialStore(self.app,self.state).current)
    def test_redownload_after_removal_can_replace_retained_incomplete_cache(self):
        root=self.store.ensure('light',opener=self.response);self.store.activate('light',root)
        remove_animations(self.store,removal_plan(self.store),unlink=lambda p:None)
        (root/'idle.webp').write_bytes(b'locked-old-incomplete')
        restored=self.store.ensure('light',opener=self.response);self.store.activate('light',restored)
        self.assertEqual((root/'idle.webp').read_bytes(),self.payload['idle.webp'])
        self.assertEqual(self.store.current,'light')

if __name__=='__main__':unittest.main()
