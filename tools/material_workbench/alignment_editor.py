"""Interactive per-action alignment with the exact export placement math."""
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,
    QPushButton,QDoubleSpinBox,QDialogButtonBox,QFormLayout,QStyle)
from preview_player import PreviewCanvas,GUIDE_LEGEND
from alignment import adjusted_record,manual_values,placement_rect
from desktop_reference import display_factor,load_desktop_reference,MODES
from motion_stabilization import transform_at
from modern_controls import ModernComboBox as QComboBox

def scene_for(record,actions,frame_index=0):
    from updater import geometry
    side,pad,anchor=geometry(actions)
    return dict(canvas=[side,side],anchor=anchor,reference_rect=[pad,pad,720,720],image_rect=placement_rect(transform_at(record,frame_index),anchor))

class AlignmentDialog(QDialog):
    def __init__(self,row,config,parent=None):
        super().__init__(parent);self.row=row;self.config=config;self.record=row['record'];self.factor=display_factor(config)
        self.setWindowTitle('调整当前动作 · '+row['name']);self.resize(770,740);self.setMinimumSize(640,610)
        layout=QVBoxLayout(self);layout.setSpacing(9)
        hint=QLabel('左键拖动人物改位置，滚轮调大小；Shift+滚轮细调。也可用下方数字微调。');hint.setWordWrap(True);layout.addWidget(hint)
        toolbar=QHBoxLayout();self.view=QComboBox();self.view.addItems(['适合窗口','桌宠实际尺寸']);toolbar.addWidget(self.view)
        self.guides=QCheckBox('参考框 / 脚底线');self.guides.setChecked(True);toolbar.addWidget(self.guides)
        self.ghost=QCheckBox('原白龙淡影');self.ghost.setChecked(True);toolbar.addWidget(self.ghost)
        self.pause=QPushButton('暂停');toolbar.addWidget(self.pause);toolbar.addStretch();layout.addLayout(toolbar)
        self.panel_mode=QComboBox();self.panel_mode.addItems(MODES);self.panel_mode.setFixedWidth(126);toolbar.insertWidget(3,self.panel_mode)
        self.refresh_layout=QPushButton();self.refresh_layout.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload));self.refresh_layout.setFixedWidth(32);self.refresh_layout.setToolTip('重新读取桌宠当前倍率、状态栏和胶囊布局');toolbar.insertWidget(4,self.refresh_layout)
        self.desktop_reference=load_desktop_reference(config)
        self.canvas=PreviewCanvas();self.canvas.actual_scale=self.factor;self.canvas.ghost=True;layout.addWidget(self.canvas,1)
        self.canvas.frameChanged.connect(self.motion_frame)
        self.canvas.set_editable(True);self.canvas.dragStarted.connect(self.begin_drag);self.canvas.dragDelta.connect(self.drag_position);self.canvas.scaleRequested.connect(self.wheel_scale)
        self.view.currentTextChanged.connect(self.canvas.set_view_mode)
        self.guides.toggled.connect(lambda v:self.flag('guides',v));self.ghost.toggled.connect(lambda v:self.flag('ghost',v))
        self.pause.clicked.connect(self.canvas.toggle);self.canvas.playingChanged.connect(lambda v:self.pause.setText('暂停' if v else '播放'))
        self.canvas.errorOccurred.connect(self.preview_error)
        self.panel_mode.currentTextChanged.connect(self.canvas.set_panel_mode);self.refresh_layout.clicked.connect(self.reload_reference)
        legend=QLabel(GUIDE_LEGEND+'<br>面板与胶囊是两种模式的叠加参照；“适合窗口”可同时看全。实际尺寸超出预览区时请切回适合窗口。')
        legend.setWordWrap(True);legend.setObjectName('muted');layout.addWidget(legend)
        self.layout_note=QLabel(self.desktop_reference['description']);self.layout_note.setWordWrap(True);self.layout_note.setObjectName('muted');layout.addWidget(self.layout_note)
        form=QFormLayout();self.scale=QDoubleSpinBox();self.scale.setRange(25,250);self.scale.setDecimals(1);self.scale.setSingleStep(1);self.scale.setSuffix(' %')
        self.x=QDoubleSpinBox();self.y=QDoubleSpinBox()
        for spin in (self.x,self.y):spin.setRange(-2048*self.factor,2048*self.factor);spin.setDecimals(1);spin.setSingleStep(1);spin.setSuffix(' px')
        manual=manual_values(config.get('adjustments',{}).get(row['file']));self.scale.setValue(manual['scale']*100);self.x.setValue(manual['offset'][0]*self.factor);self.y.setValue(manual['offset'][1]*self.factor)
        form.addRow('人物大小（100% = 自动结果）',self.scale);form.addRow('左右位置（正值向画面右侧）',self.x);form.addRow('上下位置（正值向下）',self.y);layout.addLayout(form)
        note=QLabel('拖动时自动暂停，松手恢复原播放状态。位置为当前桌宠倍率下的逻辑像素；缩放围绕脚底锚点，道具一起调整，整段参数固定。');note.setWordWrap(True);note.setObjectName('muted');layout.addWidget(note)
        self.stabilize=QCheckBox('修正缓慢放大 / 下沉（重新生成后生效）')
        self.stabilize.setChecked(bool(config.get('stabilize_actions',{}).get(row['file'],bool(self.record.get('stabilization')))))
        self.stabilize.setToolTip('适合生成视频里的镜头和脚底漂移；保留肢体姿态与时长，不修改原片。识别不可靠会停止，不猜测。')
        layout.addWidget(self.stabilize)
        self.automatic=QCheckBox('参与随机动作');self.automatic.setChecked(bool(config.get('automatic_actions',{}).get(row['file'],True)));layout.addWidget(self.automatic)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        buttons=QHBoxLayout();self.reset=QPushButton('恢复自动结果');self.reset.clicked.connect(self.reset_values);buttons.addWidget(self.reset);buttons.addStretch()
        cancel=QPushButton('取消');cancel.clicked.connect(self.reject);buttons.addWidget(cancel)
        self.save=QPushButton('保存并重新生成');self.save.setObjectName('primary');self.save.clicked.connect(self.accept);buttons.addWidget(self.save);layout.addLayout(buttons)
        for spin in (self.scale,self.x,self.y):spin.valueChanged.connect(self.update_scene)
        self.result_adjustment=manual;self.valid=True;self.preview_failed=False;self.update_scene()
        self.canvas.load(self.record['cache'],True,known_meta=row.get('meta'))
        if parent:
            screen=parent.screen().availableGeometry();self.resize(min(770,screen.width()-50),min(740,screen.height()-70))
    def flag(self,name,value):setattr(self.canvas,name,value);self.canvas.update()
    def reload_reference(self):
        x,y=self.x.value()/self.factor,self.y.value()/self.factor;self.desktop_reference=load_desktop_reference(self.config);self.factor=self.desktop_reference['factor'];self.canvas.actual_scale=self.factor
        for spin,value in ((self.x,x*self.factor),(self.y,y*self.factor)):
            spin.blockSignals(True);spin.setRange(-2048*self.factor,2048*self.factor);spin.setValue(value);spin.blockSignals(False)
        self.layout_note.setText(self.desktop_reference['description']);self.update_scene()
    def values(self):return manual_values(dict(scale=self.scale.value()/100,offset=[self.x.value()/self.factor,self.y.value()/self.factor]))
    def begin_drag(self):self.drag_start_position=(self.x.value(),self.y.value())
    def drag_position(self,dx,dy):
        origin=getattr(self,'drag_start_position',(self.x.value(),self.y.value()))
        for spin,value in ((self.x,origin[0]+dx*self.factor),(self.y,origin[1]+dy*self.factor)):
            spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
        self.update_scene()
    def wheel_scale(self,steps,fine=False):
        self.scale.setValue(max(self.scale.minimum(),min(self.scale.maximum(),self.scale.value()*(1.002 if fine else 1.02)**steps)))
    def reset_values(self):
        for spin,value in ((self.scale,100),(self.x,0),(self.y,0)):
            spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
        self.update_scene()
    def update_scene(self):
        try:
            self.result_adjustment=self.values();record=adjusted_record(self.record,self.result_adjustment)
            actions=dict(self.row.get('all_records',{}));actions[self.row.get('processed_action',self.row['action'])]=record
            scene=scene_for(record,actions,self.canvas.index);scene['desktop_reference']=self.desktop_reference;self.canvas.set_scene(scene);self.valid=True
            self.status.setText(f"输出画布 {scene['canvas'][0]} × {scene['canvas'][1]}；位置与缩放实时预览，保存后才会重新生成。")
        except (ValueError,KeyError) as error:self.valid=False;self.status.setText(str(error))
        self.save.setEnabled(self.valid and not self.preview_failed)
    def preview_error(self,error):self.preview_failed=True;self.status.setText('预览失败：'+error);self.save.setEnabled(False)
    def motion_frame(self,index,*args):
        if self.record.get('stabilization') and self.canvas.scene:
            record=adjusted_record(self.record,self.result_adjustment);scene=dict(self.canvas.scene)
            scene['image_rect']=placement_rect(transform_at(record,index),scene['anchor']);self.canvas.set_scene(scene)
    def accept(self):
        self.result_stabilize=self.stabilize.isChecked()
        self.result_automatic=self.automatic.isChecked()
        if self.valid and not self.preview_failed:super().accept()
    def done(self,result):self.canvas.close_player();super().done(result)
