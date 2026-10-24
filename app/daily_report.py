"""Manually opened, animated daily report anchored above the status bubble."""
import math,random
from html import escape
from datetime import datetime
from PySide6.QtCore import Qt,QRect,QRectF,QPointF,QPoint,QSize,QEvent,Signal,QVariantAnimation,QEasingCurve,QAbstractAnimation,QTimer
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QFontMetrics,QPixmap,QRegion
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QScrollArea,QApplication,QSizePolicy
from compact_bubble import font,INK,MUTED,FONT_CSS,action_button
from token_calendar import compact_tokens
from token_analytics import model_series,token_analogy
from book_reference import analogy as book_analogy,catalog as book_catalog
from chart_reveal import ChartReveal,RasterChart
from chart_curve import SmoothTrace
from spring_motion import island_response,dismiss_progress,stage,EXPAND_MS,DISMISS_MS
from card_motion import card_geometry,paint_card

from ui_theme import MODEL_COLORS,PANEL,PRIMARY,SELECTED
COLORS=MODEL_COLORS

def tab(text,slot,checked=False):
    b=QToolButton();b.setText(text);b.setCheckable(True);b.setChecked(checked);b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor);b.setFixedHeight(23)
    b.setStyleSheet('QToolButton{'+FONT_CSS+'font-size:11px;font-weight:500;color:#706879;border:0;border-radius:5px;padding:2px 5px;background:transparent;}QToolButton:checked{color:#514360;background:#eae1f2;}QToolButton:hover{background:#f0e9f6;}')
    b.clicked.connect(slot);return b

class OverviewStats(QWidget):
    def __init__(self,report,parent=None):
        super().__init__(parent);self.report=report
    def set_columns(self,width):
        self.columns=2;self.setFixedHeight(158)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);r=self.report
        cells=[('会话数',f"{r.get('sessions',0):,}"),('活跃天数',str(r.get('active_days',0))),
               ('Token 总量',compact_tokens(r.get('all_total',0))),('最常用模型',r.get('favorite_model','暂无记录')),
               ('消息数',f"{r.get('messages',0):,}"),('高峰时段',f"{r['peak_hour']:02}:00–{r['peak_hour']+1:02}:00" if r.get('peak_hour') is not None else '暂无用量')]
        width=(self.width()-4)/2
        p.setPen(QColor(PRIMARY));p.setFont(font(11));p.drawText(QRectF(1,0,self.width()-2,16),Qt.AlignmentFlag.AlignVCenter,'累计 · 本机记录')
        p.drawText(QRectF(1,100,self.width()-2,16),Qt.AlignmentFlag.AlignVCenter,'昨日 · '+r.get('day','--'))
        for i,(label,value) in enumerate(cells):
            rect=QRectF((i%2)*(width+4),18+(i//2)*41+(18 if i>=4 else 0),width,37)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#f1ecf6'));p.drawRoundedRect(rect,6,6)
            p.setPen(MUTED);p.setFont(font(10,True));p.drawText(rect.adjusted(6,2,-3,-20),Qt.AlignmentFlag.AlignVCenter,label)
            p.setPen(INK);p.setFont(font(11 if i in (3,5) else 14,True))
            p.drawText(rect.adjusted(6,17,-5,-2),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(value,Qt.TextElideMode.ElideRight,round(width-11)))

class ReportPlot(QWidget,RasterChart):
    hoverText=Signal(str)
    def __init__(self,report,mode='line',period='7d',selected=None,parent=None,series=None):
        super().__init__(parent);self.report=report;self.mode=mode;self.series=(series if series is not None else model_series(report,period)) if mode=='bars' else None
        self.selected=selected;self.hits=[];self.points=[];self._hover='';self._resume_time=None;self.setMouseTracking(True);self.setFixedHeight(94)
        self.reveal=ChartReveal(self)
        self._measure_axes()
    def set_data(self,report,series=None,selected=None):
        self.report=report;self.series=series;self.selected=selected;self.hits=[];self._measure_axes();self.invalidate_layers();self._set_hover('');self.update()
    def _measure_axes(self):
        values=self.report.get('hours',[0]*24) if self.mode=='line' else [b['values'].get(self.selected,0) if self.selected else b['total'] for b in self.series['bins']]
        top=max(values,default=0);self._axis_font=font(10,True);self._axis_metrics=QFontMetrics(self._axis_font)
        self._axis_labels=[compact_tokens(round(top*f)) for f in (0,.5,1)]
        self._axis_left=max(37,max(self._axis_metrics.horizontalAdvance(t) for t in self._axis_labels)+7)
    def begin_reveal(self):self.ensure_layers();self._resume_time=None;self.reveal.prepare()
    def freeze_reveal(self):
        self._resume_time=self.reveal.animation.currentTime() if self.reveal.animation.state()==QAbstractAnimation.State.Running else None
        self.reveal.stop()
    def start_reveal(self):
        if self._resume_time is not None and self.isVisible():
            ms=self._resume_time;self._resume_time=None
            self.reveal.animation.start();self.reveal.animation.setCurrentTime(ms)
        else:self.reveal.start()
    def showEvent(self,event):
        super().showEvent(event)
        # Newly inserted scroll-area children are not visible in the click
        # handler. Start after their first layout/show, rather than lose the
        # pending reveal forever. Hidden/replaced plots cannot start a timer.
        if self.reveal.pending or self._resume_time is not None:QTimer.singleShot(0,self,self.start_reveal)
    def hideEvent(self,event):self.reveal.stop();super().hideEvent(event)
    def chart_rect(self):
        top=math.ceil(self._axis_metrics.height()/2)+2
        return QRectF(self._axis_left,top,max(1,self.width()-self._axis_left-6),max(1,self.height()-self._axis_metrics.height()-6-top))
    def chart_mode(self):return self.mode
    trace_color=COLORS[0]
    def paintEvent(self,event):self.paint_layers()
    def render_layers(self,p,dynamic):
        chart=self.chart_rect();bottom=chart.bottom();self.hits=[]
        if self.mode=='line':values=self.report.get('hours',[0]*24);top=max(values,default=0)
        else:
            bins=self.series['bins'];values=[b['values'].get(self.selected,0) if self.selected else b['total'] for b in bins];top=max(values,default=0)
        p.setFont(self._axis_font)
        for f,text in zip((0,.5,1),self._axis_labels):
            y=bottom-chart.height()*f;p.setPen(QPen(QColor('#e9e1ef'),.7));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
            p.setPen(MUTED)
            baseline=y+(self._axis_metrics.ascent()-self._axis_metrics.descent())/2
            p.drawText(QPointF(chart.left()-6-self._axis_metrics.horizontalAdvance(text),baseline),text)
        slot=chart.width()/max(1,len(values));points=[];self.points=points;self.curve=None;path=QPainterPath();static=p;p=dynamic
        if self.mode=='line':
            for i,value in enumerate(values):
                point=QPointF(chart.left()+(i+.5)*chart.width()/24,bottom-chart.height()*value/max(1,top));points.append(point)
                self.hits.append((QRectF(point.x()-slot/2,chart.top(),slot,chart.height()),f"{i:02}:00–{i+1:02}:00 · {value:,} Tokens"))
            self.curve=SmoothTrace(points);path=self.curve.path
            fill=QPainterPath(path);fill.lineTo(points[-1].x(),bottom);fill.lineTo(points[0].x(),bottom);fill.closeSubpath();p.fillPath(fill,QColor('#ebe2f2'))
            p.setPen(QPen(QColor(COLORS[0]),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.drawPath(path)
            labels=[(0,'00'),(.5,'12'),(1,'24时')]
        else:
            model_order=[m['model'] for m in self.series['models']]
            for i,(b,value) in enumerate(zip(bins,values)):
                y=bottom
                for j,model in enumerate(model_order):
                    if self.selected and model!=self.selected:continue
                    amount=b['values'].get(model,0);height=chart.height()*amount/max(1,top)
                    p.fillRect(QRectF(chart.left()+i*slot,y-height,max(.8,slot-1.5),height),QColor(COLORS[j%len(COLORS)]));y-=height
                label=b['start'] if b['start']==b['end'] else b['start']+' 至 '+b['end']
                self.hits.append((QRectF(chart.left()+i*slot,chart.top(),slot,chart.height()),label+f' · {value:,} Tokens'))
            labels=[(0,self.series['start'][5:].replace('-','/')),(1,self.series['end'][5:].replace('-','/'))]
        p=static;p.setFont(font(10,True));p.setPen(MUTED)
        for f,text in labels:
            x=chart.left()+f*chart.width();rect=QRectF(x-(30 if f==1 else 0 if f==0 else 15),bottom+4,32,self._axis_metrics.height()+2)
            p.drawText(rect,Qt.AlignmentFlag.AlignVCenter| (Qt.AlignmentFlag.AlignRight if f==1 else Qt.AlignmentFlag.AlignLeft),text)
        if not top:p.drawText(chart,Qt.AlignmentFlag.AlignCenter,'暂无 Token 用量')
    def mouseMoveEvent(self,event):
        hovered=''
        for rect,text in self.hits:
            if rect.contains(event.position()):hovered=text;break
        self._set_hover(hovered)
        super().mouseMoveEvent(event)
    def _set_hover(self,text):
        if text!=self._hover:self._hover=text;self.hoverText.emit(text)
    def leaveEvent(self,event):self._set_hover('');super().leaveEvent(event)

class ModelRow(QToolButton):
    def __init__(self,item,total,index,selected,slot):
        super().__init__();self.item=item;self.total=total;self.index=index;self.selected=selected
        self.setFixedHeight(38);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(item['model']+f" · {item['total']:,} Tokens")
        self.setCheckable(True);self.setChecked(selected)
        self.clicked.connect(slot)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.selected or self.underMouse():p.fillRect(self.rect(),QColor('#f0e9f5'))
        if self.selected:
            p.setPen(QPen(QColor(PRIMARY),2));p.drawLine(0,3,0,self.height()-3)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(COLORS[self.index%len(COLORS)]));p.drawRoundedRect(QRectF(1,7,7,7),2,2)
        p.setPen(INK);p.setFont(font(11,True));name=QFontMetrics(p.font()).elidedText(self.item['model'],Qt.TextElideMode.ElideRight,max(20,self.width()-120))
        p.drawText(QRectF(13,1,self.width()-122,19),Qt.AlignmentFlag.AlignVCenter,name)
        text=compact_tokens(self.item['total'])+f" · {self.item['total']/max(1,self.total)*100:.1f}%"
        p.drawText(QRectF(self.width()-115,1,114,19),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,text)
        p.setPen(QColor('#62576e'));p.setFont(font(10,True))
        detail=compact_tokens(self.item['input'])+' in · '+compact_tokens(self.item['output'])+' out' if self.item['known'] else '输入 / 输出分项记录不完整'
        p.drawText(QRectF(13,18,self.width()-15,17),Qt.AlignmentFlag.AlignVCenter,detail)

class DailyReport(QWidget):
    refreshRequested=Signal()
    GAP=6
    PAD=8
    def __init__(self,bubble):
        flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint
        if __import__('sys').platform=='darwin':flags|=Qt.WindowType.WindowDoesNotAcceptFocus
        if bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint:flags|=Qt.WindowType.WindowStaysOnTopHint
        super().__init__(bubble,flags);self.bubble=bubble;self.requested=False;self.page='overview';self.period='all';self.selected_model=None
        self.snapshot={};self.natural_height=412;self._overview_height=412;self.fraction=0.;self._building=False
        self.book_index=0;self._book_opened=False
        self._animating=False;self._frame=None;self._pending_rebuild=False;self._syncing=False;self._series_cache={}
        self.refresh_busy=False
        self.setWindowTitle('白龙 · Token 日报');self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet('QLabel{'+FONT_CSS+'color:#393343;background:transparent;}QScrollArea{border:0;background:transparent;}QScrollBar:vertical{background:#f5f0f8;width:7px;margin:0;border-radius:3px;}QScrollBar::handle:vertical{background:#c7b7d7;min-height:18px;border-radius:3px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}')
        self.surface=QWidget(self);self.layout=QVBoxLayout(self.surface);self.layout.setContentsMargins(10,8,10,8);self.layout.setSpacing(5)
        self.refresh_button=action_button('refresh','刷新日报',parent=self.surface,hit_size=28)
        self.refresh_button.setObjectName('report_refresh');self.refresh_button.clicked.connect(self.request_refresh)
        self.refresh_button.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(260);self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._finished)
        from linked_report_motion import LinkedReportMotion
        self.follow=LinkedReportMotion(self);self.animation.finished.connect(bubble._apply_pending_mode)
        bubble.installEventFilter(self);self.hide();self.rebuild()
    def label(self,text,size=11,bold=False):
        size=max(11,size)
        w=QLabel(text);w.setFont(font(size,bold));w.setTextFormat(Qt.TextFormat.PlainText)
        # Bubble's inherited QLabel rule otherwise overrides setFont(…).
        w.setStyleSheet(FONT_CSS+f'font-size:{size}px;font-weight:{600 if size>14 else 500};color:#393343;background:transparent;');return w
    def card(self,name):
        w=QWidget();w.setObjectName(name)
        w.setStyleSheet('QWidget#'+name+'{background:#f5f0f8;border-radius:7px;}')
        layout=QVBoxLayout(w);layout.setContentsMargins(7,5,7,5);layout.setSpacing(0)
        return w,layout
    def secondary(self,label):
        label.setStyleSheet(label.styleSheet()+'color:#62576e;background:transparent;');return label
    def set_snapshot(self,snapshot):
        snapshot=snapshot or {};previous=self.snapshot;self.snapshot=snapshot
        r=snapshot.get('report') or {};old=previous.get('report') or {}
        if r==old and all(snapshot.get(k)==previous.get(k) for k in ('partial','unavailable')):return
        if r.get('day')!=old.get('day') or r.get('daily_models')!=old.get('daily_models'):self._series_cache.clear()
        if self._animating or self.follow.active:
            self._pending_rebuild=True;return
        if self.requested:
            if r and self.report:
                self.report=r;self.day_label.setText(r['day'][5:].replace('-','/')+' · 昨日')
                if self.page=='overview':
                    self.stats.report=r;self.stats.update()
                    self.hour_total.setText(compact_tokens(r.get('yesterday_total',0)))
                    if r.get('hours')!=old.get('hours'):self.plot.set_data(r)
                    self._update_analogy(r)
                else:self._update_models()
                self.note_label.setText(self._note(r));self.update()
                self._update_data_state()
                if self.page=='overview':self.sync_geometry()
            else:
                self.rebuild();self.sync_geometry();self.chart_entry()
    def request_refresh(self):
        if self.refresh_busy:return
        self.set_refresh_busy(True);self.refreshRequested.emit()
    def set_refresh_busy(self,busy):
        self.refresh_busy=bool(busy);self.refresh_button.set_busy(self.refresh_busy)
        self.refresh_button.setToolTip('正在刷新日报…' if busy else '刷新日报')
    def finish_refresh(self,success=True):
        self.refresh_busy=False;self.refresh_button.finish(success)
        self.refresh_button.setToolTip('日报已刷新' if success else '日报刷新失败，保留上次统计；点击重试')
    def _series(self):
        if self.period not in self._series_cache:self._series_cache[self.period]=model_series(self.report,self.period)
        series=self._series_cache[self.period]
        if self.selected_model and not any(item['model']==self.selected_model for item in series['models']):self.selected_model=None
        return series
    def chart_entry(self):
        if not self._animating and not self.follow.active and self.plot:
            self.plot.begin_reveal();QTimer.singleShot(0,self.plot,self.plot.start_reveal)
    def set_page(self,page):
        if self.page==page:
            self.page_buttons[page].setChecked(True);return
        self.page=page;self.rebuild();self.sync_geometry();self.chart_entry()
    def set_period(self,period):
        if self.period==period:
            if period in self.range_buttons:self.range_buttons[period].setChecked(True)
            return
        self.period=period;self.selected_model=None
        if self._animating or self.follow.active:self._pending_rebuild=True;return
        if self.page=='models' and self.report:self._update_models();self.chart_entry()
    def select_model(self,model):
        self.selected_model=None if self.selected_model==model else model
        if self._animating or self.follow.active:self._pending_rebuild=True;return
        if self.page=='models' and self.report:self._update_models();self.chart_entry()
    def _update_models(self):
        series=self._series()
        shown=next((m['total'] for m in series['models'] if m['model']==self.selected_model),series['total'])
        self.model_total.setText('Token · '+compact_tokens(shown)+'  / 截至 '+self.report['day'][5:].replace('-','/'))
        self.plot.set_data(self.report,series,self.selected_model)
        for period,button in self.range_buttons.items():button.setChecked(period==self.period)
        items=series['models']
        # Keep the clicked controls and scroll-area alive. Only changed model
        # membership requires new rows; a filter updates their paint state.
        if [r.item['model'] for r in self.model_rows]!=[item['model'] for item in items]:
            while self.model_layout.count():
                w=self.model_layout.takeAt(0).widget()
                if w:w.hide();w.deleteLater()
            self._add_model_rows(series)
            # A refresh may add many models while the viewport already exists.
            # Resolve the new extent now, instead of waiting for a nested
            # LayoutRequest and showing clipped rows until another UI event.
            self.model_layout.invalidate();self.model_layout.activate();body=self.scroll.widget()
            body.layout().invalidate();body.layout().activate()
            body.setMinimumHeight(body.minimumSizeHint().height());body.updateGeometry()
        else:
            for i,(row,item) in enumerate(zip(self.model_rows,items)):
                row.item=item;row.total=series['total'];row.index=i;row.selected=self.selected_model==item['model']
                row.setChecked(row.selected)
                row.setAccessibleName(item['model']+f" · {item['total']:,} Tokens");row.update()
        self._update_filter_label()
    def _update_filter_label(self):
        if not hasattr(self,'filter_label'):return
        self.filter_label.setText('筛选：'+self.selected_model if self.selected_model else '范围内全部模型')
        self.clear_filter.setVisible(bool(self.selected_model))
    def clear_model_filter(self):
        if self.selected_model:self.select_model(self.selected_model)
    def _add_model_rows(self,series):
        self.model_rows=[]
        for i,item in enumerate(series['models']):
            row=ModelRow(item,series['total'],i,self.selected_model==item['model'],lambda checked=False,m=item['model']:self.select_model(m))
            self.model_rows.append(row);self.model_layout.addWidget(row);row.show()
        if not self.model_rows:self.model_layout.addWidget(self.label('该时间范围内暂无模型用量',11))
    def _note(self,r):
        if self.snapshot.get('unavailable'):return '当前统计暂不可用；图中保留上次成功的本机记录。'
        if self.snapshot.get('readable_files')==0:return '源日志暂不可读；显示本机历史统计，近期用量可能不完整。'
        if self.page=='overview':
            note='本机日志 · 输入含缓存 · 输出含推理'
            return note+(' · 部分日志受限' if self.snapshot.get('partial') else '')+(' · 部分模型未识别' if r.get('metadata_incomplete') else '')
        note='仅统计本机可读日志；输入含缓存，输出含推理。'
        return note+(' 部分日志受限。' if self.snapshot.get('partial') else '')+(' 部分历史记录缺少模型信息。' if r.get('metadata_incomplete') else '')
    def _update_data_state(self):
        if not hasattr(self,'data_state'):return
        unavailable=self.snapshot.get('unavailable');partial=self.snapshot.get('partial')
        self.data_state.setText('当前受限 · 以下为上次成功统计' if unavailable else '部分日志受限 · 统计可能不完整')
        self.data_state.setVisible(bool(unavailable or partial) and bool(self.report))
    def _update_analogy(self,r):
        data=book_analogy(r.get('all_total',0),self.book_index)
        self.analogy.setText('<span style="font-size:11px;font-weight:500;color:#62576e">累计用量相当于约</span><br><span style="font-size:12px;font-weight:500;color:#514360">'+escape(data['quantity']+' 本《'+data['book']['title']+'》')+'</span>')
        self.analogy.setAccessibleName(data['sentence'])
        self.book_estimate.setText(data['estimate'])
        self.book_estimate.setAccessibleName(data['estimate']+'；Project Gutenberg '+data['book']['source']+'；o200k_base 参考计数，非账单精确值')
    def next_book(self):
        self.book_index=(self.book_index+1)%len(book_catalog()['books'])
        self._update_analogy(self.report)
        self.sync_geometry()
    def rebuild(self):
        if self._animating or self.follow.active:
            self._pending_rebuild=True;return
        self._building=True
        self.refresh_button.hide();self.refresh_button.setParent(self.surface)
        while self.layout.count():
            w=self.layout.takeAt(0).widget()
            if w:w.hide();w.deleteLater()
        width=self.bubble.width();self.surface.setFixedWidth(width);r=self.snapshot.get('report') or {};self.report=r
        header=QWidget();row=QHBoxLayout(header);row.setContentsMargins(0,0,0,0);row.setSpacing(3)
        self.day_label=self.label((r.get('day','--')[5:].replace('-','/'))+' · 昨日',10)
        row.addWidget(self.label('日报',12,True));row.addWidget(self.day_label);row.addStretch()
        row.addWidget(self.refresh_button);self.refresh_button.show()
        close=action_button('close','关闭日报',hit_size=28);close.clicked.connect(self.dismiss);row.addWidget(close);self.layout.addWidget(header)
        nav=QWidget();row=QHBoxLayout(nav);row.setContentsMargins(0,0,0,0);row.setSpacing(2)
        self.page_buttons={}
        for page,text in [('overview','概览'),('models','模型')]:
            b=tab(text,lambda checked=False,k=page:self.set_page(k),self.page==page);b.setObjectName('report_'+page);row.addWidget(b);self.page_buttons[page]=b
        row.addStretch()
        self.range_buttons={}
        if self.page=='models':
            for period,text in [('all','全部'),('30d','30天'),('7d','7天')]:
                b=tab(text,lambda checked=False,k=period:self.set_period(k),self.period==period);b.setObjectName('report_range_'+period);row.addWidget(b);self.range_buttons[period]=b
        self.layout.addWidget(nav)
        self.readout=None
        self.scroll=QScrollArea();self.scroll.setMinimumSize(0,0);self.scroll.setWidgetResizable(True);self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if self.page=='overview' else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body=QWidget();body.setStyleSheet('background:transparent;');content=QVBoxLayout(body);content.setContentsMargins(0,0,2,0);content.setSpacing(4)
        self.data_state=self.label('',11,True);self.data_state.setWordWrap(True);self.data_state.setStyleSheet(self.data_state.styleSheet()+'color:#89566c;');content.addWidget(self.data_state);self._update_data_state()
        if not r:
            content.addWidget(self.label('正在整理本机 Token 记录…' if not self.snapshot.get('unavailable') else '统计暂不可用，请稍后刷新'));self.plot=None
            self.body_height=100
        elif self.page=='overview':
            self.stats=OverviewStats(r);self.stats.set_columns(width-22);content.addWidget(self.stats)
            chart,chart_layout=self.card('report_hourly_card')
            title=QHBoxLayout();title.setContentsMargins(0,0,0,0)
            title.addWidget(self.label('昨日 Token',11,True));title.addStretch()
            self.hour_total=self.label(compact_tokens(r.get('yesterday_total',0)),14,True)
            title.addWidget(self.hour_total);chart_layout.addLayout(title)
            self.plot=ReportPlot(r);chart_layout.addWidget(self.plot)
            self.readout=self.secondary(self.label('00–24 时 · 每小时消耗',9))
            self.readout.setObjectName('report_hourly_readout');chart_layout.addWidget(self.readout)
            self.plot.hoverText.connect(lambda text,label=self.readout:label.setText(text or '00–24 时 · 每小时消耗'))
            content.addWidget(chart)
            self.body_height=self.stats.height()+94+18+17+20
        else:
            series=self._series()
            shown=next((m['total'] for m in series['models'] if m['model']==self.selected_model),series['total'])
            self.model_total=self.label('Token · '+compact_tokens(shown)+'  / 截至 '+r['day'][5:].replace('-','/'),11,True);content.addWidget(self.model_total)
            filter_bar=QWidget();filter_layout=QHBoxLayout(filter_bar);filter_layout.setContentsMargins(0,0,0,0);filter_layout.setSpacing(4)
            self.filter_label=self.label('',11,True);self.filter_label.setWordWrap(True);filter_layout.addWidget(self.filter_label,1)
            self.clear_filter=tab('清除筛选',self.clear_model_filter);self.clear_filter.setObjectName('report_clear_model_filter');filter_layout.addWidget(self.clear_filter);content.addWidget(filter_bar);self._update_filter_label()
            self.plot=ReportPlot(r,'bars',self.period,self.selected_model,series=series);content.addWidget(self.plot)
            denominator=self.secondary(self.label('模型占比 = 该模型 / 当前时间范围全部模型',10));denominator.setWordWrap(True);content.addWidget(denominator)
            self.readout=self.secondary(self.label('点击模型筛选 · 再点一次还原',9))
            self.plot.hoverText.connect(lambda text,label=self.readout:label.setText(text or '点击模型筛选 · 再点一次还原'))
            content.addWidget(self.readout)
            model_group=QWidget();self.model_layout=QVBoxLayout(model_group);self.model_layout.setContentsMargins(0,0,0,0);self.model_layout.setSpacing(4)
            self._add_model_rows(series);content.addWidget(model_group)
            self.body_height=163+min(4,max(1,len(series['models'])))*43
        self.scroll.setWidget(body);self.layout.addWidget(self.scroll,1)
        self.body_height+=30
        if self.readout:
            self.readout.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            self.readout.setFixedHeight(max(16,QFontMetrics(self.readout.font()).height()+2))
        if self.page=='overview' and r:
            comparison,comparison_layout=self.card('report_comparison_card');comparison_layout.setSpacing(2)
            line=QHBoxLayout();line.setContentsMargins(0,0,0,0);line.setSpacing(2)
            analogy=self.label('',9);analogy.setTextFormat(Qt.TextFormat.RichText);analogy.setWordWrap(True)
            analogy.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            self.analogy=analogy;line.addWidget(analogy,1)
            change=action_button('book','换一本书',hit_size=28);change.setObjectName('report_next_book');change.clicked.connect(self.next_book);line.addWidget(change)
            comparison_layout.addLayout(line)
            self.book_estimate=self.secondary(self.label('',8));self.book_estimate.setWordWrap(True);comparison_layout.addWidget(self.book_estimate)
            self._update_analogy(r)
            content.addWidget(comparison)
            self.body_height+=43
        foot=self.secondary(self.label(self._note(r),8));foot.setWordWrap(True);self.note_label=foot
        content.addWidget(foot)
        content.addStretch()
        # Measure the whole overview, including wrapped book/source notes.
        # Models reuse this canvas and scroll only when their rows overflow it.
        self._building=False
        self._measure_overview()
    def _measure_overview(self):
        if self.page=='overview':
            for widget in [self.surface]+self.surface.findChildren(QWidget):widget.ensurePolished()
            body=self.scroll.widget();available=max(1,self.surface.width()-20)
            body.ensurePolished();content=body.layout()
            height=content.totalHeightForWidth(available)
            if height<0:height=content.sizeHint().height()
            margins=self.layout.contentsMargins()
            header=sum(self.layout.itemAt(i).widget().sizeHint().height() for i in (0,1))
            self._overview_height=height+header+margins.top()+margins.bottom()+2*self.layout.spacing()+2
        self.natural_height=self._overview_height
    def reserved_height(self):
        area=(self.bubble.screen() or QApplication.primaryScreen()).availableGeometry()
        return min(self.natural_height+self.PAD,max(0,area.height()-self.bubble.height()-self.GAP)) if self.requested else 0
    def toggle(self):self.dismiss() if self.requested else self.open()
    def open(self):
        reversing=self._animating
        self.animation.stop()
        self.requested=True
        if not reversing:
            count=len(book_catalog()['books'])
            self.book_index=(self.book_index+1+random.randrange(count-1))%count if self._book_opened else random.randrange(count)
            self._book_opened=True
            top=bool(self.bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
            if bool(self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=top:self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top)
            self.rebuild();owner=self.bubble.owner_pet()
            if owner and getattr(owner,'enhanced_ready',False):owner.stop_walk();owner.position_bubble()
            self.sync_geometry();self._prepare_frame()
        self.show();self.raise_();self._input_passthrough(True)
        self.follow.prewarm()
        self._start_animation(1.)
    def dismiss(self):
        if not self.requested and not self.isVisible():return
        if self.follow.active:
            if self.follow.committed:self._dismiss_after_host=True;return
            self.follow.cancel()
        self.animation.stop();self.requested=False
        if not self._animating:
            self.sync_geometry();self._prepare_frame()
        self._input_passthrough(True);self._start_animation(0.)
    def _input_passthrough(self,value):
        # Do not recreate the layered window with QWidget.setWindowFlags.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,value)
        if self.windowHandle():self.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput,value)
    def _prepare_frame(self):
        self.refresh_button.freeze_motion('surface')
        if self.plot:
            if self.requested:self.plot.begin_reveal()
            else:self.plot.freeze_reveal()
        # Nested cards/scroll content must settle before raster capture, rather
        # than processing their first LayoutRequest after the reveal finishes.
        widgets=[self.surface]+self.surface.findChildren(QWidget)
        for widget in reversed(widgets):
            widget.ensurePolished()
            if widget.layout():widget.layout().activate()
        for widget in widgets:
            if widget.layout():widget.layout().activate()
        # Wrapped labels now have their final metrics; settle the complete
        # target before freezing it, never grow a pixel at native handoff.
        self.sync_geometry()
        ratio=self.devicePixelRatioF();size=self.surface.size()
        frame=QPixmap(round(size.width()*ratio),round(size.height()*ratio));frame.setDevicePixelRatio(ratio)
        frame.fill(QColor('#fcfafc'))
        self.surface.render(frame,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        self._frame=frame;self._animating=True
        button=self.bubble.findChild(QToolButton,'bubble_report')
        x=button.mapToGlobal(button.rect().center()).x() if button and button.isVisible() else self.bubble.geometry().center().x()
        self._merge_anchor=QPointF(x-self.x(),self.bubble.y()+1-self.y())
        # Native children/scroll areas are absent from the animated presentation.
        # The complete opaque image is ready before changing their visibility.
        self.surface.hide();self.repaint()
    def _start_animation(self,target):
        start=self.fraction
        # Changing duration/range can emit valueChanged using the old current
        # time. Configure atomically so a quick reversal never jumps to 1/0.
        blocked=self.animation.blockSignals(True)
        self._motion_start=start;self._motion_target=target
        self.animation.setDuration(max(1,round((DISMISS_MS if target==0. else EXPAND_MS)*min(1.,abs(target-start)))))
        self.animation.setStartValue(0.);self.animation.setEndValue(1.);self.animation.setCurrentTime(0)
        self.animation.blockSignals(blocked);self.fraction=start;self.animation.start()
    def content_geometry(self):
        return QRect(self.x()+self.PAD,self.y()+self.PAD,self.surface.width(),self.surface.height())
    def visual_rect(self):
        bounds=QRectF(self.PAD,self.PAD,self.surface.width(),self.surface.height())
        if self._frame is None:return bounds
        # A true zero-size endpoint joins the main surface instead of leaving
        # a floating 132x32 seed in the six-pixel gap.
        f=max(0.,self.fraction);a=self._merge_anchor
        width=bounds.width()*(math.sqrt(f) if f<=1. else 1.+(f-1.)*.35)
        height=bounds.height()*f
        center=a.x()+(bounds.center().x()-a.x())*f
        bottom=a.y()+(bounds.bottom()-a.y())*f
        return QRectF(center-width/2,bottom-height,width,height)
    def visible_height(self):return 0 if self.fraction<=0. else round(self.visual_rect().height())
    def _advance(self,value):
        progress=dismiss_progress(value) if self._motion_target==0. else island_response(value)
        self.fraction=self._motion_start+(self._motion_target-self._motion_start)*progress
        # One fixed-size native window, one raster draw. No move/resize/layout
        # operations on animation frames, in either direction.
        self.repaint()
    def _finished(self):
        from panel_transition import present_barrier
        guarded=self.requested and self._animating and QApplication.platformName()=='windows'
        if guarded:
            self.follow.shield.present(self.grab(),self.geometry());present_barrier()
        self._animating=False
        if not self.requested:
            self.fraction=0.;self._frame=None;self.surface.hide()
            self.repaint();self.hide();return
        enabled=self.updatesEnabled();self.setUpdatesEnabled(False)
        try:
            if self._pending_rebuild:
                self._pending_rebuild=False;self.rebuild()
                if self.plot:self.plot.begin_reveal()
            self.fraction=1.;self.sync_geometry();self.surface.move(self.PAD,self.PAD);self.surface.show()
            self.refresh_button.resume_motion('surface')
            self._frame=None;self._input_passthrough(False)
        finally:self.setUpdatesEnabled(enabled)
        self.repaint()
        if guarded:
            present_barrier();self.follow.park(self.follow.shield)
        if self.plot:self.plot.start_reveal()
    def sync_geometry(self):
        if self._building or self._syncing or self.follow.active:return
        b=self.bubble
        if not b.isVisible():self.hide();return
        if self._animating or self.follow.active:
            # Follow an anchor move without invalidating the backing store.
            # Width/height changes wait until the frozen frame is released.
            if self.requested:
                self.move(b.x()-self.PAD,b.y()-self.GAP-self.surface.height()-self.PAD)
            return
        self._syncing=True
        try:
            area=(b.screen() or QApplication.primaryScreen()).availableGeometry();width=b.width()
            if self.surface.width()!=width:
                self.surface.setFixedWidth(width)
                if self.page=='overview' and getattr(self,'stats',None):self.stats.set_columns(width-22)
            self._measure_overview()
            target=max(1,min(self.natural_height,b.y()-area.top()-self.GAP-self.PAD))
            if self.surface.size()!=QSize(width,target):self.surface.setFixedSize(width,target)
            self.surface.move(self.PAD,self.PAD);self.layout.activate()
            self.setGeometry(b.x()-self.PAD,b.y()-self.GAP-target-self.PAD,width+2*self.PAD,target+2*self.PAD)
            if self.isVisible():self.repaint()
        finally:self._syncing=False
    def eventFilter(self,obj,event):
        if obj is self.bubble:
            if event.type() in (QEvent.Type.Move,QEvent.Type.Resize):
                if not self.follow.active and (self.requested or self.isVisible()):self.sync_geometry()
            elif event.type()==QEvent.Type.Hide:self.hide()
        return False
    def hideEvent(self,event):
        self.follow.cancel()
        self.animation.stop();self.requested=False;self.fraction=0.;self._animating=False;self._frame=None
        self._input_passthrough(False);self.surface.hide()
        self.refresh_button.resume_motion('surface')
        super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Explicitly clear the previous reveal region in the same backing store.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.follow.active:return  # Only the independent fixed canvas presents linked motion.
        if not self.requested and not self._animating and self.surface.isHidden():return
        content=stage(self.fraction,.02,.28) if self._animating and not self.requested else None
        paint_card(p,self.visual_rect(),self._frame,self.fraction if self._frame is not None else 1.,content_progress=content)
