"""Native key-window regression, isolated from user settings and conversations."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('BAILONG_DATA_DIR') or not os.environ.get('CODEX_HOME'):
        raise RuntimeError('Set isolated BAILONG_DATA_DIR and CODEX_HOME')
    from AppKit import NSWorkspace
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from desktop import DesktopPet
    from mac_native import prepare_application, native_window, MacIntegration
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    before = int(front.processIdentifier()) if front else None
    app = QApplication([])
    prepare_application(app)
    app.setQuitOnLastWindowClosed(False)
    pet = DesktopPet(monitor=False)
    pet.apply_settings(dict(wandering=False, random_actions=False, sound=False))
    pet.mac_integration = MacIntegration(pet)
    pet.show()
    pet.bubble.redraw()
    pet.position_bubble()
    result = dict(passed=True, checks={}, native={}, passive_samples=0, passive_key_samples=0)
    def native(key, widget, reject):
        window = native_window(widget)
        value = dict(can_key=bool(window.canBecomeKeyWindow()), key=bool(window.isKeyWindow()))
        result['native'][key] = value
        if not reject and not value['key']:raise AssertionError('Editor did not receive keyboard focus: '+key)
        result['checks'][key] = value['can_key'] != reject and (not reject or not value['key'])
    def finish_transition():
        pet.bubble.size_transition.complete()
        pet.bubble.size_transition.release_landing()
    def tick():
        # Exercise exactly the background paths that used to raise/reorder panels.
        pet.position_bubble()
        pet.mac_integration.refresh()
        if pet.bubble.panel_page == 'status':
            result['passive_samples'] += 1
            windows = [pet, pet.bubble]
            if pet.bubble.report:
                windows.append(pet.bubble.report)
            if any(native_window(w) and native_window(w).isKeyWindow() for w in windows):
                result['passive_key_samples'] += 1
    timer = QTimer()
    timer.setInterval(60)
    timer.timeout.connect(tick)
    timer.start()
    def status():
        native('pet_rejects_keyboard', pet, True)
        native('status_rejects_keyboard', pet.bubble, True)
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        result['foreground_not_stolen_at_start'] = not front or int(front.processIdentifier()) != os.getpid()
        pet.open_report()
    def report():
        native('report_rejects_keyboard', pet.bubble.report, True)
        pet.open_settings()
        finish_transition()
    def settings():
        native('settings_accepts_keyboard', pet.bubble, False)
        pet.open_chat()
        finish_transition()
    def chat():
        native('chat_accepts_keyboard', pet.bubble, False)
        pet.bubble.return_to_status()
        finish_transition()
    def restored():
        native('status_rejects_keyboard_again', pet.bubble, True)
        pet.bubble.redraw()
        pet.position_bubble()
    def finish():
        timer.stop()
        result['checks']['background_never_key'] = result['passive_key_samples'] == 0
        result['checks']['startup_keeps_external_foreground'] = result['foreground_not_stolen_at_start']
        result['passed'] = all(result['checks'].values())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        pet.close()
    # Stages are spaced to allow the real Cocoa windows and Qt transitions to settle.
    for delay, function in [(1500,status),(3500,report),(5500,settings),(7500,chat),
                            (9500,restored),(13000,finish)]:
        QTimer.singleShot(delay,function)
    app.exec()
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
