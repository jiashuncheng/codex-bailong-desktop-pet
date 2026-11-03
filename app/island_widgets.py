"""Small status island and quota satellite; no per-frame window movement."""
from theme_registry import color as theme_color
from settings_controls import play_animation
import math,time,re
from PySide6.QtCore import Qt,QRectF,QSize,QTimer,Signal,QPointF,QVariantAnimation,QAbstractAnimation,QEasingCurve
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QFontMetrics,QFontMetricsF,QTextLayout,QTextCharFormat
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton
from typography import ui_font,FONT_CSS
from reset_watch import epoch
from ui_theme import SURFACE,INK,MUTED,ACCENT,TRACK,ISLAND,ON_ISLAND,ISLAND_RUNNING,QUOTA_WEEK,QUOTA_LOW
from chart_reveal import ChartReveal
from capsule_names import short_session_name,capsule_columns
from conversation_sources import display_source

WIDTH=246
STATUS_WIDTH=156
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

class IslandStatusText(QLabel):
    """Keep plain accessible text while painting each session in its own color."""
    def set_status(self,text,states,entries=None,extra=0):
        self.setText(text);self.source_rows=[];self.extra=extra
        self.row_font=ui_font(11,True);metrics=QFontMetrics(self.row_font)
        labels={'thinking':'思考','working':'执行','responding':'回复','waiting':'待操作','complete':'完成','interrupted':'中断','offline':'重连中'}
        entries=(entries or [])[:2]
        names=[short_session_name(v.get('title'),v.get('source_label')) for v in entries]
        statuses=[labels.get(v['state'],'待命') for v in entries]
        self.count_font=QFont(self.row_font);self.count_font.setPixelSize(10)
        self.row_columns=capsule_columns(self.width(),metrics,names,statuses,extra,QFontMetrics(self.count_font))
        for item,name,status in zip(entries,names,statuses):
            source=str(item.get('source_label') or '未知')
            self.source_rows.append(dict(source=metrics.elidedText(display_source(source),Qt.TextElideMode.ElideMiddle,max(1,self.row_columns['source_width']-2)),full_source=source,title=item.get('title',''),name=metrics.elidedText(name,Qt.TextElideMode.ElideMiddle,self.row_columns['name_width']),full_name=name,status=status,running=item['state'] in ('thinking','working','responding','waiting')))
        # If long, distinct titles have the same middle-elided abbreviation,
        # expose their different endings instead of identical short labels.
        if len(self.source_rows)==2 and self.source_rows[0]['name']==self.source_rows[1]['name'] and names[0]!=names[1]:
            for row,name in zip(self.source_rows,names):row['name']=metrics.elidedText(name,Qt.TextElideMode.ElideLeft,self.row_columns['name_width'])
        self.status_layout=QTextLayout(text,self.font())
        formats=[];offset=0
        # Elision/shortening preserves slash-separated session order. Overflow
        # counts and separators stay white, even after a running session.
        for index,part in enumerate(text.split('/')):
            label=re.split(r'\s*\+\d+$',part)[0]
            color=ISLAND_RUNNING if index<len(states) and states[index] in ('thinking','working','responding','waiting') else ON_ISLAND
            fmt=QTextCharFormat();fmt.setForeground(QColor(color))
            span=QTextLayout.FormatRange();span.start=offset;span.length=len(label);span.format=fmt
            formats.append(span);offset+=len(part)+1
        self.status_layout.setFormats(formats)
        self.status_layout.beginLayout();line=self.status_layout.createLine()
        if line.isValid():line.setLineWidth(self.width())
        self.status_layout.endLayout();self.update()
    def paintEvent(self,event):
        if getattr(self,'source_rows',None):
            p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setFont(self.row_font)
            line_height=17;top=(self.height()-len(self.source_rows)*line_height)/2;c=self.row_columns
            def draw(text,x,y,width,color,align=Qt.AlignmentFlag.AlignLeft):
                rect=QRectF(x,y,width,line_height);p.save();p.setClipRect(rect)
                p.setPen(QColor(color));p.drawText(rect,Qt.AlignmentFlag.AlignVCenter|align,text);p.restore()
            progress=self.property('captionProgress');progress=1. if progress is None else float(progress)
            p.setClipRect(self.rect())
            for index,row in enumerate(self.source_rows):
                p.save();p.setClipRect(QRectF(0,top+index*line_height,self.width(),line_height),Qt.ClipOperation.IntersectClip)
                previous=getattr(self,'previous_rows',[])
                moved=index>=len(previous) or (row['source'],row['full_name'])!=(previous[index]['source'],previous[index]['full_name'])
                y=top+index*line_height+(6*(1-progress) if moved else 0)
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#443b50'))
                p.drawRoundedRect(QRectF(0,y+1,c['source_width'],15),4,4)
                draw(row['source'],1,y,c['source_width']-2,'#d6cadd',Qt.AlignmentFlag.AlignHCenter)
                draw(row['name'],c['name_x'],y,c['name_width'],ON_ISLAND)
                draw(row['status'],c['status_x'],y,c['status_width'],ISLAND_RUNNING if row['running'] else ON_ISLAND)
                p.restore()
            if self.extra:
                p.setFont(self.count_font)
                draw('+'+str(self.extra),c['count_x'],top+(len(self.source_rows)-1)*line_height,c['count_width'],'#c1b5cd',Qt.AlignmentFlag.AlignRight)
            return
        layout=getattr(self,'status_layout',None)
        if layout is None:return super().paintEvent(event)
        p=QPainter(self);p.setPen(QColor(ON_ISLAND))
        layout.draw(p,QPointF(0,(self.height()-layout.boundingRect().height())/2))

class StatusIsland(QWidget):
    expand=Signal()
    def __init__(self,icon,parent=None):
        super().__init__(parent);self.setObjectName('status_island');self.icon=icon
        self.setFixedSize(STATUS_WIDTH,40);self.setCursor(Qt.CursorShape.PointingHandCursor)
        row=QHBoxLayout(self);row.setContentsMargins(12,0,10,0);row.setSpacing(5)
        row.addWidget(icon);icon.show()
        self.text=IslandStatusText();self.text.setFont(ui_font(12,True));self.text.setStyleSheet('color:'+ON_ISLAND+';background:transparent;')
        self.text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);row.addWidget(self.text,1)
        self._holds=set();self._last_status=None
        self.animation=QVariantAnimation(self);self.animation.setDuration(250);self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.valueChanged.connect(lambda value:self._caption_frame(value));self.animation.finished.connect(lambda:self._caption_frame(1.))
        self.refresh()
    def _caption_frame(self,value):
        self.text.setProperty('captionProgress',value);self.text.update()
    def freeze_motion(self,reason='surface'):
        self._holds.add(reason)
        if self.animation.state()==QAbstractAnimation.State.Running:self.animation.pause()
    def resume_motion(self,reason='surface'):
        self._holds.discard(reason)
        if not self._holds and self.isVisible() and self.animation.state()==QAbstractAnimation.State.Paused:self.animation.resume()
    def hideEvent(self,event):
        self.animation.stop();self._caption_frame(1.);super().hideEvent(event)
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
        states=getattr(self.icon,'session_states',[]) if getattr(self.icon,'session_summary','') else [self.icon.state if self.icon.visual() in ('busy','waiting') else 'complete']
        entries=getattr(self.icon,'session_entries',[])
        tail=re.search(r'\+(\d+)$',full);extra=int(tail.group(1)) if tail else 0
        signature=(text,repr(entries),extra)
        if signature==self._last_status:return
        changed=self._last_status is not None and signature!=self._last_status
        identities=tuple((v.get('session'),v.get('source_label'),v.get('title')) for v in entries)
        rotating=changed and identities!=getattr(self,'_last_identities',identities)
        if rotating:self.text.previous_rows=list(getattr(self.text,'source_rows',[]))
        self.text.set_status(text,states,entries,extra)
        from settings_controls import motion_enabled
        if rotating and self.isVisible() and not self._holds and motion_enabled():play_animation(self.animation)
        elif self.animation.state()==QAbstractAnimation.State.Stopped:self._caption_frame(1.)
        self._last_status=signature;self._last_identities=identities
        if entries:
            description='；'.join((display_source(v.get('source_label') or '未知')+' · '+str(v.get('title') or '')+' · '+{'thinking':'思考中','working':'执行中','responding':'回复中','waiting':'待操作','complete':'已完成','offline':'重连中'}.get(v['state'],'待命')).replace(' ·  · ',' · ') for v in entries)
            full=description+(f'；另有 {extra} 个会话' if extra else '')
        self.text.setAccessibleName(full);self.setAccessibleName('Codex · '+full+'；点击打开正常面板')
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            window=self.window()
            if hasattr(window,'card_pointer_press'):window.card_pointer_press(event)
            event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        window=self.window()
        if hasattr(window,'card_pointer_move') and window.card_pointer_move(event):event.accept();return
        super().mouseMoveEvent(event)
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
        self.setFixedSize(38,38);self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window=selected_quota(windows)
        self.reveal=ChartReveal(self)
        self._reveal_resume_ms=None
        value=self.window.get('remaining')
        exact=f'{value:g}%' if valid_percent(value) else '等待更新' if self.window.get('pending') else '未知'
        self.setAccessibleName(self.window.get('name','额度')+'剩余 '+exact+'；点击展开详情')
        self._prepare_dial()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._due)
        five=next((w for w in windows if w.get('name')=='5小时'),None)
        self.reset=epoch((five or self.window).get('resetsAt'))
    def set_data(self,windows,caption):
        chosen=selected_quota(windows)
        self.windows=windows;self.caption=caption
        if chosen!=self.window:
            self.window=chosen;self._prepare_dial();self.update()
        value=chosen.get('remaining');exact=f'{value:g}%' if valid_percent(value) else '等待更新' if chosen.get('pending') else '未知'
        action='打开正常卡片；可拖动；右键切换模式' if self.objectName()=='minimal_quota' else '展开详情'
        self.setAccessibleName(chosen.get('name','额度')+'剩余 '+exact+'；点击'+action);self.setAccessibleDescription(caption)
        five=next((w for w in windows if w.get('name')=='5小时'),None);reset=epoch((five or chosen).get('resetsAt'))
        if reset!=self.reset:
            self.timer.stop();self.reset=reset
            if reset and self.isVisible():self.timer.start(max(1,min(2147483647,math.ceil((reset-time.time())*1000))))

    def showEvent(self,event):
        super().showEvent(event)
        # Showing a hidden compact surface is a new entry. The bubble owns
        # preparation; never spend the reveal clock under its morph/landing.
        if self.reveal.pending or self._reveal_resume_ms is not None:QTimer.singleShot(0,self,self.start_reveal)
        if self.reset:
            self.timer.start(max(1,min(2147483647,math.ceil((self.reset-time.time())*1000))))
    def begin_reveal(self):self._reveal_resume_ms=None;self.reveal.prepare()
    def start_reveal(self):
        transition=getattr(QWidget.window(self),'size_transition',None)
        if transition and (transition.preparing or transition.running or transition.landing.image is not None):return
        if self._reveal_resume_ms is not None and self.isVisible():
            elapsed=self._reveal_resume_ms;self._reveal_resume_ms=None
            from settings_controls import play_animation
            play_animation(self.reveal.animation);self.reveal.animation.setCurrentTime(elapsed);return
        self.reveal.start()
    def hideEvent(self,event):
        self.timer.stop()
        if self.reveal.animation.state()==self.reveal.animation.State.Running:self._reveal_resume_ms=self.reveal.animation.currentTime()
        self.reveal.stop();super().hideEvent(event)
    def _due(self):self.resetDue.emit(self.reset)
    def value_text(self):
        value=self.window.get('remaining')
        if not valid_percent(value):return '—'
        if 0<value<1:return '<1%'
        return f'{100 if value==100 else min(99,int(value+.5))}%'
    def _prepare_dial(self):
        # The compact preview uses a full circular track with a lighter stroke.
        # Cache all text measurements; reveal frames only change the arc span.
        self._label=self.value_text()
        number=self._label.removesuffix('%');suffix='%' if self._label.endswith('%') else ''
        small=ui_font(11);small.setPixelSize(9)
        for size in (12,11,10):
            main=ui_font(size);main.setPixelSize(size);main.setWeight(QFont.Weight.Medium);main.setStretch(100)
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
        from theme_registry import palette,quota_ring_color
        colors=palette();self._color=QColor(quota_ring_color(value if valid_percent(value) else None))
        self._arc=QRectF(5,5,30,30)
        self._track_pen=QPen(QColor(theme_color(colors['pillTrack'])),2.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
        self._value_pen=QPen(self._color,2.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
    def paintEvent(self,event):
        p=QPainter(self);p.scale(self.width()/40,self.height()/40);self.paint_dial(p)
    def paint_dial(self,p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme_color(ISLAND)))
        p.drawEllipse(QRectF(.5,.5,39,39));p.setBrush(Qt.BrushStyle.NoBrush)
        fraction=self._fraction*self.reveal.progress
        p.setPen(theme_color(self._track_pen));p.drawArc(self._arc,90*16,-360*16)
        if fraction>0:
            p.setPen(theme_color(self._value_pen));p.drawArc(self._arc,90*16,-max(1,round(360*16*fraction)))
        p.setPen(QColor(theme_color(ON_ISLAND)))
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
