"""Run from the downloaded verified program, using the existing install transaction."""
import os,sys
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QLockFile,QTimer
from PySide6.QtWidgets import QApplication
from installer import Installer,DATA,ROOT,startup_preference
from program_updates import verify_ready
from desktop_core import VERSION

def apply_update(source,root=None,data_root=None,progress=lambda *a:None):
    data_root=Path(data_root or DATA);data_root.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(data_root/'deployment.lock'))
    if not lock.tryLock(0):raise OSError('另一个安装程序正在运行，请稍后重试')
    try:
        progress('正在复核程序更新与本地素材，旧版保持运行…')
        verify_ready(source,data_root/'updates',VERSION)
        from directory_deploy import deploy_directory
        return deploy_directory(source,startup_preference(root or ROOT),root=root,data_root=data_root,progress=progress)
    finally:lock.unlock()

class ProgramApplyJob(QThread):
    done=Signal(str);failed=Signal(str);progress=Signal(str)
    def __init__(self,source,parent=None):super().__init__(parent);self.source=source
    def run(self):
        try:self.done.emit(apply_update(self.source,progress=self.progress.emit)['executable'])
        except Exception as exc:self.failed.emit(str(exc)[:300])

class ProgramInstaller(Installer):
    def __init__(self,source):
        self.source=source;super().__init__(quick=True);self.browse.setEnabled(False)
        if not self.existing:QTimer.singleShot(0,self.start)
    def start(self):
        if self.job and self.job.isRunning():return
        self.install_button.setEnabled(False);self.status.setText('正在更新程序，复用本地动画素材…')
        self.job=ProgramApplyJob(self.source,self);self.job.progress.connect(self.status.setText);self.job.done.connect(self.finished);self.job.failed.connect(self.failed);self.job.start()

def main():
    app=QApplication.instance() or QApplication(sys.argv);app.setQuitOnLastWindowClosed(True)
    window=ProgramInstaller(Path(sys.executable).resolve().parent);window.setWindowTitle('白龙桌宠 · 程序更新 '+VERSION);window.show()
    return app.exec()
