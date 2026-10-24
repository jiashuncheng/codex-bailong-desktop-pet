"""Source update controls for the editable Mac edition."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from platform_support import ROOT, MAC_VERSION
from version import VERSION


class SourceMaintenancePanel(QWidget):
    def __init__(self, pet):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('跨平台源码版 ' + VERSION + ' · 保留个性化修改\n'
                      '修改后双击“一键启动”；另一台机器运行“同步更新源码”。\n'
                      '依赖清单有变化时，启动脚本会自动补装。')
        note.setWordWrap(True)
        layout.addWidget(note)
        button = QPushButton('打开源码目录')
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT))))
        layout.addWidget(button)
        button = QPushButton('查看跨平台使用与同步说明')
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'docs/跨平台源码使用.md'))))
        layout.addWidget(button)
        button = QPushButton('打开日志与数据目录')
        button.clicked.connect(pet.open_data)
        layout.addWidget(button)
