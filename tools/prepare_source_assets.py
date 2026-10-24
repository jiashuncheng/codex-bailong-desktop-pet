"""Reuse validated local assets; ask for a source folder on a fresh checkout."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))

def main():
    from material_store import MaterialStore
    from platform_support import data_dir
    store=MaterialStore(ROOT,data_dir())
    if store.current in ('hd','local_hd') and store.available(store.current):return 0
    light=store.catalog['tiers']['light']['files']
    if all((store.tier_root('light')/f['path']).is_file() and (store.tier_root('light')/f['path']).stat().st_size==f['bytes'] for f in light):
        store.verify(store.tier_root('light'),'light');return 0
    for tier in ('hd','local_hd'):
        if store.available(tier):
            store.activate(tier,store.tier_root(tier));return 0
    print('首次运行请选择完整高清素材目录，包含素材清单及 quality-v1 等子目录。',flush=True)
    from import_local_hd import main as import_assets
    return import_assets()

if __name__=='__main__':raise SystemExit(main())
