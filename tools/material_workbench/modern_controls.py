"""Quiet rounded dropdowns with a consistent popup on Windows and macOS."""
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QPointF,Signal
from PySide6.QtGui import QColor,QPen,QPolygonF,QPainter
from PySide6.QtWidgets import QComboBox,QListView,QStyledItemDelegate,QStyle,QPushButton,QMenu,QWidgetAction,QCheckBox

def dropdown_style():
    arrow=(Path(__file__).parent/'icons/chevron-down.svg').as_posix()
    return '''
QComboBox { background:#ffffff; color:#252525; border:1px solid #dedee3; border-radius:10px; padding:7px 32px 7px 11px; min-height:20px; }
QComboBox:hover { background:#f7f7f8; border-color:#ccccd2; }
QComboBox:focus { border-color:#a8a8b2; }
QComboBox:disabled { color:#a4a4ac; background:#f5f5f6; border-color:#e8e8ec; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; width:28px; border:0; background:transparent; }
QComboBox::down-arrow { image:url("'''+arrow+'''"); width:14px; height:14px; }
QComboBox QAbstractItemView { background:white; color:#202020; border:1px solid #dedee3; border-radius:10px; padding:5px; outline:0; selection-background-color:#f0f0f2; selection-color:#202020; }
QMenu { background:#ffffff; color:#252525; border:1px solid #dedee3; border-radius:12px; padding:7px; }
QMenu::item { padding:8px 12px; border-radius:7px; }
QMenu::item:selected { background:#f1f1f3; }
QPushButton#encodingSelector { background:white; color:#252525; border:1px solid #dedee3; border-radius:10px; padding:8px 30px 8px 12px; text-align:left; }
QPushButton#encodingSelector:hover { background:#f7f7f8; }
QPushButton#encodingSelector::menu-indicator { image:url("'''+arrow+'''"); width:14px; height:14px; subcontrol-position:right center; right:9px; }
QCheckBox#encodingChoice { color:#252525; padding:8px; border-radius:8px; spacing:9px; }
QCheckBox#encodingChoice:hover { background:#f3f3f5; }
'''

class MenuDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        hint=super().sizeHint(option,index);return QSize(hint.width()+36,max(34,hint.height()+14))
    def paint(self,painter,option,index):
        painter.save();rect=option.rect.adjusted(2,1,-2,-1)
        if option.state & (QStyle.StateFlag.State_Selected|QStyle.StateFlag.State_MouseOver):
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#f0f0f2'));painter.drawRoundedRect(rect,7,7)
        painter.setPen(QColor('#252525'));painter.setFont(option.font)
        text=option.fontMetrics.elidedText(str(index.data() or ''),Qt.TextElideMode.ElideRight,max(10,rect.width()-42))
        painter.drawText(rect.adjusted(9,0,-29,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,text)
        combo=self.parent()
        if index.row()==combo.currentIndex():
            x=rect.right()-17;y=rect.center().y();painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor('#303030'),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(QPolygonF([QPointF(x-4,y),QPointF(x-1,y+3),QPointF(x+5,y-4)]))
        painter.restore()

class ModernComboBox(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);view=QListView(self);view.setMouseTracking(True);view.setSpacing(1);view.setUniformItemSizes(True)
        self.setView(view);self.setItemDelegate(MenuDelegate(self));self.setMaxVisibleItems(10)
    def showPopup(self):
        longest=max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())),default=80)
        self.view().setMinimumWidth(min(540,max(self.width(),longest+58)));super().showPopup()

class EncodingSelector(QPushButton):
    changed=Signal()
    def __init__(self,values=None,parent=None):
        super().__init__(parent);self.setObjectName('encodingSelector');self.boxes={};menu=QMenu(self);menu.setMinimumWidth(320);self.setMenu(menu)
        from encoding_presets import PRESETS
        for code,info in PRESETS.items():
            box=QCheckBox(info['label']+'\n'+info['description']);box.setObjectName('encodingChoice');box.setMinimumHeight(52)
            action=QWidgetAction(menu);action.setDefaultWidget(box);menu.addAction(action);self.boxes[code]=box
            box.setChecked(code in (values or []));box.toggled.connect(self.selection_changed)
        self.selection_changed()
    def values(self):return [code for code,box in self.boxes.items() if box.isChecked()]
    def set_estimates(self,values):
        from encoding_presets import PRESETS
        from size_estimation import format_estimate
        for code,box in self.boxes.items():
            info=PRESETS[code];box.setText(info['label']+'\n'+info['description']+'\n'+format_estimate((values or {}).get(code)));box.setMinimumHeight(70)
    def selection_changed(self,*args):
        from encoding_presets import PRESETS
        selected=self.values();self.setText('导出档位 · 已选 '+str(len(selected))+' 项')
        self.setToolTip('可多选，同时生成供对比：'+('、'.join(PRESETS[c]['label'] for c in selected) or '请至少选择一项'))
        self.changed.emit()
