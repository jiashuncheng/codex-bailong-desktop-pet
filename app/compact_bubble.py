"""Compact, accessible quota dials; full information remains in the details view."""
import math
import time
from PySide6.QtCore import Qt,QRectF,QSize,Signal,QTimer,QVariantAnimation,QEasingCurve,QAbstractAnimation
from PySide6.QtGui import QColor,QFont,QFontMetrics,QPainter,QPen,QTextLayout,QTextOption,QIcon,QPixmap,QPolygonF,QPalette
from PySide6.QtCore import QPointF,QObject,QEvent
from PySide6.QtWidgets import QWidget,QLabel,QHBoxLayout,QVBoxLayout,QToolButton,QApplication,QStackedWidget,QLayout,QToolTip
from panel_transition import PanelTransition
from surface_morph import PANEL_RADIUS
from status_indicator import StatusIndicator
from refresh_indicator import RefreshButton
from pet import Bubble
from enhanced_core import clean_text
from typography import FONT_FAMILIES,FONT_CSS,ui_font
from ui_theme import editor_stylesheet,PRIMARY,ACCENT,SELECTED,DISABLED
from reset_watch import epoch,local_time,schedule_text,account_reset_text,SOURCE_URL,pending_reset,schedule_key,locally_reset,reset_has_priority

INK=QColor('#393343');MUTED=QColor('#706879');PURPLE=QColor('#8b78a6')
GREEN=QColor('#b3a5cb');AMBER=QColor('#915e74');TRACK=QColor('#e4dfea')
CARD_HEIGHT=90

def action_icon(kind):
    pixmap=QPixmap(32,32);pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(2,2)
    p.setPen(QPen(QColor('#75618d'),1.9,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if kind=='refresh':
        p.drawArc(QRectF(3,3,10,10),20*16,290*16)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#75618d'));p.drawPolygon(QPolygonF([QPointF(14,2.5),QPointF(14,7),QPointF(9.5,5)]))
    elif kind=='external':
        p.drawLine(9,3,13,3);p.drawLine(13,3,13,7);p.drawLine(7,9,13,3)
        p.drawPolyline(QPolygonF([QPointF(6,3),QPointF(3,3),QPointF(3,13),QPointF(13,13),QPointF(13,10)]))
    elif kind=='details':
        p.drawLine(3,4,10,4);p.drawLine(3,8,8,8);p.drawLine(3,12,8,12)
        p.drawLine(11,8,14,11);p.drawLine(14,11,11,14)
    elif kind=='collapse':p.drawLine(3,8,13,8)
    elif kind=='compact':
        p.drawRoundedRect(QRectF(2,5,12,6),3,3);p.drawLine(6,3,10,3);p.drawLine(6,13,10,13)
    elif kind=='expand':
        p.drawLine(4,6,8,2);p.drawLine(8,2,12,6);p.drawLine(4,10,8,14);p.drawLine(8,14,12,10)
    elif kind=='close':p.drawLine(4,4,12,12);p.drawLine(12,4,4,12)
    elif kind=='report':
        p.drawRoundedRect(QRectF(3,2,10,12),1.5,1.5)
        p.drawLine(6,10,6,8);p.drawLine(8,10,8,5);p.drawLine(10,10,10,7)
    elif kind=='book':
        p.setPen(QPen(QColor('#75618d'),1.4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(2,4),QPointF(5,3),QPointF(8,4),QPointF(11,3),QPointF(14,4),QPointF(14,11),QPointF(11,10),QPointF(8,11),QPointF(5,10),QPointF(2,11),QPointF(2,4)]))
        p.drawLine(8,4,8,11);p.drawLine(QPointF(6,13.5),QPointF(11,13.5));p.drawLine(QPointF(9,12),QPointF(11,13.5));p.drawLine(QPointF(11,13.5),QPointF(9,15))
    elif kind=='settings':
        p.drawEllipse(QRectF(4,4,8,8));p.drawEllipse(QRectF(6.5,6.5,3,3))
        for angle in range(0,360,45):
            a=math.radians(angle);p.drawLine(QPointF(8+4*math.cos(a),8+4*math.sin(a)),QPointF(8+6*math.cos(a),8+6*math.sin(a)))
    elif kind=='chat':
        p.drawRoundedRect(QRectF(2,3,12,9),2,2);p.drawLine(5,12,4,14);p.drawLine(4,14,8,12)
    elif kind=='web':
        p.drawEllipse(QRectF(2,2,12,12));p.drawEllipse(QRectF(5,2,6,12));p.drawLine(2,8,14,8)
    elif kind=='code':
        p.drawPolyline(QPolygonF([QPointF(5,4),QPointF(1,8),QPointF(5,12)]))
        p.drawPolyline(QPolygonF([QPointF(11,4),QPointF(15,8),QPointF(11,12)]));p.drawLine(9,3,7,13)
    elif kind=='pin':
        p.drawLine(5,3,11,3);p.drawLine(6,3,6,7);p.drawLine(10,3,10,7)
        p.drawLine(6,7,4,10);p.drawLine(4,10,12,10);p.drawLine(12,10,10,7);p.drawLine(8,10,8,14)
    elif kind=='move':
        p.drawLine(2,8,14,8);p.drawLine(8,2,8,14)
        for a,b,c in [(QPointF(4,6),QPointF(2,8),QPointF(4,10)),(QPointF(12,6),QPointF(14,8),QPointF(12,10)),(QPointF(6,4),QPointF(8,2),QPointF(10,4)),(QPointF(6,12),QPointF(8,14),QPointF(10,12))]:p.drawPolyline(QPolygonF([a,b,c]))
    p.end();return QIcon(pixmap)

def action_button(kind,tip,text='',parent=None,hit_size=20,keyboard=False,under=False):
    button=RefreshButton(parent) if kind=='refresh' else QToolButton(parent)
    button.setObjectName('bubble_'+kind)
    if kind!='refresh':button.setIcon(action_icon(kind))
    button.setIconSize(QSize(18,18) if kind=='refresh' else QSize(16,16))
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus if keyboard else Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(tip);button.setAccessibleName(tip)
    button.setStyleSheet('QToolButton{'+FONT_CSS+f'border:0;border-radius:6px;color:{PRIMARY};background:transparent;font-size:11px;padding:0;}}QToolButton:hover{{background:#f0eaf5;}}QToolButton:pressed{{background:#e0d3eb;}}QToolButton:checked{{background:{SELECTED};}}QToolButton:disabled{{color:{DISABLED};}}QToolButton:focus{{border:0;background:{SELECTED};}}')
    if text:
        button.setText(text);button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if under else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if under:button.setFixedSize(hit_size,36)
        else:button.setFixedHeight(28)
    else:button.setFixedSize(hit_size,hit_size)
    return button

def font(px,bold=False):
    return ui_font(px,bold)

def caption_brief(value):
    if '上次记录' in value:return '上次记录'
    if '暂不可用' in value:return '暂不可用'
    text=value.removeprefix('额度 · ').replace('会话记录','会话')
    if '待刷新' in text:return '待刷新 · '+text.split(' · ')[0].split(' ')[-1]
    return text

def reset_brief(value,now=None):
    stamp=epoch(value);now=time.time() if now is None else now
    if stamp is None:return '时间未提供'
    if stamp<=now:return '已到期 · 待刷新'
    return local_time(stamp)

def schedule_brief(snapshot):
    item=(snapshot or {}).get('scheduled')
    if snapshot is None:return '重置消息查询中…'
    if not item:return '额外重置 · 暂未公布'
    name='备用' if item.get('reset_type')=='banked' else '额外'
    stamp=epoch(item.get('scheduled'))
    if stamp is None:return name+'重置 · 时间待定'
    if stamp<=time.time():return name+' '+local_time(stamp)+' · 待确认'
    return name+' ≤ '+local_time(stamp)

class Summary(QWidget):
    """At most two lines; elision has a tooltip and an explicit expansion control."""
    expand=Signal()
    def __init__(self,text,width,parent=None):
        super().__init__(parent);self.text=text;self.setFixedWidth(width);self.setFont(font(12))
        self.setToolTip(text);self.setAccessibleName('Codex 状态：'+text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.line_height=max(18,QFontMetrics(self.font()).height()+2)
        self.lines=self.wrap(text,width);self.setFixedHeight(max(self.line_height,len(self.lines)*self.line_height))
    def wrap(self,text,width):
        text=text.replace('\n','  ')
        layout=QTextLayout(text,self.font());option=QTextOption();option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);layout.setTextOption(option)
        layout.beginLayout();result=[]
        for index in range(2):
            line=layout.createLine()
            if not line.isValid():break
            line.setLineWidth(width);start=line.textStart();length=line.textLength()
            if index==1:result.append(QFontMetrics(self.font()).elidedText(text[start:],Qt.TextElideMode.ElideRight,width))
            else:result.append(text[start:start+length].rstrip())
        layout.endLayout();return result or ['等待 Codex 新消息']
    def paintEvent(self,event):
        p=QPainter(self);p.setFont(self.font());p.setPen(INK)
        for i,line in enumerate(self.lines):p.drawText(QRectF(0,i*self.line_height,self.width(),self.line_height),Qt.AlignmentFlag.AlignVCenter,line)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.expand.emit()

class StatusScroller(QLabel):
    scrollRequested=Signal(int)
    """Persistent clipped viewport: old text moves up, new text enters below.

    A burst retains one latest pending message, not an ever-growing queue.
    Quota/token redraws never recreate this widget or restart its animation.
    """
    expand=Signal()
    conversationRequested=Signal(str)
    heightChanged=Signal()
    def __init__(self,width,parent=None):
        super().__init__('',parent);self.setFixedWidth(width);self.setFont(font(12));self.setTextFormat(Qt.TextFormat.PlainText)
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.line_height=max(18,QFontMetrics(self.font()).height()+2)
        self.full=False;self.current='';self.incoming='';self.pending=None;self.progress=1.;self.initialized=False
        self.conversation_rows=False;self.extra=0;self.single_line=False;self.rows={};self.row_positions={}
        self.conversation_title='';self.conversation_id='';self.completed=False;self.short_title='';self.title_width=0;self.title_suffix=''
        self.name_hovered=False;self.name_pressed=False;self.setMouseTracking(True)
        self.overflow=QToolButton(self);self.overflow.setObjectName('conversation_overflow');self.overflow.setFixedSize(26,20);self.overflow.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.overflow.hide()
        self.overflow.setStyleSheet('QToolButton{'+FONT_CSS+'color:#514360;background:#eee8f3;border:0;border-radius:5px;font-size:11px;}QToolButton:hover{background:#e4dbea;}')
        self.animation=QVariantAnimation(self);self.animation.setDuration(300);self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic);self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._finish)
        self._from_height=self._to_height=self.line_height;self._scroll_distance=self.line_height+4
        self.setFixedHeight(self.line_height)
    # QLabel's cached text hint does not describe our animated viewport. The
    # outer layout must follow its current height, not a previous two-line hint.
    def sizeHint(self):return QSize(self.width(),self.height())
    def minimumSizeHint(self):return self.sizeHint()
    def hasHeightForWidth(self):return False
    def lines_for(self,text):
        width=self.width()-(30 if self.extra else 0)-2
        if self.single_line:return [QFontMetrics(self.font()).elidedText(text,Qt.TextElideMode.ElideRight,max(1,width-self.text_left()-4))]
        text=text.replace('\n','  ');layout=QTextLayout(text,self.font());option=QTextOption();option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);layout.setTextOption(option)
        layout.beginLayout();lines=[]
        while True:
            line=layout.createLine()
            if not line.isValid():break
            line.setLineWidth(width);start=line.textStart();length=line.textLength()
            if not self.full and len(lines)==1:
                lines.append(QFontMetrics(self.font()).elidedText(text[start:],Qt.TextElideMode.ElideRight,self.width()));break
            lines.append(text[start:start+length].rstrip())
        layout.endLayout();return lines or ['等待 Codex 新消息']
    def _set_height(self,value):
        height=round(float(value))
        if height!=self.height():self.setFixedHeight(height);self.heightChanged.emit()
        self.overflow.move(self.width()-26,max(0,(self.height()-20)//2))
    def resizeEvent(self,event):
        self.overflow.move(self.width()-26,max(0,(self.height()-20)//2))
        for row in self.rows.values():row.setFixedWidth(max(1,self.width()-(30 if self.extra else 0)))
        self.layout_title()
        super().resizeEvent(event)
    def text_left(self):return self.title_width+14 if self.conversation_title else 0
    def layout_title(self):
        if not self.conversation_title:self.title_width=0;return
        from conversation_roster import title_keywords
        metrics=QFontMetrics(font(12,True));budget=min(112,round(self.width()*.42))
        self.short_title=metrics.elidedText(title_keywords(self.conversation_title),Qt.TextElideMode.ElideMiddle,max(1,budget-metrics.horizontalAdvance(self.title_suffix)))+self.title_suffix
        self.title_width=metrics.horizontalAdvance(self.short_title)
    def wheelEvent(self,event):
        if self.conversation_rows or self.conversation_id:
            delta=event.angleDelta().y()
            if delta:self.scrollRequested.emit(1 if delta<0 else -1)
            event.accept()
        else:super().wheelEvent(event)
    def set_conversations(self,items,extra=0,full=False,metadata=None):
        """Each session owns its text clock; the parent animates only row layout."""
        items=items[:2];keys=[sid for sid,text in items]
        old_keys=list(self.rows);changed_mode=self.full!=full or not self.conversation_rows
        self.conversation_rows=True;self.full=full;self.extra=extra
        metadata=metadata or {}
        joined='\n'.join((metadata.get(sid,{}).get('title','')+' · '+text).strip(' ·') for sid,text in items);super().setText(joined)
        self.setToolTip(joined);self.setAccessibleName('Codex 状态：'+joined)
        for sid in old_keys:
            if sid not in keys:
                row=self.rows.pop(sid);row.animation.stop();row.hide();row.deleteLater()
        start={sid:row.y() for sid,row in self.rows.items()}
        for index,(sid,text) in enumerate(items):
            row=self.rows.get(sid)
            if row is None:
                row=StatusScroller(self.width(),self);row.single_line=True
                row.expand.connect(self.expand.emit);row.conversationRequested.connect(self.conversationRequested.emit);row.scrollRequested.connect(self.scrollRequested.emit);self.rows[sid]=row
                start[sid]=index*self.line_height
            row.setFixedWidth(max(1,self.width()-(30 if extra else 0)))
            info=metadata.get(sid,{})
            row.conversation_id=sid;row.conversation_title=info.get('title','');row.completed=info.get('state')=='complete';row.title_suffix='';row.layout_title()
            row.set_status(text)
            row.setAccessibleName((row.conversation_title+' · '+text).strip(' ·'));row.show();row.update()
        self.rows={sid:self.rows[sid] for sid in keys}
        names=[row.short_title for row in self.rows.values()]
        for sid,row in self.rows.items():
            if row.conversation_title and names.count(row.short_title)>1:
                row.title_suffix=' '+sid[-3:];row.layout_title()
        self.current=self.incoming=joined;self.pending=None;self.initialized=True
        target=max(1,len(items))*self.line_height
        if old_keys!=keys or changed_mode or not self.isVisible():
            self.animation.stop();self.row_positions={sid:(start[sid],index*self.line_height) for index,sid in enumerate(keys)}
            self._from_height=self.height();self._to_height=target
            moving=self.height()!=target or any(start[sid]!=index*self.line_height for index,sid in enumerate(keys))
            if self.isVisible() and not changed_mode and moving:
                self.progress=0.;self.animation.start()
            else:self._advance(1.)
        self.overflow.raise_();self.update()
    def clear_conversations(self):
        if not self.conversation_rows:return
        self.animation.stop()
        for row in self.rows.values():row.animation.stop();row.hide();row.deleteLater()
        self.rows={};self.row_positions={};self.conversation_rows=False;self.initialized=False
    def _height(self,*texts):
        height=max(len(self.lines_for(t)) for t in texts)*self.line_height
        self._from_height=self._to_height=height;self._scroll_distance=height+4;self._set_height(height)
    def set_status(self,text,full=False):
        changed_mode=self.full!=full;self.full=full
        same=text==self.text();super().setText(text);self.setToolTip(text);self.setAccessibleName('Codex 状态：'+text)
        if not self.initialized or changed_mode or not self.isVisible():
            self.animation.stop();self.current=self.incoming=text;self.pending=None;self.progress=1.;self.initialized=True;self._height(text);self.update();return
        if same:return
        if self.animation.state()==QAbstractAnimation.State.Running:
            self.pending=text;return
        self._start(text)
    def _start(self,text):
        if text==self.current:return
        self.incoming=text;self.pending=None
        self._from_height=self.height();self._to_height=len(self.lines_for(text))*self.line_height
        # Freeze travel distance for this transition: changing viewport height
        # must not also change the text's speed or create a second resize phase.
        self._scroll_distance=max(self._from_height,len(self.lines_for(self.current))*self.line_height)+4
        self.progress=0.;self.animation.start();self.update()
    def _advance(self,value):
        self.progress=float(value)
        self._set_height(self._from_height+(self._to_height-self._from_height)*self.progress)
        for sid,(start,end) in self.row_positions.items():
            if sid in self.rows:self.rows[sid].move(0,round(start+(end-start)*self.progress))
        self.update()
    def _finish(self):
        self.current=self.incoming;self.progress=1.;self._set_height(self._to_height);self.update()
        pending=self.pending;self.pending=None
        if pending is not None and pending!=self.current:QTimer.singleShot(0,self._continue_latest)
    def _continue_latest(self):
        if self.animation.state()!=QAbstractAnimation.State.Running and self.text()!=self.current:self._start(self.text())
    def offsets(self):
        distance=self._scroll_distance
        return -self.progress*distance,(1-self.progress)*distance
    def hideEvent(self,event):
        self.name_hovered=False;self.name_pressed=False
        for row in self.rows.values():
            row.animation.stop();row.current=row.incoming=row.text();row.pending=None;row.progress=1.
        super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setClipRect(0,0,self.width()-(30 if self.extra else 0),self.height());p.setFont(self.font());p.setPen(INK)
        if self.full:
            p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setBrush(QColor('#f5f1f7'));p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(self.rect()),5,5);p.setPen(INK)
        if self.conversation_rows:return
        if self.completed:
            p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor('#dacee6'),1));p.setBrush(QColor('#eee7f4'))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),5,5)
        left=self.text_left()
        if self.conversation_title:
            if self.name_hovered or self.name_pressed:
                p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor('#806095' if self.name_pressed else '#a087b3'),1))
                p.setBrush(QColor('#c5add9' if self.name_pressed else '#dfcfeb'));p.drawRoundedRect(QRectF(1,1,left-4,self.height()-2),4,4)
            offset=1 if self.name_pressed else 0
            title_font=font(12,True);title_font.setUnderline(self.name_hovered or self.name_pressed)
            p.setFont(title_font);p.setPen(QColor('#30203e' if self.name_pressed else '#472c5d' if self.name_hovered else '#665078'))
            p.drawText(QRectF(5+offset,offset,self.title_width,self.height()),Qt.AlignmentFlag.AlignVCenter,self.short_title)
            p.setPen(QColor('#c1b4cc'));p.drawLine(left-5,5,left-5,self.height()-5)
        p.setFont(self.font());p.setPen(INK);p.setClipRect(left,0,max(0,self.width()-left-(30 if self.extra else 0)),self.height())
        def draw(text,y):
            for i,line in enumerate(self.lines_for(text)):p.drawText(QRectF(left,y+i*self.line_height,self.width()-left,self.line_height),Qt.AlignmentFlag.AlignVCenter,line)
        if self.animation.state()==QAbstractAnimation.State.Running:
            old_y,new_y=self.offsets();draw(self.current,old_y);draw(self.incoming,new_y)
        else:draw(self.current,0)
    def _on_name(self,point):
        return bool(self.conversation_id and self.conversation_title and self.rect().contains(point.toPoint()) and 0<=point.x()<self.text_left())
    def mouseMoveEvent(self,event):
        hovered=self._on_name(event.position())
        if hovered!=self.name_hovered:self.name_hovered=hovered;self.update()
        super().mouseMoveEvent(event)
    def leaveEvent(self,event):
        self.name_hovered=False;self.update();super().leaveEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self._on_name(event.position()):
            self.name_pressed=True;self.name_hovered=True;self.update();event.accept();return
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        was_pressed=self.name_pressed;self.name_pressed=False;self.update()
        if event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            if self._on_name(event.position()) and was_pressed:
                self.conversationRequested.emit(self.conversation_id)
            elif was_pressed:return
            elif not self.full:self.expand.emit()

class QuotaDial(QWidget):
    """240 degree dial; its lower opening is the quota window legend."""
    def __init__(self,window,caption='',alternate=False,parent=None):
        super().__init__(parent);self.window=dict(window);self.caption=caption;self.alternate=alternate
        self.setFixedHeight(CARD_HEIGHT);self.setMinimumWidth(106)
        value=window.get('remaining');self.remaining=value
        self.name=str(window.get('name','额度'))
        percent=f'{value:g}%' if value is not None else '未提供'
        full=f'{self.name} · 剩余 {percent}\n{account_reset_text(window.get("resetsAt"))}（北京时间）\n{caption}'
        self.setToolTip(full);self.setAccessibleName(self.name+'剩余额度');self.setAccessibleDescription(full)
    def sizeHint(self):return QSize(116,CARD_HEIGHT)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#f5f2f7'));p.drawRoundedRect(QRectF(self.rect()),11,11)
        cx=self.width()/2;rect=QRectF(cx-26,5,52,52)
        p.setPen(QPen(TRACK,4.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.drawArc(rect,210*16,-240*16)
        value=self.remaining
        color=AMBER if value is not None and value<=15 else GREEN if self.alternate else PURPLE
        if value is not None and value>0:
            p.setPen(QPen(color,4.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            p.drawArc(rect,210*16,-round(240*16*max(0,min(100,value))/100))
        p.setFont(font(17,True));p.setPen(color if value is not None and value<=15 else INK)
        p.drawText(QRectF(3,17,self.width()-6,24),Qt.AlignmentFlag.AlignCenter,f'{value:g}%' if value is not None else '—')
        p.setFont(font(11,True));p.setPen(INK)
        p.drawText(QRectF(3,47,self.width()-6,15),Qt.AlignmentFlag.AlignCenter,self.name+'剩余')
        p.setFont(font(11));p.setPen(AMBER if epoch(self.window.get('resetsAt')) and epoch(self.window.get('resetsAt'))<=time.time() else MUTED)
        text=reset_brief(self.window.get('resetsAt'))
        text_width=QFontMetrics(p.font()).horizontalAdvance(text);left=(self.width()-text_width-15)/2
        # A vector clock avoids thin/missing Unicode reset glyphs in font fallback.
        clock_color=p.pen().color();p.setPen(QPen(clock_color,1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(left,70,10,10));p.drawLine(QPointF(left+5,72.5),QPointF(left+5,75));p.drawLine(QPointF(left+5,75),QPointF(left+7.5,76.5))
        p.drawText(QRectF(left+15,65,text_width+1,20),Qt.AlignmentFlag.AlignVCenter,text)

from reset_card import ResetCard as Announcement

def source_button(parent=None,compact=False):
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl
    button=QToolButton(parent);button.setText('Resets' if compact else 'Codex Resets');button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setIcon(action_icon('external'));button.setIconSize(QSize(13,13));button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet('QToolButton{'+FONT_CSS+'font-size:11px;color:#75618d;border:0;padding:0;background:transparent;} QToolButton:hover{color:#514360;}')
    button.setToolTip('来源：Codex Resets（第三方）\n点击打开原始公告；预计时间不等于账户额度已到账。')
    button.setAccessibleName('打开 Codex Resets 第三方公告来源')
    button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(SOURCE_URL)));return button

class InlineExplanationOnly(QObject):
    """Keep accessible descriptions and inline hints, suppress native tooltip windows."""
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.ToolTip and isinstance(obj,QWidget):
            bubble=self.parent()
            if obj is bubble or bubble.isAncestorOf(obj):
                QToolTip.hideText();event.accept();return True
        return False

class CompactBubble(Bubble):
    reportRequested=Signal()
    refreshAllRequested=Signal()
    quotaRefreshRequested=Signal()
    resetRefreshRequested=Signal()
    tokenRefreshRequested=Signal()
    tokenRangeChanged=Signal(str)
    settingsRequested=Signal()
    chatRequested=Signal()
    shortcutRequested=Signal()
    codexRequested=Signal()
    conversationRequested=Signal(str)
    optionRequested=Signal(str,bool)
    modeChanged=Signal(str)
    dataBusyChanged=Signal(str,bool)
    def __init__(self,owner=None):
        super().__init__();self._owner=owner;self.setParent(owner,self.windowFlags())
        self.report=None;self.inline_explanations=InlineExplanationOnly(self);QApplication.instance().installEventFilter(self.inline_explanations)
        self.content=QWidget(self);self.content.setLayout(self.layout);self.content.setFixedWidth(268);self.content.show()
        self.setFixedWidth(268);self.layout.setContentsMargins(10,6,10,6);self.layout.setSpacing(3)
        self.layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setFont(font(12));self.setStyleSheet('QLabel{'+FONT_CSS+'font-weight:500;color:#393343;font-size:12px;background:transparent;}')
        self.windows=[];self.status='已启动，正在连接 Codex…';self.heading='白龙 · Codex 桌面伙伴'
        self.quota_caption='额度加载中…';self.reset_snapshot=None;self.reset_feed_error=False;self.reset_error_details=None
        self.show_quota=True;self.enabled=True;self.expanded=False
        self.bubble_mode='auto';self.auto_compact=False;self._minimal_normal_open=False;self._last_compact_surface=None
        self.last_task_update=time.monotonic();self.codex_open=None
        self._manual_grace_until=0.;self._pending_mode=None;self._pending_navigation=None
        self.quota_busy=False;self.reset_busy=False;self.pinned=True;self.wandering=True;self.movement_locked=False
        self.quota_refresh_button=None;self.reset_refresh_buttons=[];self.token_refresh_buttons=[];self.token_busy=False
        self.refresh_busy=False
        self.refresh_button=action_button('refresh','刷新额度、Token 与重置公告',parent=self.content,hit_size=28)
        self.refresh_button.setObjectName('bubble_refresh_all');self.refresh_button.clicked.connect(self.request_refresh_all)
        self.refresh_button.hide()
        self.token_snapshot=None;self.dashboard_page='tokens';self.deck=None;self.today_tokens_card=None;self._active_reset_key=None;self._ring_values={}
        self.token_range='all';self.detail_tab='quota';self.details_tabs=None;self.detail_scroll={}
        self._chart_entry=False;self._plot_resume=None
        from conversation_roster import ConversationRoster
        self.roster=ConversationRoster();self._roster_pending=False
        self.panel_page='status';self._editor_origin=None;self._editor_positioned=False;self.editor_stack=QStackedWidget(self);self.editor_stack.hide();self.editor_title=None
        self.editor_stack.setObjectName('integrated_contents')
        self.editor_stack.setStyleSheet(editor_stylesheet(FONT_CSS))
        palette=QPalette()
        for role,color in ((QPalette.ColorRole.WindowText,'#393343'),(QPalette.ColorRole.Text,'#393343'),(QPalette.ColorRole.ButtonText,'#514360'),(QPalette.ColorRole.Window,'#f5f2f7'),(QPalette.ColorRole.Base,'#fcfafc'),(QPalette.ColorRole.Button,'#eee7f5'),(QPalette.ColorRole.Highlight,'#dacbe8'),(QPalette.ColorRole.HighlightedText,'#352840'),(QPalette.ColorRole.PlaceholderText,'#786d84')):
            palette.setColor(role,QColor(color))
        self.editor_stack.setPalette(palette)
        self.status_indicator=StatusIndicator(self.content)
        self.island=None;self.minimal_quota=None;self.shortcut_button=None;self.capsule_action='chatgpt';self._quota_reset_requested=None;self._card_press=None;self._card_dragged=False
        self.status_indicator.changed.connect(self._refresh_island_status)
        self.size_transition=PanelTransition(self)
        self.size_transition.animation.finished.connect(self._apply_pending_mode)
        self._redrawing=False;self._fitting_height=False;self.status_view=StatusScroller(248,self);self.status_view.expand.connect(self.toggle_details)
        self.status_view.conversationRequested.connect(self.conversationRequested.emit)
        self.status_view.overflow.clicked.connect(lambda:self.cycle_conversations())
        self.status_view.scrollRequested.connect(self.cycle_conversations)
        self.conversation_auto_scroll=True
        self.conversation_timer=QTimer(self)
        self.conversation_timer.setInterval(3000)
        self.conversation_timer.timeout.connect(self._auto_cycle_conversations)
        self.conversation_timer.start()
        self.status_view.setToolTip('每隔 3 秒只替换一条会话；另一条保持原位，悬停暂停，滚轮可手动切换')
        self.status_view.heightChanged.connect(self._status_height_changed)
        self.status_view.animation.finished.connect(self._status_height_finished)
        self.setWindowTitle('白龙增强版 · 状态气泡');self.redraw()
    def clear(self):
        # Headers are rebuilt; the tiny task animation must keep its clock.
        self._plot_resume=None;self.deck=None
        self.shortcut_button=None
        for widget in self.content.findChildren(QWidget):
            if widget.isVisible() and type(widget).__name__=='TokenPlot' and widget.reveal.animation.state()==QAbstractAnimation.State.Running:
                self._plot_resume=widget.reveal.animation.currentTime()
        self.island=None;self.minimal_quota=None;self._status_title=None;self._status_badge=None;self._header=None;self.today_tokens_card=None;self.status_indicator.set_island(False)
        self.status_indicator.hide();self.status_indicator.setParent(self.content)
        self.refresh_button.hide();self.refresh_button.setParent(self.content)
        while self.layout.count():
            widget=self.layout.takeAt(0).widget()
            if widget is self.editor_stack:widget.hide()
            elif widget and widget is not self.status_view:widget.hide();widget.deleteLater()
    def add(self,widget):self.layout.addWidget(widget);widget.show();return widget
    def label(self,text):
        label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);return self.add(label)
    def toggle_details(self):
        if self.report and self.report.requested and self.report._animating:
            self._pending_navigation=('toggle',None);return
        if self.size_transition.running:self._pending_navigation=('toggle',None);self._pending_mode=None;return
        if self.panel_page!='status':self.collapse_to_normal();return
        self.size_transition.begin();self.expanded=not self.expanded;self.redraw();self.size_transition.commit()
    def show_status(self,expanded=True):
        if self.size_transition.running:self._pending_navigation=('status',expanded);self._pending_mode=None;return
        self.size_transition.begin()
        self.panel_page='status';self.expanded=expanded;self._editor_origin=None;self._editor_positioned=False
        self._editing_flags(False);self.redraw();self.size_transition.commit()
    def return_to_status(self):
        if self.size_transition.running:self._pending_navigation=('return',None);self._pending_mode=None;return
        if self.panel_page=='status':return
        origin=self._editor_origin or dict(expanded=False,bubble_mode=self.bubble_mode,auto_compact=self.auto_compact,
                                           minimal_normal_open=self._minimal_normal_open)
        self.size_transition.begin();self.panel_page='status';self.expanded=origin['expanded']
        self.bubble_mode=origin['bubble_mode'];self.auto_compact=origin['auto_compact']
        self._minimal_normal_open=origin.get('minimal_normal_open',False)
        self._editor_origin=None;self._editor_positioned=False;self._manual_grace_until=time.monotonic()+15
        self._editing_flags(False);self.redraw();self.size_transition.commit()
    def collapse_to_normal(self):
        if self.bubble_mode=='minimal':self.open_normal_from_minimal()
        else:self.set_mode('auto')
    def show_page(self,key,widget):
        if self.size_transition.running:self._pending_navigation=(key,widget);self._pending_mode=None;return
        if self.report:self.report.dismiss()
        self.size_transition.begin()
        entering=self.panel_page=='status'
        if entering:self._editor_origin=dict(expanded=self.expanded,bubble_mode=self.bubble_mode,
                                             auto_compact=self.auto_compact,minimal_normal_open=self._minimal_normal_open)
        if self.editor_stack.indexOf(widget)<0:self.editor_stack.addWidget(widget)
        self.editor_stack.setCurrentWidget(widget);widget.show();self.panel_page=key;self.expanded=True
        if entering:self._editor_positioned=False
        self._editing_flags(True);self.redraw();self.size_transition.commit()
    def _editing_flags(self,editing):
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,not editing)
        if __import__('sys').platform=='darwin':
            from mac_native import set_keyboard_input
            set_keyboard_input(self,editing)
        through=bool(getattr(self.owner_pet(),'settings',{}).get('mouse_through',False)) and not editing
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,through)
        if self.windowHandle():self.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput,through)
    def navigation(self):
        from settings_controls import SlidingSegments
        toolbar=QWidget();toolbar.setObjectName('detail_shortcuts');toolbar.setFixedHeight(32)
        actions=QHBoxLayout(toolbar);actions.setContentsMargins(0,0,0,0);actions.setSpacing(7)
        tabs=SlidingSegments([('状态','status'),('聊天','chat'),('设置','settings')],compact=True)
        tabs.setObjectName('main_navigation');tabs.setCurrentIndex(tabs.findData(self.panel_page),False)
        for key,b in tabs.buttons.items():b.setObjectName('bubble_'+('details' if key=='status' else key))
        tabs.currentIndexChanged.connect(lambda index:self.return_to_status() if tabs.currentData()=='status' else
            self.chatRequested.emit() if tabs.currentData()=='chat' else self.settingsRequested.emit())
        actions.addWidget(tabs,1);self._navigation_segments=tabs
        for kind,text,tip,key,value in [('pin','置顶','切换始终置顶','on_top',self.pinned),('move','移动','切换桌面自由移动','wandering',self.wandering)]:
            shortcut=action_button(kind,tip,text,keyboard=self.panel_page!='status');shortcut.setCheckable(True);shortcut.setChecked(value)
            shortcut.toggled.connect(lambda checked,k=key:self.optionRequested.emit(k,checked));actions.addWidget(shortcut)
            if key=='wandering' and self.movement_locked:shortcut.setEnabled(False);shortcut.setText('已锁定');shortcut.setToolTip('移动已锁定，请在设置中解除锁定')
        return toolbar
    def _redraw_editor(self):
        self._redrawing=True
        self._last_compact_surface=None
        self.layout.setContentsMargins(10,6,10,6);self.layout.setSpacing(3)
        if self.layout.indexOf(self.editor_stack)<0:
            if self.details_tabs:self.detail_scroll={key:area.verticalScrollBar().value() for key,area in self.details_tabs.areas.items()}
            self.quota_refresh_button=None;self.reset_refresh_buttons=[];self.token_refresh_buttons=[]
            self.clear();self.details_tabs=None;self.status_view.hide()
            header=QWidget();header.setFixedHeight(28);row=QHBoxLayout(header);row.setContentsMargins(2,0,0,0)
            row.addWidget(self.status_indicator);self.status_indicator.show()
            self.editor_title=QLabel();row.addWidget(self.editor_title,1)
            codex=action_button('external','打开 Codex','Codex',keyboard=True);codex.setObjectName('open_codex');codex.clicked.connect(lambda:self.codexRequested.emit());row.addWidget(codex)
            close=action_button('collapse','收起到正常气泡','收起',keyboard=True);close.clicked.connect(self.collapse_to_normal);row.addWidget(close)
            self.add(header);self.add(self.navigation());self.add(self.editor_stack)
        self.editor_title.setText('白龙 '+('聊天' if self.panel_page=='chat' else '设置'))
        tabs=getattr(self,'_navigation_segments',None)
        if tabs:
            blocked=tabs.blockSignals(True);tabs.setCurrentIndex(tabs.findData(self.panel_page));tabs.blockSignals(blocked)
        for button in self.findChildren(QToolButton):
            if button.objectName() in ('bubble_chat','bubble_settings'):
                button.setChecked(button.objectName()=='bubble_'+self.panel_page)
            elif button.objectName() in ('bubble_pin','bubble_move'):
                button.blockSignals(True);button.setChecked(self.pinned if button.objectName()=='bubble_pin' else self.wandering);button.blockSignals(False)
                if button.objectName()=='bubble_move':button.setEnabled(not self.movement_locked);button.setText('已锁定' if self.movement_locked else '移动')
        screen=self.screen() or QApplication.primaryScreen();area=screen.availableGeometry()
        self.content.setFixedWidth(min(560,area.width()-24));self.editor_stack.setFixedHeight(min(520,max(220,area.height()-104)))
        self._redrawing=False;self._fit_height()
        owner=self.owner_pet()
        if owner is None or owner.isVisible():self.show()
        self._position_now()

    def select_dashboard(self,page):
        if page not in ('tokens','reset'):return
        if page==self.dashboard_page:
            if self.deck:self.deck.tabs.buttons[page].setChecked(True)
            self._sync_today_selection()
            return
        self.dashboard_page=page
        if self.deck and self.deck.isVisible():
            deck=self.deck;deck.token_busy=self.token_busy;deck.reset_busy=self.reset_busy;deck.set_page(page)
        else:self._chart_entry=True;self.redraw()
        self._sync_today_selection()
    def _sync_today_selection(self):
        if self.today_tokens_card:self.today_tokens_card.set_selected(self.dashboard_page=='tokens' and self.token_range=='day')
    def select_token_range(self,period):
        from token_calendar import TOKEN_RANGES
        if period in TOKEN_RANGES:
            if period==self.token_range:
                if self.deck and self.dashboard_page=='tokens':
                    button=self.deck.content.range_buttons.get(period)
                    if button:button.setChecked(True)
                self._sync_today_selection()
                return
            self.token_range=period
            if self.deck and self.deck.isVisible():
                self.deck.token_range=period
                if 'tokens' in self.deck.pages:self.deck.pages['tokens'].set_period(period)
            else:self._chart_entry=True;self.redraw()
            self._sync_today_selection();self.tokenRangeChanged.emit(period)
    def show_today_tokens(self):
        self.select_dashboard('tokens');self.select_token_range('day')
    def show_quota_details(self):
        self.detail_tab='quota';self.show_status(True)
    def show_reset_details(self):
        self.detail_tab='reset';self.show_status(True)
    def request_refresh_all(self):
        if self.refresh_busy:return
        self.set_refresh_busy(True);self.refreshAllRequested.emit()
    def set_refresh_busy(self,busy):
        self.refresh_busy=bool(busy);self.refresh_button.set_busy(self.refresh_busy)
        if self.shortcut_button and self.capsule_action=='refresh':self.shortcut_button.set_busy(self.refresh_busy)
        self.refresh_button.setToolTip('正在刷新额度、Token 与重置公告…' if busy else '刷新额度、Token 与重置公告')
    def finish_refresh(self,success=True):
        self.refresh_busy=False;self.refresh_button.finish(success)
        if self.shortcut_button and self.capsule_action=='refresh':self.shortcut_button.finish(success)
        text='额度、Token 已刷新；重置公告暂不可用，已保留上次记录' if success=='partial' else '额度、Token 与重置公告已刷新' if success else '数据刷新失败，保留上次记录；点击重试'
        if success=='partial' and self.reset_error_details:text='额度、Token 已刷新；'+self.reset_error_details.get('message','重置公告暂不可用')
        self.refresh_button.setToolTip(text);self.refresh_button.setAccessibleDescription(text)
    def set_quota_busy(self,busy):
        changed=self.quota_busy!=bool(busy)
        self.quota_busy=bool(busy)
        if changed:self.dataBusyChanged.emit('quota',self.quota_busy)
    def set_reset_busy(self,busy):
        changed=self.reset_busy!=bool(busy)
        self.reset_busy=bool(busy)
        if changed:self.dataBusyChanged.emit('reset',self.reset_busy)
    def set_token_busy(self,busy):
        changed=self.token_busy!=bool(busy)
        self.token_busy=bool(busy)
        if changed:self.dataBusyChanged.emit('token',self.token_busy)
    def _status_heading(self):
        indicator=self.status_indicator
        if indicator.unread:return f'{len(indicator.unread)}条待查看'
        waiting=[v for v in self.roster.items.values() if v['state']=='waiting']
        if waiting or indicator.state=='waiting' or indicator.waiting:
            reasons={v.get('waiting_reason','') for v in waiting}
            return '待你确认' if reasons=={'approval'} else '待你输入' if reasons=={'input'} else '待你操作'
        if indicator.state=='interrupted' and not indicator.is_busy():return '已中断'
        if indicator.state=='offline' and not indicator.is_busy():return '未连接'
        return 'Codex'
    def _update_header(self):
        """Use the actual header width for both first layout and live updates."""
        title=getattr(self,'_status_title',None);header=getattr(self,'_header',None)
        if title is None or header is None:return
        heading=self._status_heading()
        active=sum(v['state'] in ('thinking','working','responding','waiting') for v in self.roster.items.values())
        active=max(active,int(self.status_indicator.active))
        badge=self._status_badge;badge_text=str(active) if heading=='Codex' and active>1 else ''
        badge.setText(badge_text);badge.setVisible(bool(badge_text))
        badge_width=QFontMetrics(font(10,True)).horizontalAdvance(badge_text)+10 if badge_text else 0
        badge.setFixedWidth(badge_width)
        # Four 28px actions and their five layout gaps are reserved before
        # measuring the title. This stays identical across first paint/update.
        margins=self.layout.contentsMargins();inner=self.content.width()-margins.left()-margins.right()
        actions=sum(button.width() for button in self._header_actions)
        gap=header.layout().spacing();available=inner-actions-gap*(len(self._header_actions)+1)
        icon_width=self.status_indicator.width()+2
        badge_space=badge_width+3 if badge_text else 0
        text_budget=max(1,available-icon_width-badge_space-2)
        metrics=QFontMetrics(font(12,True));text=metrics.elidedText(heading,Qt.TextElideMode.ElideRight,text_budget)
        title.setText(text);title.setFixedWidth(metrics.horizontalAdvance(text)+2)
        title.parentWidget().setFixedSize(icon_width+title.width()+badge_space,28)
        title.setToolTip(heading+('\n'+str(active)+' 个会话正在进行' if badge_text else '')+'\n点击打开 Codex')
        title.setAccessibleName(heading+'；点击打开 Codex')
        header.layout().activate()
    def _refresh_conversation_rows(self):
        selected,extra=self.roster.selection(self.status_indicator.unread)
        self.status_view.extra=extra
        self.status_view.overflow.setText('+'+str(extra));self.status_view.overflow.setVisible(bool(extra))
        self.status_view.overflow.setAccessibleName(f'另有 {extra} 个会话，点击切换显示')
        from conversation_roster import LABELS
        if selected:
            rows=[(v['session'],'已完成' if v['state']=='complete' else clean_text(v['text'],80)) for v in selected]
            metadata={v['session']:dict(title=clean_text(v['title'],160),state=v['state']) for v in selected}
            self.status_view.set_conversations(rows,extra,self.expanded,metadata)
        else:
            self.status_view.clear_conversations()
            self.status_view.set_status('等待 Codex 新消息' if self.roster.items else self.status,self.expanded)
    def refresh_status(self):
        """Keep static cards and chart clocks alive for text-only changes."""
        if self.size_transition.running or self.size_transition.preparing:
            self.size_transition.status_deferred=True;return
        if self.panel_page!='status':return
        if self.is_minimal():return
        if self.is_island():
            if self.island is None:self.redraw();return
            from conversation_roster import LABELS
            selected,extra=self.roster.selection(self.status_indicator.unread)
            self.status_indicator.session_summary='/'.join('压缩' if v.get('compacting') and v['state']!='waiting' else LABELS.get(v['state'],'待命').removesuffix('中') for v in selected)+(' +'+str(extra) if extra else '')
            self.island.refresh();return
        title=getattr(self,'_status_title',None)
        if title is None or not self.status_view.isVisible():
            self.redraw();return
        self._update_header()
        self._refresh_conversation_rows()
        self.setAccessibleName(self.heading+'；'+self.status)
    def redraw(self):
        if self.size_transition.running:self.size_transition.deferred=True;return
        if self.panel_page!='status':self._redraw_editor();return
        if self.is_minimal():self._redraw_minimal();return
        if self.is_island():self._redraw_island();return
        self._last_compact_surface=None
        self._redrawing=True
        if self.details_tabs:
            self.detail_scroll={key:area.verticalScrollBar().value() for key,area in self.details_tabs.areas.items()}
        self.details_tabs=None
        self.layout.setContentsMargins(10,6,10,6);self.layout.setSpacing(3)
        self.content.setFixedWidth(360 if self.expanded else 268)
        self.status_view.setFixedWidth(340 if self.expanded else 248)
        self.clear();self.quota_refresh_button=None;self.reset_refresh_buttons=[];self.token_refresh_buttons=[]
        header=QWidget();header.setObjectName('status_header');header.setFixedHeight(28);row=QHBoxLayout(header);row.setContentsMargins(0,0,0,0);row.setSpacing(2)
        title=QToolButton();title.setObjectName('open_codex');title.setFont(font(12,True))
        title.setFixedHeight(28)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus);title.setCursor(Qt.CursorShape.PointingHandCursor)
        title.setStyleSheet('QToolButton{'+FONT_CSS+'font-size:12px;color:#393343;border:0;padding:0;background:transparent;text-align:left;}QToolButton:hover{color:#8b78a6;}')
        title.setAccessibleName('打开 Codex');title.clicked.connect(lambda:self.codexRequested.emit())
        self._status_title=title
        name_group=QWidget();name_group.setObjectName('codex_heading');name_group.setFixedHeight(28)
        name_row=QHBoxLayout(name_group);name_row.setContentsMargins(0,0,0,0);name_row.setSpacing(2)
        name_row.addWidget(self.status_indicator);self.status_indicator.show();name_row.addWidget(title)
        badge=QLabel();badge.setObjectName('codex_active_count');badge.setFixedHeight(18)
        badge.setStyleSheet(FONT_CSS+'font-size:11px;font-weight:500;color:#66517e;background:#eee6f4;border-radius:6px;padding:0;')
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter);name_row.addWidget(badge);self._status_badge=badge
        row.addWidget(name_group);row.addStretch(1)
        self.quota_refresh_button=self.refresh_button;row.addWidget(self.refresh_button);self.refresh_button.show()
        report_button=action_button('report','打开 / 收起数据面板',hit_size=28);report_button.setObjectName('bubble_report')
        report_button.clicked.connect(self.reportRequested.emit);row.addWidget(report_button)
        compact_target='minimal' if self.bubble_mode=='minimal' else 'mini'
        mini=action_button('compact','收起到极简模式' if compact_target=='minimal' else '收起到胶囊模式',hit_size=28)
        mini.setObjectName('bubble_compact');mini.clicked.connect(lambda:self.set_mode(compact_target));row.addWidget(mini)
        button=action_button('collapse' if self.expanded else 'details','收起详情' if self.expanded else '展开完整状态、来源与重置说明',hit_size=28)
        button.clicked.connect(self.toggle_details);row.addWidget(button);self.add(header)
        self._header=header;self._header_actions=[self.refresh_button,report_button,mini,button];self._update_header()
        if self.expanded:
            self.add(self.navigation())
            label=self.label('当前任务');label.setObjectName('detail_status_title');label.setStyleSheet(FONT_CSS+'font-size:11px;color:#706879;margin-top:3px;')
        self._refresh_conversation_rows()
        self.add(self.status_view)
        if self.show_quota:
            # Only a new/resolved announcement changes the default front card;
            # routine status, quota and token updates preserve manual switching.
            from dashboard_cards import CardDeck,DASH_HEIGHT
            from quota_summary import QuotaSummary,TodayTokens
            pending=pending_reset(self.reset_snapshot);key=(schedule_key(pending),locally_reset(self.reset_snapshot)) if pending else None
            if key!=self._active_reset_key:
                self.dashboard_page='reset' if reset_has_priority(self.reset_snapshot) else 'tokens';self._active_reset_key=key
            from quota_history import visible_anomaly
            warning=visible_anomaly(self.token_snapshot,self.windows)
            container=QWidget()
            stack=QVBoxLayout(container);stack.setContentsMargins(0,0,0,0);stack.setSpacing(2)
            cards=QWidget();row=QHBoxLayout(cards);row.setContentsMargins(0,0,0,0);row.setSpacing(6);stack.addWidget(cards)
            quota=QuotaSummary(self.windows,self.quota_caption,progress_cache=self._ring_values,anomaly=warning);quota.expand.connect(self.show_quota_details)
            cards.setFixedHeight(quota.height());container.setFixedHeight(quota.height()+TodayTokens.HEIGHT+2)
            quota.resetDue.connect(self._quota_reset_due);row.addWidget(quota,1)
            self.ring_kinds=['quota']*len(quota.items)+['time','tokens']
            deck=CardDeck(self.dashboard_page,self.token_snapshot,self.reset_snapshot,self.reset_error_details or self.reset_feed_error,self.reset_busy,token_busy=self.token_busy,token_range=self.token_range)
            deck.reset_details_requested.connect(self.show_reset_details)
            self.deck=deck
            deck.selected.connect(self.select_dashboard)
            deck.token_range_changed.connect(self.select_token_range)
            row.addWidget(deck,1,Qt.AlignmentFlag.AlignTop);daily=TodayTokens(self.token_snapshot,selected=self.dashboard_page=='tokens' and self.token_range=='day');self.today_tokens_card=daily
            daily.activated.connect(self.show_today_tokens);stack.addWidget(daily);self.add(container)
            if self.expanded:
                from detail_sections import DetailsTabs
                self.details_tabs=DetailsTabs(self);self.add(self.details_tabs)
        self._redrawing=False;self._fit_height()
        self.set_quota_busy(self.quota_busy);self.set_reset_busy(self.reset_busy);self.set_token_busy(self.token_busy)
        owner=self.owner_pet()
        if self.enabled and self.host_visible():self.show()
        elif self.host_visible():self.size_transition.dismiss()
        else:self.hide()
        if self.details_tabs:
            tabs=self.details_tabs;positions=dict(self.detail_scroll)
            QTimer.singleShot(0,tabs,lambda:tabs.restore_scroll(positions))
        self._position_now()
        if self._chart_entry:
            self._chart_entry=False
            for widget in self.content.findChildren(QWidget):
                if widget.isVisible() and hasattr(widget,'begin_reveal'):widget.begin_reveal();widget.start_reveal()
        elif self._plot_resume is not None and not self.size_transition.preparing:
            for widget in self.content.findChildren(QWidget):
                if widget.isVisible() and type(widget).__name__=='TokenPlot':
                    widget.reveal.prepare();widget.reveal.start();widget.reveal.animation.setCurrentTime(self._plot_resume)
    def owner_pet(self):return self._owner or self.parentWidget()
    def host_visible(self):
        owner=self.owner_pet()
        return owner is None or (owner.card_surface_visible() if hasattr(owner,'card_surface_visible') else owner.isVisible())
    def is_minimal(self):return self.panel_page=='status' and not self.expanded and self.bubble_mode=='minimal' and not self._minimal_normal_open
    def is_compact(self):return self.is_island() or self.is_minimal()
    def is_island(self):return self.panel_page=='status' and not self.expanded and (self.bubble_mode=='mini' or self.auto_compact)
    def set_mode(self,mode):
        if mode not in ('auto','mini','minimal'):raise ValueError('未知的卡片显示模式')
        if self.size_transition.running:self._pending_mode=mode;self._pending_navigation=None;return
        self.size_transition.begin();self.bubble_mode=mode;self.auto_compact=False;self._minimal_normal_open=False
        self.expanded=False;self.panel_page='status';self._editor_origin=None
        self.last_task_update=time.monotonic();self._manual_grace_until=self.last_task_update+15
        if self.report:self.report.dismiss()
        self._editing_flags(False);self.redraw();self.size_transition.commit();self.modeChanged.emit(mode)
    def open_normal_from_minimal(self):
        """Temporarily open the card while keeping minimal as its compact shape."""
        if self.size_transition.running:self._pending_navigation=('minimal_normal',None);self._pending_mode=None;return
        self.size_transition.begin();self._minimal_normal_open=True;self.auto_compact=False
        self.expanded=False;self.panel_page='status';self._editor_origin=None
        self.last_task_update=time.monotonic();self._manual_grace_until=self.last_task_update+15
        if self.report:self.report.dismiss()
        self._editing_flags(False);self.redraw();self.size_transition.commit()
    def _apply_pending_mode(self):
        mode=self._pending_mode;nav=self._pending_navigation;self._pending_mode=None;self._pending_navigation=None
        if mode:self.set_mode(mode);return
        if nav:
            key,value=nav
            callback=(lambda:self.toggle_details()) if key=='toggle' else self.return_to_status if key=='return' else self.open_normal_from_minimal if key=='minimal_normal' else (lambda:self.show_status(value)) if key=='status' else (lambda:self.show_page(key,value))
            callback()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            if self.report and self.report.requested:self.report.dismiss()
            elif self.panel_page!='status':self.return_to_status()
            elif self.expanded:self.collapse_to_normal()
            else:super().keyPressEvent(event);return
            event.accept();return
        super().keyPressEvent(event)
    def task_updated(self,event):
        # Only monitor task events reset inactivity; quota/token/feed polls do not.
        self.last_task_update=time.monotonic()
        if self.codex_open is False:self.codex_open=None
        self.evaluate_mode()
    def evaluate_mode(self,now=None):
        now=time.monotonic() if now is None else now
        if self.panel_page!='status' or self.expanded or (self.report and self.report.requested) or self.size_transition.running:return
        if self.bubble_mode=='minimal':
            if self._minimal_normal_open and now>=self._manual_grace_until and (now-self.last_task_update>=90 or self.codex_open is False):
                self.size_transition.begin();self._minimal_normal_open=False;self.redraw();self.size_transition.commit()
            return
        if self.bubble_mode!='auto':return
        compact=now>=self._manual_grace_until and (now-self.last_task_update>=90 or self.codex_open is False)
        if compact==self.auto_compact:return
        self.size_transition.begin();self.auto_compact=compact;self.redraw();self.size_transition.commit()
    def _refresh_island_status(self):
        if self.size_transition.running or self.size_transition.preparing:
            self.size_transition.status_deferred=True;return
        if self.island:self.island.refresh()
        if (self.roster.items or self.status_indicator.unread) and not self._roster_pending:
            self._roster_pending=True;QTimer.singleShot(0,self,self._apply_roster)
    def _apply_roster(self):self._roster_pending=False;self.refresh_status()
    def _auto_cycle_conversations(self):
        if not self.conversation_auto_scroll or not self.status_view.isVisible() or not self.status_view.extra:return
        if self.panel_page!='status' or self.size_transition.running:return
        from PySide6.QtGui import QCursor
        if self.status_view.rect().contains(self.status_view.mapFromGlobal(QCursor.pos())):return
        if self.roster.rotate_one(self.status_indicator.unread):self.refresh_status()
    def cycle_conversations(self,direction=1):
        self.roster.cycle(direction);self.refresh_status()
        self.conversation_timer.start()
    def _quota_reset_due(self,stamp):
        if self._quota_reset_requested is not None and stamp<=self._quota_reset_requested:return
        self._quota_reset_requested=stamp
        self.quotaRefreshRequested.emit();self.redraw()
    def _redraw_island(self):
        from island_widgets import StatusIsland,QuotaSatellite,WIDTH,HEIGHT
        self._redrawing=True
        entering=self._last_compact_surface!='mini';self._last_compact_surface='mini'
        if self.details_tabs:self.detail_scroll={key:area.verticalScrollBar().value() for key,area in self.details_tabs.areas.items()}
        self.clear();self.details_tabs=None;self.status_view.animation.stop();self.status_view.hide()
        self.quota_refresh_button=None;self.reset_refresh_buttons=[];self.token_refresh_buttons=[]
        self.layout.setContentsMargins(0,2,0,2);self.layout.setSpacing(0)
        self.content.setFixedWidth(WIDTH if self.show_quota else WIDTH-45)
        cluster=QWidget();cluster.setFixedHeight(40);row=QHBoxLayout(cluster);row.setContentsMargins(0,0,0,0);row.setSpacing(5)
        circle_style='QToolButton{border:0;border-radius:20px;background:#fcfafc;}QToolButton:hover{background:#eee8f3;}QToolButton:pressed{background:#e4dbea;}'
        from quick_actions import action_info
        key,title,icon=action_info(self.capsule_action)
        shortcut=action_button(icon,title,keyboard=True);shortcut.setObjectName('island_shortcut');shortcut.setFixedSize(40,40);shortcut.setIconSize(QSize(18,18))
        shortcut.setStyleSheet(circle_style+'QToolButton:focus{border:0;background:#eee8f3;}')
        shortcut.clicked.connect(self.shortcutRequested.emit);row.addWidget(shortcut);self.shortcut_button=shortcut
        if key=='refresh':shortcut.set_busy(self.refresh_busy)
        self.status_indicator.set_island(True);self.island=StatusIsland(self.status_indicator)
        from conversation_roster import LABELS
        selected,extra=self.roster.selection(self.status_indicator.unread)
        self.status_indicator.session_summary='/'.join('压缩' if v.get('compacting') and v['state']!='waiting' else LABELS.get(v['state'],'待命').removesuffix('中') for v in selected)+(' +'+str(extra) if extra else '')
        self.island.refresh()
        self.island.expand.connect(lambda:self.set_mode('auto'));row.addWidget(self.island)
        if self.show_quota:
            quota=QuotaSatellite(self.windows,self.quota_caption);quota.clicked.connect(self.toggle_details)
            if entering:quota.begin_reveal()
            quota.resetDue.connect(self._quota_reset_due);row.addWidget(quota)
        self.add(cluster);self._redrawing=False;self._fit_height()
        owner=self.owner_pet()
        if self.enabled and self.host_visible():self.show()
        elif self.host_visible():self.size_transition.dismiss()
        else:self.hide()
        if self.show_quota and entering and not self.size_transition.preparing and not self.size_transition.running:
            QTimer.singleShot(0,quota,quota.start_reveal)
        self._position_now()
    def _redraw_minimal(self):
        from island_widgets import MinimalQuota
        self._redrawing=True
        entering=self._last_compact_surface!='minimal';self._last_compact_surface='minimal'
        self.clear();self.details_tabs=None;self.status_view.animation.stop();self.status_view.hide()
        self.quota_refresh_button=None;self.reset_refresh_buttons=[];self.token_refresh_buttons=[]
        self.layout.setContentsMargins(0,0,0,0);self.layout.setSpacing(0);self.content.setFixedWidth(54)
        self.minimal_quota=MinimalQuota(self.windows,self.quota_caption,self)
        self.minimal_quota.clicked.connect(self.open_normal_from_minimal);self.minimal_quota.resetDue.connect(self._quota_reset_due)
        if entering:self.minimal_quota.begin_reveal()
        self.add(self.minimal_quota);self._redrawing=False;self._fit_height()
        if self.enabled and self.host_visible():self.show()
        elif self.host_visible():self.size_transition.dismiss()
        else:self.hide()
        if entering and not self.size_transition.preparing and not self.size_transition.running:
            QTimer.singleShot(0,self.minimal_quota,self.minimal_quota.start_reveal)
        self._position_now()
    def _status_height_changed(self):
        if not self._redrawing and self.panel_page=='status':
            r=self.report;scroller=self.status_view
            if r and r.requested and not r._animating and not self.size_transition.running and not self.size_transition.preparing:
                if not r.follow.active and scroller.animation.state()==QAbstractAnimation.State.Running and scroller._to_height!=scroller._from_height:
                    target=self.content_geometry(QSize(self.content.width(),self.height()+scroller._to_height-scroller._from_height))
                    r.follow.begin_status(target)
            self._fit_height()
            if r:r.follow.track_status(self.geometry(),scroller.progress)
    def _status_height_finished(self):
        if self.report:self.report.follow.finish_status()
    def _fit_height(self):
        if self.size_transition.running:return
        if self._fitting_height:return
        self._fitting_height=True
        margins=self.layout.contentsMargins();inner=self.content.width()-margins.left()-margins.right()
        wanted=margins.top()+margins.bottom()+self.layout.spacing()*max(0,self.layout.count()-1)
        for i in range(self.layout.count()):
            widget=self.layout.itemAt(i).widget();widget.ensurePolished()
            h=widget.heightForWidth(inner) if widget.hasHeightForWidth() else widget.sizeHint().height()
            wanted+=min(widget.maximumHeight(),max(widget.minimumSizeHint().height(),h,widget.minimumHeight()))
        owner=self.owner_pet()
        if self.details_tabs and owner:
            settings=getattr(owner,'settings',{})
            detached=settings.get('panel_detached') or not settings.get('character_visible',True)
            rect=owner.card_geometry(self.content.size()) if detached else owner.frameGeometry()
            screen=QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
            area=screen.availableGeometry()
            room=area.height()-16 if detached else max(owner.y()-area.top()-8,area.bottom()-owner.y()-owner.height()-7)
            old=self.details_tabs.height();height=max(120,min(244,room-(wanted-old)))
            self.details_tabs.setFixedHeight(height);wanted+=height-old
        if self.content.height()!=max(40,wanted):self.content.setFixedHeight(max(40,wanted))
        self.setAccessibleName(self.heading+'；'+self.status)
        if not self.size_transition.preparing and self.size()!=self.content.size():self.setFixedSize(self.content.size())
        self.layout.activate();self._fitting_height=False;self._position_now()
    def _position_now(self):
        if self.size_transition.running or self.size_transition.preparing or self.size_transition.landing.image is not None:return
        owner=self.owner_pet()
        if owner and getattr(owner,'enhanced_ready',False):owner.position_bubble()
    def content_geometry(self,size=None):
        owner=self.owner_pet();size=self.content.size() if size is None else size
        if owner is None:return QRectF(self.x(),self.y(),size.width(),size.height()).toRect()
        if hasattr(owner,'card_geometry') and (owner.settings.get('panel_detached') or not owner.settings.get('character_visible',True)):return owner.card_geometry(size)
        screen=QApplication.screenAt(owner.frameGeometry().center()) or QApplication.primaryScreen();area=screen.availableGeometry()
        if self.panel_page!='status' and self._editor_positioned:x,y=self.x(),self.y()
        else:
            x=owner.x()+(owner.width()-size.width())//2;y=owner.y()-size.height()-8
            reserve=max(0,2*self.status_view.line_height-self.status_view.height()) if not self.expanded and not self.is_island() else 0
            if y-reserve<area.top():y=owner.y()+owner.height()+8
        reserve=self.report.reserved_height()+6 if self.report and self.report.requested else 0
        x=max(area.left(),min(x,area.right()-size.width()+1));y=max(area.top()+reserve,min(y,area.bottom()-size.height()+1))
        return QRectF(x,y,size.width(),size.height()).toRect()
    def placement_height(self):
        # One-/two-line changes must not flip the bubble to the opposite side
        # of the character near the top edge. Probe with the larger compact size.
        reserve=max(0,2*self.status_view.line_height-self.status_view.height()) if not self.expanded and not self.is_island() else 0
        return self.height()+reserve
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if not self.isVisible() or self.is_compact() or self.size_transition.canvas_morph or self.size_transition.preparing:return
        p.setBrush(QColor('#fcfafc'));p.setPen(QPen(QColor('#e0d9e6'),1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),PANEL_RADIUS,PANEL_RADIUS)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not self._redrawing and not self._fitting_height:self._position_now()
    def hideEvent(self,event):
        if hasattr(self,'size_transition'):self.size_transition.cancel()
        super().hideEvent(event)
    def showEvent(self,event):
        super().showEvent(event)
        if not self.size_transition.running and not self.size_transition.preparing:self.content.show()
        self._editing_flags(self.panel_page!='status')
    def message(self,text):self.is_quota_result=False;self.status=clean_text(text,180);self.refresh_status()
    def quota(self,windows):self.windows=windows;self.redraw()
    def contextMenuEvent(self,event):
        owner=self.owner_pet()
        if owner and hasattr(owner,'context_menu'):owner.context_menu(event.globalPos());event.accept()
        else:super().contextMenuEvent(event)
    def card_pointer_press(self,event):
        owner=self.owner_pet()
        if event.button()==Qt.MouseButton.LeftButton and owner and (owner.settings.get('panel_detached') or not owner.settings.get('character_visible',True)) and not self.size_transition.running:
            self._card_press=(event.globalPosition().toPoint(),self.pos());self._card_dragged=False;return True
        return False
    def card_pointer_move(self,event):
        if self._card_press and event.buttons()&Qt.MouseButton.LeftButton:
            point,start=self._card_press;delta=event.globalPosition().toPoint()-point
            if delta.manhattanLength()>5 or self._card_dragged:
                self._card_dragged=True;owner=self.owner_pet();owner.move_card(start+delta);return True
        return False
    def card_pointer_release(self):
        dragged=self._card_dragged;self._card_press=None;self._card_dragged=False
        if dragged:self.owner_pet().save_settings()
        return dragged
    def mousePressEvent(self,event):
        if not self.card_pointer_press(event):super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if not self.card_pointer_move(event):super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if not self.card_pointer_release():super().mouseReleaseEvent(event)
