"""Explicit SSH opt-in for the current Mac user's existing SSH aliases."""
import json
import re
import sys
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QCheckBox, QLineEdit, QPushButton, QLabel
from desktop_core import atomic_json
from platform_support import ROOT, data_dir


def config_path():
    return data_dir() / 'bridge-config.json'


def read_config():
    try:
        value = json.loads(config_path().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(enabled, host):
    host = host.strip()
    if host and not re.fullmatch(r'[A-Za-z0-9._-]+', host):
        raise ValueError('请填写 ~/.ssh/config 中的 SSH 别名，不要填写命令。')
    if enabled and not host:
        raise ValueError('启用远程会话前，请填写本机的 SSH 别名。')
    value = read_config()
    value.update(enabled=bool(enabled), ssh_host=host)
    atomic_json(config_path(), value)


class BridgeSettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        config = read_config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox('启用 SSH 远程会话回传')
        self.enabled.setChecked(bool(config.get('enabled')))
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.host = QLineEdit(str(config.get('ssh_host', '')))
        self.host.setPlaceholderText('填写本机 ~/.ssh/config 中的别名')
        form.addRow('SSH 别名', self.host)
        layout.addLayout(form)
        self.button = QPushButton('保存并重连 SSH')
        self.button.clicked.connect(self.apply)
        layout.addWidget(self.button)
        self.status = QLabel('仅回传远端会话状态；首次请在终端确认主机指纹并完成 SSH 认证。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self.done)

    def apply(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            save_config(self.enabled.isChecked(), self.host.text())
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.button.setEnabled(False)
        self.status.setText('正在应用 SSH 配置…')
        self.process.start(sys.executable, [str(ROOT / 'launch.py'), 'bridge-restart'])

    def done(self, code, _):
        output = bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace').strip()
        self.status.setText(output[-600:] or ('SSH 配置已应用。' if code == 0 else 'SSH 启动失败，请查看日志。'))
        self.button.setEnabled(True)
