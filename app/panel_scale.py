"""Scale passive status widgets with Qt's native widget/scene input mapping."""
import math
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QPainter,QTransform
from PySide6.QtWidgets import QWidget,QGraphicsView,QGraphicsScene,QFrame

def scaled_size(size,scale):
    return QSize(max(1,math.ceil(size.width()*scale)),max(1,math.ceil(size.height()*scale)))

class StatusContent(QWidget):
    def __init__(self,bubble):super().__init__(bubble);self.bubble=bubble
    # The embedded logical root is a QWidget window, not a native OS window.
    # Forward blank-area dragging and island release checks to the real shell.
    def card_pointer_press(self,event):return self.bubble.card_pointer_press(event)
    def card_pointer_move(self,event):return self.bubble.card_pointer_move(event)
    def card_pointer_release(self):return self.bubble.card_pointer_release()
    def mousePressEvent(self,event):
        if not self.card_pointer_press(event):super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if not self.card_pointer_move(event):super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if not self.card_pointer_release():super().mouseReleaseEvent(event)
    def contextMenuEvent(self,event):self.bubble.contextMenuEvent(event)

class StatusScaleHost(QGraphicsView):
    def __init__(self,bubble):
        super().__init__(bubble);self.bubble=bubble;self.proxy=None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.setStyleSheet('QGraphicsView{border:0;background:transparent;}')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.viewport().setAutoFillBackground(False)
        self.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.TextAntialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        self.setScene(QGraphicsScene(self));self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.hide()
    def sync(self,scale):
        root=self.bubble.content
        if scale==1:
            if self.proxy is not None:
                self.proxy.setWidget(None);root.setParent(self.bubble)
                self.scene().removeItem(self.proxy);self.proxy.deleteLater();self.proxy=None
            self.hide();return
        if self.proxy is None:
            root.setParent(None);root.setStyleSheet(self.bubble.styleSheet())
            self.proxy=self.scene().addWidget(root)
            # Qt enables a window background when embedding. Preserve the
            # transparent gaps around the capsule and the shell's rounded card.
            root.setAutoFillBackground(False)
            root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            root.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setSceneRect(0,0,root.width(),root.height())
        self.setTransform(QTransform().scale(scale,scale))
        size=scaled_size(root.size(),scale);self.setGeometry(0,0,size.width(),size.height())
        self.show();self.stackUnder(self.bubble.size_transition.cover)
