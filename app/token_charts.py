"""Small, readable token bars and calendar-day hourly consumption curve."""
import time
from datetime import datetime
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QPainterPath,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QToolTip,QSizePolicy
from compact_bubble import font,INK,MUTED,FONT_CSS
from token_calendar import usage_series,compact_tokens,TOKEN_RANGES
from chart_reveal import ChartReveal,RasterChart
from chart_curve import SmoothTrace

class TokenPlot(QWidget,RasterChart):
    def __init__(self,snapshot,period,parent=None,now=None):
        super().__init__(parent);self.hits=[];self.points=[];self.reveal=ChartReveal(self)
        self.setMouseTracking(True);self.setMinimumWidth(0);self.set_data(snapshot,period,now)

    def set_data(self,snapshot,period,now=None):
        self.snapshot=snapshot or {};self.now=time.time() if now is None else now
        self.series=usage_series(snapshot,period,self.now);self.invalidate_layers()
        s=self.series;bucket=s.get('bucket_days',1)
        description=f"{s['title']} · {s['total']:,} Tokens；{s['start']} 至 {s['end']}。"
        description+='每小时消耗，非累计曲线；当天00–24时，当前小时尚未结束。' if s['mode']=='line' else f'每根柱覆盖{bucket}天，悬停查看日期与用量。'
        description+='仅本机可读取日志；输入含缓存，输出含推理，均不重复相加。'
        if self.snapshot.get('checked'):description+='截至'+datetime.fromtimestamp(self.snapshot['checked']).strftime('%m-%d %H:%M')+'。'
        if not s['available']:description+='统计中或暂不可用。'
        if self.snapshot.get('partial'):description+='部分日志暂不可读。'
        self.setAccessibleName('Codex Token '+('小时曲线' if s['mode']=='line' else '用量柱状图'))
        self.setAccessibleDescription(description);self.setToolTip(description);self.update()

    def chart_rect(self):
        # Both the title and the mixed Chinese/numeric axis use the shared
        # small-text font. Reserve its actual height instead of a 12px strip.
        line_height=QFontMetrics(font(11)).height()
        top=max(18,line_height+3);bottom=line_height+3
        return QRectF(2,top,max(1,self.width()-4),max(5,self.height()-top-bottom))
    def chart_mode(self):return self.series['mode']
    trace_color='#8d76ab'
    def paintEvent(self,event):self.paint_layers()
    def render_layers(self,p,dynamic):
        s=self.series;w=self.width();h=self.height();p.setFont(font(11,True));p.setPen(INK)
        title=s['title']+' · '+compact_tokens(s['total']) if s['available'] else ('暂不可用' if self.snapshot.get('unavailable') else '统计中…')
        p.drawText(QRectF(0,0,w,max(16,QFontMetrics(p.font()).height())),Qt.AlignmentFlag.AlignCenter,QFontMetrics(p.font()).elidedText(title,Qt.TextElideMode.ElideRight,w))
        plot=self.chart_rect();bottom=plot.bottom();bins=s['bins'];top=max((b['value'] for b in bins if not b['future']),default=0)
        p.setPen(QPen(QColor('#d8cde3'),.8));p.drawLine(QPointF(plot.left(),bottom),QPointF(plot.right(),bottom))
        p.setPen(QPen(QColor('#e9e1f0'),.6));p.drawLine(QPointF(plot.left(),plot.top()),QPointF(plot.right(),plot.top()))
        self.hits=[];self.points=[];self.curve=None;static=p;p=dynamic
        if s['mode']=='bars':
            slot=plot.width()/max(1,len(bins));gap=1 if len(bins)>15 else 2
            for i,b in enumerate(bins):
                height=plot.height()*b['value']/max(1,top);x=plot.left()+i*slot
                rect=QRectF(x,bottom-height,max(.6,slot-gap),height)
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#8d76ab' if b['current'] else '#b19bc9'))
                if height:p.drawRoundedRect(rect,min(1.5,rect.width()/3),min(1.5,height/3))
                else:
                    p.setPen(QPen(QColor('#c8bbd7'),1));p.drawLine(QPointF(x,bottom),QPointF(x+rect.width(),bottom))
                self.hits.append((QRectF(x,plot.top(),slot,plot.height()+1),b))
            left=s['start'][5:].replace('-','/');right=s['end'][5:].replace('-','/')
            if s['start'][:4]!=s['end'][:4]:
                left=s['start'][2:4]+'年'+str(int(s['start'][5:7]));right=s['end'][2:4]+'年'+str(int(s['end'][5:7]))
        else:
            slot=plot.width()/24;path=QPainterPath();last=None
            current=datetime.fromtimestamp(self.now).hour
            future_left=plot.left()+(current+1)*slot
            static.fillRect(QRectF(future_left,plot.top(),max(0,plot.right()-future_left),plot.height()),QColor('#f0ebf5'))
            for i,b in enumerate(bins):
                self.hits.append((QRectF(plot.left()+i*slot,plot.top(),slot,plot.height()+1),b))
                if b['future'] or not s['available']:continue
                point=QPointF(plot.left()+(i+.5)*slot,bottom-plot.height()*b['value']/max(1,top));self.points.append(point)
                last=point
            if self.points:
                self.curve=SmoothTrace(self.points);path=self.curve.path
                fill=QPainterPath(path);fill.lineTo(last.x(),bottom);fill.lineTo(self.points[0].x(),bottom);fill.closeSubpath()
                p.fillPath(fill,QColor('#e3d7ef'));p.setPen(QPen(QColor('#8d76ab'),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.drawPath(path)
            left,right='00时','24时'
        p=static;p.setFont(font(11));p.setPen(MUTED)
        label_height=QFontMetrics(p.font()).height()+2;label_top=h-label_height
        p.drawText(QRectF(0,label_top,w/2,label_height),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,left)
        p.drawText(QRectF(w/2,label_top,w/2,label_height),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,right)
        if s['mode']=='line':p.drawText(QRectF(w/2-14,label_top,28,label_height),Qt.AlignmentFlag.AlignCenter,'12')
        if s['available'] and not top:
            p.setFont(font(10,True));p.setPen(MUTED);p.drawText(plot,Qt.AlignmentFlag.AlignCenter,'暂无用量')

    def detail(self,b):
        if b['future']:value='尚未到来'
        elif not self.series['available']:value='统计暂不可用' if self.snapshot.get('unavailable') else '正在统计…'
        else:value=f"{b['value']:,} Tokens"
        text=b['label']+' · '+value
        if b['current']:text+='\n当前小时尚未结束' if self.series['mode']=='line' else '\n含今天，今日用量仍在更新'
        return text+'\n本机 Codex 日志 · 输入（含缓存）+ 输出（含推理）'
    def begin_reveal(self):self.ensure_layers();self.reveal.prepare()
    def start_reveal(self):self.reveal.start()
    def hideEvent(self,event):self.reveal.stop();super().hideEvent(event)

    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:
            for rect,b in self.hits:
                if rect.contains(event.pos()):QToolTip.showText(event.globalPos(),self.detail(b),self);return True
        return super().event(event)

class TokenChartCard(QWidget):
    rangeChanged=Signal(str)
    def __init__(self,snapshot=None,parent=None,period='all',now=None):
        super().__init__(parent);self.setMinimumWidth(0)
        self.period=period if period in TOKEN_RANGES else 'all';self.range_buttons={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        tabs=QWidget();tabs.setFixedHeight(18);row=QHBoxLayout(tabs);row.setContentsMargins(0,0,0,0);row.setSpacing(1)
        for key,text,tip in [('all','全部','全部本机记录；较长时间自动合并日期分组'),('30d','30天','最近30天，每天一根柱'),('7d','7天','最近7天，每天一根柱')]:
            button=QToolButton();button.setObjectName('token_range_'+key);button.setText(text);button.setToolTip(tip)
            button.setAccessibleName(tip);button.setCheckable(True);button.setChecked(self.period==key);button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor);button.setFixedHeight(18)
            button.setStyleSheet('QToolButton{'+FONT_CSS+'font-size:11px;font-weight:500;color:#76638c;border:0;padding:0;background:transparent;border-radius:4px;}QToolButton:checked{background:#e8def0;color:#514360;}QToolButton:hover{background:#eee7f5;}')
            button.clicked.connect(lambda checked=False,k=key:self.rangeChanged.emit(k));row.addWidget(button,1);self.range_buttons[key]=button
        layout.addWidget(tabs);self.plot=TokenPlot(snapshot,self.period,self,now);layout.addWidget(self.plot,1)
        self.setAccessibleName(self.plot.accessibleName());self.setAccessibleDescription(self.plot.accessibleDescription())

    def set_period(self,period):
        self.period=period
        for key,button in self.range_buttons.items():button.setChecked(key==period)
        self.plot.set_data(self.plot.snapshot,period);self.plot.begin_reveal();self.plot.start_reveal()
