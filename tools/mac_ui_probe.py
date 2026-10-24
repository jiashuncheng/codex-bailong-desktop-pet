"""Exercise real Mac Qt windows using isolated, clearly labelled demo data."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hold', type=int, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not os.environ.get('BAILONG_DATA_DIR') or not os.environ.get('CODEX_HOME'):
        raise RuntimeError('Native probe requires explicitly isolated BAILONG_DATA_DIR and CODEX_HOME')
    from PySide6.QtCore import QTimer, QPoint, Qt
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtWidgets import QApplication
    from desktop import DesktopPet
    from mac_native import MacIntegration, prepare_application, native_window
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    prepare_application(app)
    pet = DesktopPet(monitor=False)
    pet.apply_settings(dict(wandering=False, random_actions=False, sound=False))
    pet.mac_integration = MacIntegration(pet)
    pet.show()
    area = app.primaryScreen().availableGeometry()
    pet.move(area.right() - 365, area.bottom() - 300)
    pet.update_quota([dict(name='5小时', remaining=68, resetsAt=None),
                      dict(name='一周', remaining=82, resetsAt=None)], time.time(), 'demo')
    pet.bubble.quota_caption = 'Mac 界面演示 · 非真实额度'
    for i in range(3):
        pet.on_activity(dict(kind='status', session=f'12345678-1234-4234-8234-{i:012d}',
                             title='Mac 移植演示 ' + str(i + 1), turn='demo', state='working',
                             active=1, text='正在验证源码与窗口交互'))
    pet.bubble.redraw()
    pet.position_bubble()
    results = dict(platform=app.platformName(), screens=len(app.screens()), dpr=pet.devicePixelRatioF(),
                   errors=[], checks={})
    def settle():
        pet.bubble.size_transition.complete()
        pet.bubble.size_transition.release_landing()
        app.processEvents()
    def capture(name):
        settle()
        pet.record_state()
        pet.bubble.grab().save(str(args.output / (name + '.png')))
    def run(name, function):
        try:
            function()
            results['checks'][name] = True
        except Exception as error:
            results['checks'][name] = False
            results['errors'].append(dict(stage=name, error=repr(error)))
    def normal():
        capture('normal')
        window = native_window(pet)
        assert window is not None and not window.hidesOnDeactivate()
        assert pet.frames and pet.player.frame_index > 0
        results['native_level'] = int(window.level())
        results['collection_behavior'] = int(window.collectionBehavior())
        pet.grab().save(str(args.output / 'pet.png'))
    def report():
        pet.open_report()
        pet.bubble.report.animation.setCurrentTime(pet.bubble.report.animation.duration())
        pet.bubble.report.grab().save(str(args.output / 'report.png'))
        assert pet.bubble.report.isVisible()
    def settings():
        pet.open_settings()
        capture('settings')
        assert pet.bubble.panel_page == 'settings'
        assert 'macOS' in pet.settings_dialog.startup.text()
    def chat():
        pet.open_chat()
        capture('chat')
        assert pet.bubble.panel_page == 'chat'
    def modes():
        pet.bubble.return_to_status()
        settle()
        for mode in ('mini', 'minimal', 'auto'):
            pet.bubble.set_mode(mode)
            capture(mode)
        pet.apply_settings(dict(character_visible=False))
        assert not pet.isVisible() and pet.bubble.isVisible()
        pet.apply_settings(dict(character_visible=True))
        assert pet.isVisible()
        pet.set_option('on_top', False)
        assert native_window(pet).level() == 0
        pet.set_option('on_top', True)
        pet.mac_integration.refresh()
        assert native_window(pet).level() > 0
    def finish():
        results['passed'] = all(results['checks'].values()) and not results['errors']
        (args.output / 'native-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(results, ensure_ascii=False), flush=True)
        if not args.hold:
            pet.close()
    stages = [('normal', normal), ('report', report), ('settings', settings), ('chat', chat), ('modes', modes)]
    def next_stage():
        if not stages:
            finish()
            if args.hold:QTimer.singleShot(args.hold*1000,pet.close)
            return
        name,function=stages.pop(0)
        run(name,function)
        QTimer.singleShot(1400,next_stage)
    QTimer.singleShot(1600,next_stage)
    app.exec()
    return 0 if results.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
