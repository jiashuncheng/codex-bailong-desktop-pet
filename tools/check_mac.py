"""Reproducible Mac checks with isolated data and no real server connections."""
import argparse
import compileall
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

MODULES = [
    'test_capsule_stability', 'test_window_layout', 'test_window_layers',
    'test_notifications', 'test_settings_controls',
    'test_refresh_stability', 'test_active_turn_recovery', 'test_usage_push', 'test_state_push', 'test_shared_sync', 'test_capsule_names', 'test_capsule_sources', 'test_panel_scale', 'test_tray_quota', 'test_native_landing.NativeLandingTests.test_non_native_environment_does_not_call_win32',
    'test_island', 'test_panel_transition', 'test_surface_handoff', 'test_quota_history', 'test_token_sync', 'test_merge_compat', 'test_mac_platform', 'test_source_platform', 'test_quota_summary_data', 'test_spring_motion',
    'test_status_reactions.SchedulerTests', 'test_ring_metrics', 'test_work_actions',
    'test_sustained_reactions', 'test_soft_curves_navigation', 'test_release_version',
    'test_app_updates.ReleaseTests', 'test_app_updates.StagingTests', 'test_loop_cache', 'test_decoder_runtime', 'test_animation_quality',
    'test_sustained_player', 'test_personal_scroll', 'test_action_shuffle',
    'test_read_completion', 'test_completion_expiry', 'test_bridge_names', 'test_local_conversation_names', 'test_conversation_rows',
    'test_material_store', 'test_material_controller', 'test_continuous_work',
    'test_daily_report', 'test_independent_cards', 'test_companion_options', 'test_status_indicator',
    'test_reset_card','test_reset_presentation','test_shortcuts_startup',
    'test_reset_watch','test_reset_recovery','test_audit_fixes','test_chat_config',
    'test_chat_config_ui','test_chat_transport','test_typography','test_liquid_status',
    'test_release_retention','test_local_workflow',
]
MODULES=list(dict.fromkeys(MODULES+['test_storage_locations', 'test_token_calendar', 'test_material_store', 'test_quota_compare_ui', 'test_wsl_codex', 'test_animation_updates', 'test_quota_history', 'test_daily_report', 'test_quota_summary_data', 'test_spring_motion', 'test_status_reactions.SchedulerTests', 'test_ring_metrics', 'test_work_actions', 'test_sustained_reactions', 'test_soft_curves_navigation', 'test_release_version', 'test_app_updates', 'test_loop_cache', 'test_decoder_runtime', 'test_animation_quality', 'test_sustained_player', 'test_program_updates', 'test_status_indicator', 'test_read_completion', 'test_reset_card', 'test_reset_presentation', 'test_reset_watch', 'test_reset_recovery', 'test_audit_fixes', 'test_chat_config', 'test_chat_config_ui', 'test_chat_transport', 'test_typography', 'test_liquid_status', 'test_release_retention', 'test_local_workflow', 'test_tray_history', 'test_tray_quota', 'test_native_landing', 'test_hover_hints', 'test_shared_card_transition', 'test_status_handoff', 'test_decode_geometry', 'test_shortcuts_startup', 'test_entry_icon', 'test_token_rate', 'test_rate_floor', 'test_rate_integration', 'test_live_rate', 'test_quota_workload', 'test_project_cost', 'test_project_cost_reliability', 'test_project_cost_drain', 'test_index_maintenance', 'test_material_incremental', 'test_material_publication', 'test_material_recovery', 'test_stable_tray', 'test_process_launch', 'test_codex_close', 'test_upgrade_settings', 'test_presentation_policy', 'test_transition_recovery', 'test_qt_trim', 'test_locomotion', 'test_large_card_layout', 'test_large_card_morph', 'test_large_chat_ui', 'test_settings_presentation', 'test_live_rate_hover', 'test_runtime_activity']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--modules',nargs='+',help='Run selected isolated regression groups')
    parser.add_argument('--connection', action='store_true')
    parser.add_argument('--require-assets',action='store_true')
    parser.add_argument('--without-assets',action='store_true',help='Run only tests that need no external animations')
    parser.add_argument('--report', type=Path, default=ROOT / '.checks/latest.json')
    args = parser.parse_args()
    if args.connection:
        from codex_connection import check_connection, connection_summary
        report = check_connection()
        print(connection_summary(report))
        return 0 if report['cli_found'] and report['home_exists'] else 1
    began = time.monotonic()
    from version import VERSION,DISPLAY_VERSION
    result = dict(version=VERSION,display_version=DISPLAY_VERSION,platform=sys.platform, python=sys.version.split()[0], passed=True, modules=[], tests=0)
    for folder in ('app', 'tools', 'ssh-bridge', 'sync-service'):
        if not compileall.compile_dir(ROOT / folder, quiet=2):
            result['passed'] = False
    catalog = json.loads((ROOT / 'app/material_catalog.json').read_text())
    missing = []
    base = ROOT / 'outputs/白龙桌宠素材'
    for entry in catalog['tiers']['light']['files']:
        path = base / entry['path']
        if (not path.is_file() or path.stat().st_size != entry['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']):
            missing.append(entry['path'])
    result['light_assets'] = dict(files=len(catalog['tiers']['light']['files']), invalid=missing)
    result['light_assets']['checked']=not missing
    if args.require_assets:result['passed'] &= not missing
    modules=[m for m in (args.modules or MODULES) if m!='test_mac_platform' or sys.platform=='darwin']
    if args.without_assets or missing:
        modules=[m for m in modules if m not in ('test_independent_cards','test_companion_options')]
        modules=['test_shortcuts_startup.StartupTests' if m=='test_shortcuts_startup' else m for m in modules]
    for module in modules + ([] if args.modules else ['bridge-regressions']):
        with tempfile.TemporaryDirectory(prefix='bailong-mac-check-') as temp:
            env = dict(os.environ, LOCALAPPDATA=temp, CODEX_HOME=str(Path(temp) / 'codex'),
                       QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(ROOT / 'app') + os.pathsep + str(ROOT) + os.pathsep + os.environ.get('BAILONG_CHECK_PYTHONPATH',''),
                       BAILONG_SOURCE_ROOT=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            env.pop('BAILONG_DATA_DIR', None)
            command = ([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'ssh-bridge'), '-p', 'test_bridge.py']
                       if module == 'bridge-regressions' else [sys.executable, '-c', "import settings_controls; settings_controls._system_motion_enabled=lambda:True; import unittest; unittest.main(module=None)", module])
            try:
                p = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=100)
                matches = re.findall(r'Ran (\d+) tests?', p.stderr)
                count = int(matches[-1]) if matches else 0
                entry = dict(module=module, passed=p.returncode == 0, tests=count)
                if p.returncode:
                    entry['error'] = (p.stdout + p.stderr)[-6000:]
            except subprocess.TimeoutExpired:
                entry = dict(module=module, passed=False, tests=0, error='100 second timeout')
            result['modules'].append(entry)
            result['tests'] += entry['tests']
            result['passed'] &= entry['passed']
            print(('通过 ' if entry['passed'] else '失败 ') + module + ' · ' + str(entry['tests']) + ' 项', flush=True)
            if not entry['passed']:print(entry.get('error','检查失败'),flush=True)
    result['seconds'] = round(time.monotonic() - began, 1)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('检查完成：' + str(result['tests']) + ' 项，' + ('全部通过' if result['passed'] else '部分失败，详见 ' + str(args.report)))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
