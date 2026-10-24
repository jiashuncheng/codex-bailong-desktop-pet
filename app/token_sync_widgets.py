"""Explicit device pairing, sync scope and connection status for both desktops."""
import json
import time
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QCheckBox,QComboBox,QPushButton,QLabel,QFileDialog
from platform_support import data_dir
from token_sync import read_config,config_path,atomic,import_connection,export_connection

class SyncJob(QThread):
    done=Signal(str);failed=Signal(str)
    def __init__(self,operation,parent=None):super().__init__(parent);self.operation=operation
    def run(self):
        try:self.operation();self.done.emit('同步配置已更新。')
        except Exception as error:self.failed.emit(str(error)[:200])

class TokenSyncPanel(QWidget):
    def __init__(self,pet):
        super().__init__();self.pet=pet;self.job=None;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        config=read_config(data_dir());self.enabled=QCheckBox('启用多端 Token 同步（仅上传统计计数）');self.enabled.setChecked(bool(config.get('enabled')));layout.addWidget(self.enabled)
        self.scope=QComboBox();self.scope.addItem('显示全部设备去重汇总','all');self.scope.addItem('显示本机统计（后台仍同步）','local');self.scope.setCurrentIndex(max(0,self.scope.findData(config.get('view','all'))));layout.addWidget(self.scope)
        self.controls=[]
        for title,callback in [('导入同步连接文件…',self.import_file),('导出另一台设备连接文件…',self.export_file),('保存并立即同步',self.apply)]:
            button=QPushButton(title);button.clicked.connect(callback);layout.addWidget(button);self.controls.append(button)
        self.note=QLabel('首次在另一台设备导入连接文件即可加入。连接文件限一次使用，7 天有效。每 30 秒增量上报，断网后自动补传；聊天正文和登录凭据不上传。');self.note.setWordWrap(True);layout.addWidget(self.note)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.refresh_status);self.timer.start();self.refresh_status()
    def refresh_status(self):
        if self.job and self.job.isRunning():return
        config=read_config(data_dir())
        if not config.get('device_id'):self.status.setText('尚未加入同步服务，请先导入连接文件。');return
        if not config.get('enabled'):self.status.setText('同步已关闭，使用本机统计。');return
        try:status=json.loads((data_dir()/'token-sync-status.json').read_text())
        except (OSError,ValueError):self.status.setText('已配置，等待第一次同步。');return
        if status.get('connected'):
            when=time.strftime('%H:%M:%S',time.localtime(status.get('checked',0)))
            self.status.setText(f"已连接 · {len(status.get('devices',[]))} 台设备 · {when} 更新"+(' · 正在补传历史记录' if status.get('more') else '')+(' · 部分日志不可读' if status.get('scan_errors') else ''))
        else:self.status.setText(status.get('error','同步暂不可用，稍后自动重试。'))
    def wake(self):
        self.pet.refresh_tokens()
    def start_job(self,operation):
        if self.job and self.job.isRunning():return
        for button in self.controls:button.setEnabled(False)
        self.status.setText('正在安全连接同步服务…');self.job=SyncJob(operation,self)
        self.job.done.connect(self.completed);self.job.failed.connect(self.status.setText);self.job.finished.connect(self.finished);self.job.start()
    def finished(self):
        for button in self.controls:button.setEnabled(True)
    def completed(self,message):
        config=read_config(data_dir());self.enabled.setChecked(bool(config.get('enabled')));self.scope.setCurrentIndex(max(0,self.scope.findData(config.get('view','all'))));self.status.setText(message);self.wake()
    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'导入同步连接文件','','白龙同步连接 (*.bailong-sync);;所有文件 (*)')
        if not path:return
        def operation():
            if Path(path).stat().st_size>65536:raise ValueError('连接文件过大。')
            import_connection(data_dir(),json.loads(Path(path).read_text(encoding='utf-8')))
        self.start_job(operation)
    def export_file(self):
        path,_=QFileDialog.getSaveFileName(self,'导出供另一台设备使用的连接文件','白龙Token同步.bailong-sync','白龙同步连接 (*.bailong-sync)')
        if path:self.start_job(lambda:export_connection(data_dir(),path))
    def apply(self):
        config=read_config(data_dir())
        if self.enabled.isChecked() and not config.get('device_id'):self.status.setText('请先导入连接文件。');return
        config.update(enabled=self.enabled.isChecked(),view=self.scope.currentData());atomic(config_path(data_dir()),config);self.wake();self.refresh_status()
