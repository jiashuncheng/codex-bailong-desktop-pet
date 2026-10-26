"""Small status island and quota satellite; no per-frame window movement."""
import math,time,re
from PySide6.QtCore import Qt,QRectF,QSize,QTimer,Signal,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QFontMetrics,QFontMetricsF
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton
from typography import ui_font,FONT_CSS
from reset_watch import epoch
from ui_theme import SURFACE,INK,MUTED,ACCENT,TRACK,ISLAND,ON_ISLAND,QUOTA_WEEK,QUOTA_LOW
from chart_reveal import ChartReveal

WIDTH=222
HEIGHT=44

def valid_percent(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=100

def selected_quota(windows,now=None):
    now=time.time() if now is None else now
    five=next((w for w in windows if w.get('name')=='5小时'),None)
    week=next((w for w in windows if w.get('name')=='一周'),None)
    chosen=five or week or next(iter(windows),dict(name='额度',remaining=None))
    if five:
        reset=epoch(five.get('resetsAt'))
        if not (reset is not None and reset<=now) and valid_percent(five.get('remaining')) and five['remaining']==0 and week:
            chosen=week
    chosen=dict(chosen);reset=epoch(chosen.get('resetsAt'))
    if reset is not None and reset<=now:
        chosen.update(remaining=None,pending=True)
    return chosen

def short_status(icon):
    if getattr(icon,'session_summary',''):return icon.session_summary
    visual=icon.visual()
    if visual=='attention':return '已完成 · 仍有任务' if icon.is_busy() else '已完成'
    if visual=='complete':return '已确认' if icon.is_busy() else '已完成'
    if visual=='busy':return {'thinking':'思考中','responding':'回复中'}.get(icon.state,'执行中')
    if visual=='waiting':return '待操作'
    if visual=='paused':return '已中断'
    if visual=='warning':return '已中断' if icon.state=='interrupted' else '未连接'
    return '待命'

class StatusIsland(QWidget):
    expand=Signal()
    def __init__(self,icon,parent=None):
        super().__init__(parent);self.setObjectName('status_island');self.icon=icon
        self.setFixedSize(132,40);self.setCursor(Qt.CursorShape.PointingHandCursor)
        row=QHBoxLayout(self);row.setContentsMargins(12,0,10,0);row.setSpacing(5)
        row.addWidget(icon);icon.show()
        self.text=QLabel();self.text.setFont(ui_font(12,True));self.text.setStyleSheet('color:'+ON_ISLAND+';background:transparent;')
        self.text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);row.addWidget(self.text,1)
        self.refresh()
    def refresh(self):
        full=short_status(self.icon);budget=self.width()-12-10-16-5-2
        self.text.setFixedWidth(budget);self.text.setFont(ui_font(12,True));text=full
        if QFontMetrics(self.text.font()).horizontalAdvance(text)>budget:
            self.text.setFont(ui_font(11,True))
            for a,b in [('已完成','完成'),('思考中','思考'),('执行中','执行'),('回复中','回复'),('仍有任务','进行中')]:text=text.replace(a,b)
        metrics=QFontMetrics(self.text.font());tail=re.search(r'\s*\+\d+$',text)
        if tail and metrics.horizontalAdvance(text)>budget:
            suffix=tail.group();text=metrics.elidedText(text[:tail.start()],Qt.TextElideMode.ElideRight,max(1,budget-metrics.horizontalAdvance(suffix)))+suffix
        else:text=metrics.elidedText(text,Qt.TextElideMode.ElideRight,budget)
        self.text.setText(text);self.setAccessibleName('Codex · '+full+'；点击打开正常面板')
    def mouseReleaseEvent(self,event):
        window=self.window()
        if hasattr(window,'card_pointer_release') and window.card_pointer_release():event.accept();return
        if event.button()==Qt.MouseButton.LeftButton:self.expand.emit();event.accept()
    def paintEvent(self,event):
        p=QPainter(self);self.paint_dial(p)
    def paint_dial(self,p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#494052'),1));p.setBrush(QColor(ISLAND));p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),22,22)

class QuotaSatellite(QToolButton):
    resetDue=Signal(float)
    def __init__(self,windows,caption,parent=None):
        super().__init__(parent);self.setObjectName('island_quota');self.windows=windows;self.caption=caption
        self.setFixedSize(40,40);self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window=selected_quota(windows)
        self.reveal=ChartReveal(self)
        value=self.window.get('remaining')
        exact=f'{value:g}%' if valid_percent(value) else '等待更新' if self.window.get('pending') else '未知'
        self.setAccessibleName(self.window.get('name','额度')+'剩余 '+exact+'；点击展开详情')
        self._prepare_dial()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._due)
        five=next((w for w in windows if w.get('name')=='5小时'),None)
        self.reset=epoch((five or self.window).get('resetsAt'))
    def showEvent(self,event):
        super().showEvent(event)
        if self.reset:
            self.timer.start(max(1,min(2147483647,math.ceil((self.reset-time.time())*1000))))
    def begin_reveal(self):self.reveal.prepare()
    def start_reveal(self):self.reveal.start()
    def hideEvent(self,event):self.timer.stop();self.reveal.stop();super().hideEvent(event)
    def _due(self):self.resetDue.emit(self.reset)
    def value_text(self):
        value=self.window.get('remaining')
        if not valid_percent(value):return '—'
        if 0<value<1:return '<1%'
        return f'{100 if value==100 else min(99,int(value+.5))}%'
    def _prepare_dial(self):
        # The selected open-arc design has one continuous 270-degree track.
        # Cache all text measurements; reveal frames only change the arc span.
        self._label=self.value_text()
        number=self._label.removesuffix('%');suffix='%' if self._label.endswith('%') else ''
        small=ui_font(11)
        for size in (14,13,12,11,10):
            main=ui_font(size,True);main.setWeight(QFont.Weight.DemiBold);main.setStretch(90)
            metrics=QFontMetricsF(main);bounds=metrics.tightBoundingRect(number)
            suffix_x=metrics.horizontalAdvance(number)+.6
            if suffix:bounds=bounds.united(QFontMetricsF(small).tightBoundingRect(suffix).translated(suffix_x,0))
            if bounds.width()**2+bounds.height()**2<=27.6**2:break
        origin=QPointF(20-bounds.center().x(),20-bounds.center().y())
        self._text_runs=[(main,number,origin)]
        if suffix:self._text_runs.append((small,suffix,origin+QPointF(suffix_x,0)))
        self._label_bounds=bounds.translated(origin)
        value=self.window.get('remaining')
        self._fraction=value/100 if valid_percent(value) else 0.
        self._color=QColor(QUOTA_LOW if valid_percent(value) and value<=15 else ACCENT)
        self._arc=QRectF(3.4,3.4,33.2,33.2)
        self._track_pen=QPen(QColor(TRACK),4.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
        self._value_pen=QPen(self._color,4.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
    def paintEvent(self,event):
        p=QPainter(self);self.paint_dial(p)
    def paint_dial(self,p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#e9e1ef' if self.isDown() else '#f3eef7' if self.underMouse() else SURFACE))
        p.drawEllipse(QRectF(.5,.5,39,39));p.setBrush(Qt.BrushStyle.NoBrush)
        fraction=self._fraction*self.reveal.progress
        p.setPen(self._track_pen);p.drawArc(self._arc,225*16,-270*16)
        if fraction>0:
            p.setPen(self._value_pen);p.drawArc(self._arc,225*16,-max(1,round(270*16*fraction)))
        p.setPen(QColor(INK))
        for font,text,origin in self._text_runs:
            p.setFont(font);p.drawText(origin,text)

class MinimalQuota(QuotaSatellite):
    """A single readable quota circle; dragging never expands the panel."""
    def __init__(self,windows,caption,parent=None):
        super().__init__(windows,caption,parent);self.setObjectName('minimal_quota');self.setFixedSize(54,54)
        self.setAccessibleName(self.accessibleName().replace('展开详情','打开正常卡片')+'；可拖动；右键切换模式')
    def paintEvent(self,event):
        p=QPainter(self);p.scale(self.width()/40,self.height()/40);self.paint_dial(p)
    def mousePressEvent(self,event):
        self.parentWidget().window().card_pointer_press(event);super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.parentWidget().window().card_pointer_move(event):self.setDown(False);event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.parentWidget().window().card_pointer_release():self.setDown(False);event.accept();return
        super().mouseReleaseEvent(event)
