"""Bounded, alpha-aware preview decoder for MP4/WebM/animated WebP."""
from pathlib import Path
import queue,threading,time,math,os
from PIL import Image
from PySide6.QtCore import Qt,QTimer,Signal,QRectF,QSize,QPointF,QEvent
from PySide6.QtGui import QImage,QPainter,QColor,QBrush,QPixmap,QPen
from PySide6.QtWidgets import QWidget
import imageio_ffmpeg
from desktop_reference import reference_rects,MODES

GUIDE_LEGEND=('<span style="color:#278bc0">━ 原白龙固定参照</span>　'
    '<span style="color:#d58b23">━ 标准脚底</span>　'
    '<span style="color:#597bb4">┄ 状态栏 / 面板</span>　'
    '<span style="color:#634d74">┄ 胶囊</span>')

class PreviewDecoder:
    def __init__(self,path,start_index=0,known_meta=None):
        self.path=Path(path);self.start_index=start_index;self.known=known_meta or {}
        self.queue=queue.Queue(6);self.stop=threading.Event();self.meta=None;self.error=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def put(self,item):
        while not self.stop.is_set():
            try:self.queue.put(item,timeout=.05);return True
            except queue.Full:pass
        return False
    def frame(self,im,index,delay):
        if max(im.size)>1100:
            im=im.copy();im.thumbnail((1100,1100),Image.Resampling.BILINEAR)
        rgba=im.convert('RGBA');data=rgba.tobytes()
        frame=QImage(data,rgba.width,rgba.height,rgba.width*4,QImage.Format.Format_RGBA8888).copy()
        return self.put((index,frame,max(.01,delay)))
    def run(self):
        reader=None
        try:
            if self.path.suffix.lower() in ('.webp','.gif','.png'):
                with Image.open(self.path) as image:
                    count=getattr(image,'n_frames',1);index=min(self.start_index,count-1);image.seek(0);image.load()
                    delay=float(image.info.get('duration',1000/24))/1000
                    duration=float(self.known.get('duration',count*delay));fps=float(self.known.get('fps',1/max(delay,.01)))
                    self.meta=dict(size=list(image.size),frames=count,duration=duration,fps=fps,alpha='A' in image.getbands())
                    for index in range(index,count):
                        if self.stop.is_set():return
                        image.seek(index);image.load()
                        if not self.frame(image,index,float(image.info.get('duration',delay*1000))/1000):return
            else:
                params=['-c:v','libvpx-vp9'] if self.path.suffix.lower()=='.webm' else []
                fps=float(self.known.get('fps',24))
                if self.start_index:params+=['-ss',str(self.start_index/fps)]
                reader=imageio_ffmpeg.read_frames(str(self.path),pix_fmt='rgba',bits_per_pixel=32,input_params=params)
                info=next(reader);size=info['size'];fps=float(info['fps'] or fps)
                duration=float(self.known.get('duration',info.get('duration',0)))
                count=int(self.known.get('frames') or max(1,round(duration*fps)))
                self.meta=dict(size=list(size),frames=count,duration=duration,fps=fps,alpha=self.path.suffix.lower()=='.webm')
                for index,raw in enumerate(reader,self.start_index):
                    if self.stop.is_set():return
                    if not self.frame(Image.frombytes('RGBA',size,raw),index,1/fps):return
            self.put(('end',None,0))
        except Exception as error:
            self.error=str(error);self.put(('error',None,0))
        finally:
            if reader is not None:reader.close()
    def close(self):self.stop.set()

class PreviewCanvas(QWidget):
    frameChanged=Signal(int,dict)
    errorOccurred=Signal(str)
    playingChanged=Signal(bool)
    dragStarted=Signal()
    dragDelta=Signal(float,float)
    dragFinished=Signal()
    scaleRequested=Signal(float,bool)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(260,120)
        self.setObjectName('previewCanvas');self.decoder=None;self.path=None;self.image=None
        self.meta={};self.playing=False;self.loop=True;self.speed=1.;self.background='透明棋盘'
        self.index=0;self.due=0.;self.zoom=1.;self.ended=False;self.message='选择左侧素材，直接在这里预览'
        self.scene=None;self.view_mode='适合窗口';self.actual_scale=1.;self.guides=True;self.ghost=False
        self.editable=False;self.drag_origin=None;self.gesture_factor=None;self.gesture_anchor_screen=None;self.drag_was_playing=False;self.panel_mode=MODES[0]
        self.setMouseTracking(True)
        self.reference=QImage(str(Path(__file__).parent/'白龙标准参考.png'))
        with Image.open(Path(__file__).parent/'白龙标准参考.png') as reference:self.reference_box=reference.convert('RGBA').getchannel('A').getbbox()
        self.timer=QTimer(self);self.timer.setInterval(8);self.timer.timeout.connect(self.advance);self.timer.start()
    def load(self,path,autoplay=True,index=0,known_meta=None):
        if self.decoder:self.decoder.close()
        self.path=Path(path);self.meta=known_meta or (self.meta if self.path==getattr(self,'last_path',None) else {})
        self.last_path=self.path;self.decoder=PreviewDecoder(path,index,self.meta)
        self.playing=autoplay;self.due=0.;self.index=index;self.ended=False;self.message='正在加载预览…'
        self.image=None;self.timer.start(8);self.update();self.playingChanged.emit(autoplay)
    def clear(self,message='没有可预览的文件'):
        if self.decoder:self.decoder.close()
        self.decoder=None;self.path=None;self.image=None;self.message=message;self.timer.stop();self.update()
    def set_playing(self,value):
        if value and self.ended and self.path:
            self.load(self.path,True,0,self.meta);return
        self.playing=value;self.due=0.
        if value:self.timer.start(8)
        elif self.image is not None:self.timer.stop()
        self.playingChanged.emit(value)
    def toggle(self):
        if self.path:self.set_playing(not self.playing)
    def seek(self,index):
        if self.path:self.load(self.path,self.playing,index,self.meta)
    def set_background(self,value):self.background=value;self.update()
    def set_speed(self,value):self.speed=max(.25,min(3,float(value)));self.due=0.
    def set_scene(self,scene=None):self.scene=scene;self.update()
    def set_view_mode(self,value):self.view_mode=value;self.update()
    def set_panel_mode(self,value):self.panel_mode=value;self.update()
    def set_editable(self,value):
        self.editable=bool(value)
        self.setToolTip('左键拖动人物改位置；滚轮向上放大、向下缩小；Shift+滚轮细调。数字框同步更新。' if value else '')
        if not value:self.finish_drag(False)
    def hit_subject(self,point):
        if not self.editable or self.image is None or not self.scene:return False
        canvas,target,factor=self.drawing_rects()
        if not canvas.contains(point) or not target.contains(point):return False
        x=int((point.x()-target.left())/target.width()*self.image.width());y=int((point.y()-target.top())/target.height()*self.image.height())
        return 0<=x<self.image.width() and 0<=y<self.image.height() and self.image.pixelColor(x,y).alpha()>=32
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.hit_subject(event.position()):
            canvas,_,factor=self.drawing_rects();anchor=self.scene.get('anchor',[self.scene['canvas'][0]/2,self.scene['canvas'][1]/2])
            self.drag_origin=QPointF(event.position());self.gesture_factor=factor;self.gesture_anchor_screen=QPointF(canvas.x()+anchor[0]*factor,canvas.y()+anchor[1]*factor)
            self.drag_was_playing=self.playing;self.set_playing(False);self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.dragStarted.emit();event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.drag_origin is not None:
            if not event.buttons()&Qt.MouseButton.LeftButton:self.finish_drag(False);return
            delta=(event.position()-self.drag_origin)/self.gesture_factor
            self.dragDelta.emit(delta.x(),delta.y());event.accept();return
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.hit_subject(event.position()) else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.drag_origin is not None and event.button()==Qt.MouseButton.LeftButton:
            delta=(event.position()-self.drag_origin)/self.gesture_factor;self.dragDelta.emit(delta.x(),delta.y())
            self.finish_drag(True);event.accept();return
        super().mouseReleaseEvent(event)
    def finish_drag(self,resume=False):
        if self.drag_origin is None:return
        was_playing=self.drag_was_playing;self.drag_origin=None;self.gesture_factor=None;self.gesture_anchor_screen=None;self.drag_was_playing=False
        self.setCursor(Qt.CursorShape.ArrowCursor);self.dragFinished.emit();self.update()
        if resume and was_playing:self.set_playing(True)
    def event(self,event):
        if event.type() in (QEvent.Type.UngrabMouse,QEvent.Type.WindowDeactivate,QEvent.Type.Hide) and getattr(self,'drag_origin',None) is not None:self.finish_drag(False)
        return super().event(event)
    def wheelEvent(self,event):
        if self.editable and self.image is not None and self.scene:
            steps=event.angleDelta().y()/120 if event.angleDelta().y() else event.pixelDelta().y()/40
            if steps:self.scaleRequested.emit(steps,bool(event.modifiers()&Qt.KeyboardModifier.ShiftModifier));event.accept();return
        super().wheelEvent(event)
    def drawing_rects(self):
        sw,sh=(self.scene or {}).get('canvas') or self.meta.get('size') or [self.image.width(),self.image.height()]
        bounds=QRectF(0,0,sw,sh)
        for _,box in reference_rects(self.scene,self.panel_mode):bounds=bounds.united(box)
        factor=self.gesture_factor or (self.actual_scale if self.view_mode=='桌宠实际尺寸' else min((self.width()-24)/bounds.width(),(self.height()-32)/bounds.height()))
        if self.gesture_anchor_screen is not None:
            anchor=self.scene.get('anchor',[sw/2,sh/2]);x=self.gesture_anchor_screen.x()-anchor[0]*factor;y=self.gesture_anchor_screen.y()-anchor[1]*factor
        else:x=(self.width()-bounds.width()*factor)/2-bounds.x()*factor;y=(self.height()-bounds.height()*factor)/2-bounds.y()*factor
        canvas=QRectF(x,y,sw*factor,sh*factor)
        x,y,w,h=(self.scene or {}).get('image_rect',[0,0,sw,sh])
        return canvas,QRectF(canvas.x()+x*factor,canvas.y()+y*factor,w*factor,h*factor),factor
    def paint_desktop_reference(self,painter,canvas,factor):
        reference=(self.scene or {}).get('desktop_reference') or {}
        for item,box in reference_rects(self.scene,self.panel_mode):
            target=QRectF(canvas.x()+box.x()*factor,canvas.y()+box.y()*factor,box.width()*factor,box.height()*factor)
            if item['key']=='panel':
                color=QColor('#597bb4');painter.setPen(QPen(color,1,Qt.PenStyle.DashLine));painter.setBrush(QColor(103,145,199,24));painter.drawRoundedRect(target,7,7)
            else:
                color=QColor('#634d74');painter.setPen(QPen(color,1,Qt.PenStyle.DashLine));painter.setBrush(QColor(62,42,76,18));painter.drawRoundedRect(target,target.height()/2,target.height()/2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    def advance(self):
        if not self.decoder or (not self.playing and self.image is not None):return
        now=time.perf_counter()
        if self.due and now<self.due:return
        try:index,image,delay=self.decoder.queue.get_nowait()
        except queue.Empty:return
        if index=='error':self.message='无法播放这段素材';self.errorOccurred.emit(self.decoder.error or self.message);self.decoder.close();self.decoder=None;self.set_playing(False);self.timer.stop();self.update();return
        if index=='end':
            if self.loop and self.playing:
                last=self.image;self.load(self.path,True,0,self.meta);self.image=last;self.message=''
            else:self.ended=True;self.set_playing(False)
            return
        self.meta=self.decoder.meta or self.meta;self.image=image;self.index=index
        self.message='';self.due=now+delay/self.speed;self.update();self.frameChanged.emit(index,self.meta)
        if not self.playing:self.timer.stop()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect=self.rect();colors={'白色':QColor('#ffffff'),'深色':QColor('#202633'),'纯绿色':QColor('#00ff00')}
        if self.background=='透明棋盘':
            tile=QPixmap(32,32);tile.fill(QColor('#edf0f5'));p=QPainter(tile);p.fillRect(0,0,16,16,QColor('#dfe4ed'));p.fillRect(16,16,16,16,QColor('#dfe4ed'));p.end();painter.fillRect(rect,QBrush(tile))
        else:painter.fillRect(rect,colors.get(self.background,QColor('#edf0f5')))
        if self.image is not None:
            canvas,target,factor=self.drawing_rects();painter.save();painter.setClipRect(canvas)
            reference_rect=None
            if self.scene and self.scene.get('reference_rect'):
                x,y,w,h=self.scene['reference_rect'];reference_rect=QRectF(canvas.x()+x*factor,canvas.y()+y*factor,w*factor,h*factor)
                if self.ghost and not self.reference.isNull():
                    painter.setOpacity(.22);painter.drawImage(reference_rect,self.reference);painter.setOpacity(1.)
            painter.drawImage(target,self.image);painter.restore()
            if self.guides:
                if reference_rect is not None:
                    painter.setPen(QPen(QColor('#278bc0'),1,Qt.PenStyle.DashLine));painter.drawRect(reference_rect)
                    if self.reference_box:
                        l,t,r,b=self.reference_box
                        painter.drawRect(QRectF(reference_rect.x()+l/720*reference_rect.width(),reference_rect.y()+t/720*reference_rect.height(),(r-l)/720*reference_rect.width(),(b-t)/720*reference_rect.height()))
                if self.scene and self.scene.get('anchor'):
                    ax,ay=self.scene['anchor'];y=canvas.y()+ay*factor
                    painter.setPen(QPen(QColor('#d58b23'),1,Qt.PenStyle.DashLine));painter.drawLine(QPointF(canvas.left(),y),QPointF(canvas.right(),y))
            self.paint_desktop_reference(painter,canvas,factor)
        else:
            painter.setPen(QColor('#7c8598'));painter.drawText(rect.adjusted(16,16,-16,-16),Qt.AlignmentFlag.AlignCenter,self.message)
    def close_player(self):
        self.finish_drag(False)
        self.timer.stop()
        if self.decoder:self.decoder.close()
