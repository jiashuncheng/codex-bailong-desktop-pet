"""Fork features remain valid with upstream cached validation and relocation."""
import json,unittest,sys
from unittest.mock import patch
from pathlib import Path
from material_store import MaterialStore
import test_material_store as fixtures

class MergeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MaterialStoreTests('test_seed_and_restart_reuses_hd_without_copying_or_network')
        self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
    def test_explicit_material_location_wins_over_portable_default(self):
        f=self.fixture
        (f.app/'portable-materials.json').write_text('{}')
        self.assertEqual(MaterialStore(f.app,f.state).cache,f.app/'materials')
        target=f.root/'elsewhere';target.mkdir()
        (f.state/'material-location.json').write_text(json.dumps(dict(schema=1,path=str(target))))
        self.assertEqual(MaterialStore(f.app,f.state).cache,target)
    def test_local_hd_still_restores_cached_display_hint(self):
        f=self.fixture;root=f.store.import_local_hd(f.source);f.store.activate('local_hd',root)
        restored=MaterialStore(f.app,f.state)
        self.assertEqual(restored.current,'local_hd');self.assertTrue(restored.known_available('local_hd'))
        with patch.object(restored,'_check_available',side_effect=AssertionError('display rescanned files')):
            self.assertTrue(restored.known_available('local_hd'))
    def test_storage_paths_follow_platform_data_adapter(self):
        from storage_locations import data_dir
        with patch('platform_support.data_dir',return_value=self.fixture.root/'platform-private'):
            self.assertEqual(data_dir(),self.fixture.root/'platform-private')
    @unittest.skipUnless(sys.platform=='darwin','macOS system temporary-directory alias')
    def test_mac_system_data_alias_does_not_block_material_relocation(self):
        from storage_locations import destination
        state=self.fixture.state
        if not state.is_relative_to('/private/var'):self.skipTest('temporary root is outside /private/var')
        alias=Path('/var')/state.relative_to('/private/var')
        with patch('platform_support.data_dir',return_value=alias):
            self.assertEqual(destination(self.fixture.root/'new-materials','materials',self.fixture.store.cache),self.fixture.root/'new-materials')
