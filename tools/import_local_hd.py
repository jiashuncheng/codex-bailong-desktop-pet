"""Import verified local HD files and use light files for missing animations."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))

def main():
    from platform_support import data_dir
    from material_store import MaterialStore
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',nargs='?')
    args=parser.parse_args()
    store=MaterialStore(ROOT,data_dir())
    source=args.source or store.local_hd_info().get('source')
    if not source or not Path(source).is_dir():
        from PySide6.QtWidgets import QApplication,QFileDialog
        app=QApplication.instance() or QApplication([])
        source=QFileDialog.getExistingDirectory(None,'选择本地高清素材目录（包含 quality-v1 等文件夹）')
        if not source:
            print('已取消，保留当前画质。');return 1
    root=store.import_local_hd(source)
    info=store.local_hd_info()
    if not info['fallback_files']:
        # The completed snapshot is independent of its syncing source. Reuse
        # these immutable files as the normal fully verified HD cache.
        root=store.import_hd(root)
        store.activate('hd',root)
    else:
        store.activate('local_hd',root)
    print(f"本地高清已接入：{len(info['hd_files'])} 个文件使用高清，{len(info['fallback_files'])} 个文件使用轻量。",flush=True)
    print('后续文件同步完成后，再次双击“更新本地高清素材.command”即可校验、更新并重启。',flush=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError) as error:
        print('素材未更新，保留当前画质：'+str(error),file=sys.stderr);raise SystemExit(1)
