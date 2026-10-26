"""Short body-only crossfade; headers and the native window never disappear."""
from PySide6.QtCore import Qt,QVariantAnimation,QEasingCurve,QPoint,QRect
from PySide6.QtGui import QPainter,QPixmap,QColor,QRegion
from PySide6.QtWidgets import QWidget
from ui_theme import SURFACE

class PageFade(QWidget):
    @staticmethod
    def snapshot(widget):
        ratio=widget.devicePixelRatioF()
        image=QPixmap(round(widget.width()*ratio),round(widget.height()*ratio));image.setDevicePixelRatio(ratio)
        # A transparent scroll viewport has no standalone backing background.
        # Seed the actual card colour, otherwise Windows can capture black.
        image.fill(QColor(SURFACE));widget.render(image,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        return image
    @staticmethod
    def snapshot_region(widget,rect):
        """Capture a parent region including overlays and the live child below."""
        rect=QRect(rect);ratio=widget.devicePixelRatioF()
        image=QPixmap(round(rect.width()*ratio),round(rect.height()*ratio));image.setDevicePixelRatio(ratio)
        image.fill(QColor(SURFACE))
        widget.render(image,QPoint(-rect.x(),-rect.y()),QRegion(rect),QWidget.RenderFlag.DrawChildren)
        return image
    def __init__(self,parent):
        super().__init__(parent);self.frame=None;self.next_frame=None;self.progress=0.;self.fade_out=False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);self.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(160)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.advance);self.animation.finished.connect(self.clear)
    def present(self,frame,next_frame,rect,fade_out=False):
        self.animation.stop();self.frame=frame;self.next_frame=next_frame;self.progress=0.;self.fade_out=bool(fade_out);self.setGeometry(rect)
        self.show();self.raise_();self.animation.start()
    def current_frame(self):
        """Return the pixels currently on screen when a second switch interrupts us."""
        if self.frame is None:return None
        if self.next_frame is None or not self.isVisible():return self.frame
        ratio=self.devicePixelRatioF()
        image=QPixmap(round(self.width()*ratio),round(self.height()*ratio));image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        p.setOpacity(self.progress);p.drawPixmap(self.rect(),self.next_frame,self.next_frame.rect());p.end()
        return image
    def advance(self,value):self.progress=float(value);self.update()
    def clear(self):
        self.animation.stop();self.hide();self.frame=None;self.next_frame=None;self.progress=0.;self.fade_out=False
    def paintEvent(self,event):
        if self.frame is None:return
        p=QPainter(self)
        if self.fade_out:
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        elif self.next_frame is None:p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        else:
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
            p.setOpacity(self.progress);p.drawPixmap(self.rect(),self.next_frame,self.next_frame.rect())
