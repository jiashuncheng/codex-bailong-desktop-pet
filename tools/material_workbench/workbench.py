"""Cross-platform Qt material library, alpha preview, preparation and activation."""
from pathlib import Path
import json,os,sys,uuid,shutil,time
from PySide6.QtCore import Qt,QTimer,QProcess,QProcessEnvironment,QUrl,QSize
from PySide6.QtGui import QFont,QColor,QDesktopServices,QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QVBoxLayout,QHBoxLayout,
    QLabel,QLineEdit,QPushButton,QCheckBox,QComboBox,QSplitter,QTableWidget,QTableWidgetItem,
    QHeaderView,QAbstractItemView,QFileDialog,QMessageBox,QSlider,QTabBar,QProgressBar,
    QPlainTextEdit,QDoubleSpinBox,QDialog,QDialogButtonBox,QFormLayout,QInputDialog,QStyle)
from config_store import load_config,save_config
from library_scan import ScanWorker,read_json
from preview_player import PreviewCanvas,GUIDE_LEGEND
from alignment_editor import AlignmentDialog,display_factor
from desktop_reference import load_desktop_reference,MODES

BASE=Path(__file__).resolve().parent
STYLE='''
QWidget { color:#253248; font-size:13px; }
QMainWindow, QWidget#root { background:#f3f5fa; }
QFrame#card { background:white; border:1px solid #e0e5ee; border-radius:12px; }
QLabel#title { font-size:24px; font-weight:650; color:#18263d; }
QLabel#section { font-size:15px; font-weight:600; }
QLabel#muted { color:#748095; }
QLabel#chip { background:#eaeef8; color:#556280; padding:5px 10px; border-radius:11px; }
QPushButton { background:white; border:1px solid #d9dfeb; border-radius:7px; padding:8px 12px; }
QPushButton:hover { background:#eef2fa; border-color:#b5c1d8; }
QPushButton:disabled { color:#a3acbc; background:#f2f4f8; border-color:#e6eaf1; }
QPushButton#primary { color:white; background:#6455cb; border-color:#6455cb; font-weight:600; }
QPushButton#primary:hover { background:#5545ba; }
QPushButton#primary:disabled { background:#d7d4ed; border-color:#d7d4ed; color:#f9f8ff; }
QPushButton#apply { background:#e7f5ef; color:#13775d; border-color:#b7dece; font-weight:600; }
QPushButton#apply:disabled { color:#a2b4ac; background:#f0f5f2; border-color:#e1e9e4; }
QLineEdit,QComboBox,QDoubleSpinBox { background:white; border:1px solid #d9dfeb; border-radius:6px; padding:7px; selection-background-color:#dcd6ff; }
QTableWidget { border:0; background:white; alternate-background-color:#f8faff; gridline-color:#eef1f6; selection-background-color:#eeeafd; selection-color:#253248; }
QHeaderView::section { color:#7b8698; background:#f8f9fc; border:0; border-bottom:1px solid #e7ebf3; padding:8px; }
QTabBar::tab { background:transparent; color:#7b8698; padding:9px 20px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#6455cb; border-bottom-color:#6455cb; font-weight:600; }
QTabBar::tab:disabled { color:#c0c6d0; }
QProgressBar { border:0; background:#e7eaf3; border-radius:3px; height:6px; }
QProgressBar::chunk { background:#7e6dd8; border-radius:3px; }
QSlider::groove:horizontal { background:#e3e7f0; height:4px; border-radius:2px; }
QSlider::handle:horizontal { background:#7663d0; width:12px; margin:-5px 0; border-radius:6px; }
QPlainTextEdit { background:#f8f9fd; border:1px solid #e3e7ef; border-radius:7px; font-family:monospace; font-size:11px; }
QSplitter::handle { background:transparent; width:12px; }
'''

def label(text='',name=None):
    result=QLabel(text)
    if name:result.setObjectName(name)
    return result

def nice_name(value):
    import re
    return re.sub(r'[_ -]*(透明|有损|无损|预览|母版|\d+x\d+|\d+fps).*','',value).replace('_保留白色雪花',' · 保留雪花')

class MaterialWorkbench(QMainWindow):
    def __init__(self,config_path=None):
        super().__init__();self.config_path=Path(config_path or BASE/'配置.json');self.config=load_config(self.config_path)
        self.setWindowTitle('白龙素材工作台');self.resize(1180,780);self.setMinimumSize(900,630)
        self.setStyleSheet(STYLE);self.rows=[];self.inventory={};self.scan_workers=[];self.current_row=None
        self.busy=False;self.buffer=b'';self.last_report=None;self.last_error='';self.seeking=False;self.process_mode='';self.result_notice='';self.focus_processed=False
        root=QWidget();root.setObjectName('root');self.setCentralWidget(root)
        layout=QVBoxLayout(root);layout.setContentsMargins(20,18,20,16);layout.setSpacing(12)
        header=QHBoxLayout();titleblock=QVBoxLayout();titleblock.setSpacing(3)
        titleblock.addWidget(label('白龙素材工作台','title'));titleblock.addWidget(label('选素材 → 界面内预览 → 处理 → 加入桌宠','muted'));header.addLayout(titleblock);header.addStretch()
        self.add_button=QPushButton('添加视频');self.add_button.clicked.connect(self.import_files);header.addWidget(self.add_button)
        self.refresh_button=QPushButton('刷新');self.refresh_button.clicked.connect(self.refresh);header.addWidget(self.refresh_button)
        self.settings_button=QPushButton('设置');self.settings_button.clicked.connect(self.settings_dialog);header.addWidget(self.settings_button);layout.addLayout(header)
        folderrow=QHBoxLayout();folderrow.addWidget(label('素材目录','muted'))
        self.folder=QLineEdit(self.config['input_dir']);self.folder.setReadOnly(True);folderrow.addWidget(self.folder,1)
        self.change_button=QPushButton('更换');self.change_button.clicked.connect(self.choose_folder);folderrow.addWidget(self.change_button)
        self.open_input_button=QPushButton('打开目录');self.open_input_button.clicked.connect(lambda:self.open_folder(self.config['input_dir']));folderrow.addWidget(self.open_input_button);layout.addLayout(folderrow)
        splitter=QSplitter(Qt.Orientation.Horizontal);splitter.setChildrenCollapsible(False)
        left=QFrame();left.setObjectName('card');left.setMinimumWidth(320);ll=QVBoxLayout(left);ll.setContentsMargins(12,12,12,12);ll.setSpacing(9)
        listhead=QHBoxLayout();listhead.addWidget(label('素材列表','section'));listhead.addStretch();self.count=label('正在扫描…','chip');listhead.addWidget(self.count);ll.addLayout(listhead)
        filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('搜索文件或动作名称');self.search.textChanged.connect(self.filter_rows);filters.addWidget(self.search,1)
        self.filter=QComboBox();self.filter.addItems(['全部','待处理','已处理','已加入','失败']);self.filter.currentTextChanged.connect(self.filter_rows);filters.addWidget(self.filter);ll.addLayout(filters)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['选','动作 / 文件','状态','大小']);self.table.verticalHeader().hide();self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setAlternatingRowColors(True);self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(0,34)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        for col,width in ((2,70),(3,65)):self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(col,width)
        self.table.itemSelectionChanged.connect(self.selection_changed);self.table.itemChanged.connect(self.update_actions);ll.addWidget(self.table,1)
        selection=QHBoxLayout();self.all_check=QCheckBox('全选');self.all_check.toggled.connect(self.select_all);selection.addWidget(self.all_check)
        pending=QPushButton('只选待处理');pending.clicked.connect(self.select_pending);selection.addWidget(pending);selection.addStretch()
        self.rename_button=QPushButton('改动作名');self.rename_button.clicked.connect(self.rename_action);selection.addWidget(self.rename_button);ll.addLayout(selection)
        ll.addWidget(label('点名称预览，勾选后处理；原片始终保留。','muted'));splitter.addWidget(left)
        right=QFrame();right.setObjectName('card');right.setMinimumWidth(440);rl=QVBoxLayout(right);rl.setContentsMargins(14,10,14,12);rl.setSpacing(8)
        previewhead=QHBoxLayout();self.preview_title=label('素材预览','section');previewhead.addWidget(self.preview_title);previewhead.addStretch()
        self.open_results_button=QPushButton('打开处理结果');self.open_results_button.clicked.connect(lambda:self.open_folder(self.config['output_dir']));previewhead.addWidget(self.open_results_button);rl.addLayout(previewhead)
        self.tabs=QTabBar();self.tabs.addTab('原素材');self.tabs.addTab('处理后');self.tabs.currentChanged.connect(self.load_preview);rl.addWidget(self.tabs)
        viewing=QHBoxLayout();self.view_mode=QComboBox();self.view_mode.addItems(['适合窗口','桌宠实际尺寸']);viewing.addWidget(self.view_mode)
        self.guides=QCheckBox('参考框');self.guides.setChecked(True);viewing.addWidget(self.guides)
        self.ghost=QCheckBox('白龙淡影');viewing.addWidget(self.ghost);viewing.addStretch()
        self.adjust_button=QPushButton('调大小 / 位置');self.adjust_button.clicked.connect(self.adjust_alignment);viewing.addWidget(self.adjust_button);rl.addLayout(viewing)
        self.edit_button=QPushButton('裁剪 / 拼接');self.edit_button.clicked.connect(self.edit_clips);viewing.insertWidget(viewing.count()-1,self.edit_button)
        self.canvas=PreviewCanvas();self.canvas.frameChanged.connect(self.frame_changed);self.canvas.errorOccurred.connect(self.preview_error);self.canvas.playingChanged.connect(self.playing_changed);rl.addWidget(self.canvas,1)
        self.view_mode.currentTextChanged.connect(self.canvas.set_view_mode)
        self.guides.toggled.connect(lambda v:self.preview_flag('guides',v));self.ghost.toggled.connect(lambda v:self.preview_flag('ghost',v))
        self.preview_note=label('适合窗口会缩放显示；处理后可对照原白龙大小和脚底线。','muted');self.preview_note.setWordWrap(True);rl.addWidget(self.preview_note)
        self.meta=label('支持 MP4、透明 WebM 和动画 WebP。','muted');rl.addWidget(self.meta)
        controls=QHBoxLayout();self.play_button=QPushButton();self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause));self.play_button.setFixedWidth(42);self.play_button.clicked.connect(self.canvas.toggle);controls.addWidget(self.play_button)
        self.position=QSlider(Qt.Orientation.Horizontal);self.position.setRange(0,1);self.position.sliderPressed.connect(self.begin_seek);self.position.sliderReleased.connect(self.end_seek);controls.addWidget(self.position,1)
        self.time_label=label('00:00 / 00:00','muted');controls.addWidget(self.time_label);rl.addLayout(controls)
        options=QHBoxLayout();options.addWidget(label('背景','muted'));self.background=QComboBox();self.background.addItems(['透明棋盘','白色','深色','纯绿色']);self.background.currentTextChanged.connect(self.canvas.set_background);options.addWidget(self.background)
        options.addSpacing(10);options.addWidget(label('速度','muted'));self.speed=QComboBox();self.speed.addItems(['0.5×','1×','1.5×','2×']);self.speed.setCurrentText('1×');self.speed.currentTextChanged.connect(lambda t:self.canvas.set_speed(float(t.rstrip('×'))));options.addWidget(self.speed)
        self.loop=QCheckBox('循环');self.loop.setChecked(True);self.loop.toggled.connect(lambda v:setattr(self.canvas,'loop',v));options.addWidget(self.loop);options.addStretch();rl.addLayout(options)
        self.panel_reference=QComboBox();self.panel_reference.addItems(MODES);self.panel_reference.setFixedWidth(126);self.panel_reference.setToolTip('上方状态栏、胶囊的布局参照；两种模式可叠加对照，不写入素材。');self.panel_reference.currentTextChanged.connect(self.canvas.set_panel_mode);options.insertWidget(options.count()-1,self.panel_reference)
        splitter.addWidget(right);splitter.setSizes([400,740]);layout.addWidget(splitter,1)
        self.status=label('正在读取本地素材…');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setMaximumHeight(6);layout.addWidget(self.progress)
        bottom=QHBoxLayout();self.auto_apply=QCheckBox('处理完成后自动加入桌宠');self.auto_apply.setChecked(bool(self.config.get('auto_apply',False)));bottom.addWidget(self.auto_apply)
        self.log_button=QPushButton('详细记录');self.log_button.setCheckable(True);self.log_button.toggled.connect(self.toggle_logs);bottom.addWidget(self.log_button);bottom.addStretch()
        self.process_all_button=QPushButton('处理全部');self.process_all_button.clicked.connect(lambda:self.start_processing(all_files=True));bottom.addWidget(self.process_all_button)
        self.process_button=QPushButton('处理选中');self.process_button.setObjectName('primary');self.process_button.clicked.connect(lambda:self.start_processing());bottom.addWidget(self.process_button)
        self.apply_button=QPushButton('加入桌宠');self.apply_button.setObjectName('apply');self.apply_button.clicked.connect(self.activate);bottom.addWidget(self.apply_button);layout.addLayout(bottom)
        self.logs=QPlainTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumBlockCount(1800);self.logs.setMaximumHeight(130);self.logs.hide();layout.addWidget(self.logs)
        self.process=QProcess(self);self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output);self.process.finished.connect(self.process_finished);self.process.errorOccurred.connect(self.process_error)
        self.update_actions();QTimer.singleShot(0,self.refresh)

    def append(self,text):self.logs.appendPlainText(str(text))
    def open_folder(self,value):
        path=Path(value)
        if not path.is_dir():self.status.setText('目录还不存在，处理成功后会生成。');return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'选择素材目录',self.config['input_dir'])
        if path:self.config['input_dir']=path;self.folder.setText(path);save_config(self.config_path,self.config);self.refresh()
    def import_files(self):
        files,_=QFileDialog.getOpenFileNames(self,'添加视频素材',self.config['input_dir'],'视频素材 (*.webm *.webp *.mp4 *.mov *.mkv)')
        if not files:return
        root=Path(self.config['input_dir']);dest=root/'导出结果' if (root/'导出结果').is_dir() else root
        dest.mkdir(parents=True,exist_ok=True);copied=0
        for file in files:
            source=Path(file);target=dest/source.name
            if source.resolve()==target.resolve():continue
            index=2
            while target.exists():target=dest/(source.stem+f'_{index}'+source.suffix);index+=1
            try:shutil.copy2(source,target);copied+=1
            except OSError as error:self.append(f'添加失败：{source.name}：{error}')
        self.status.setText(f'已复制 {copied} 个视频；原文件保留。');self.refresh()
    def refresh(self):
        if self.busy:return
        for worker in self.scan_workers:
            if worker.isRunning():worker.requestInterruption()
        worker=ScanWorker(self.config,self);self.scan_workers.append(worker)
        worker.result.connect(lambda rows,info,w=worker:self.populate(rows,info) if not w.isInterruptionRequested() else None)
        worker.failed.connect(lambda error:self.status.setText('读取失败：'+error))
        worker.finished.connect(lambda w=worker:self.scan_done(w));worker.start();self.status.setText('正在核对文件与处理状态…')
    def scan_done(self,worker):
        if worker in self.scan_workers:self.scan_workers.remove(worker)
        worker.deleteLater()
    def populate(self,rows,info):
        previous=self.current_row['path'] if self.current_row else None;self.rows=rows;self.inventory=info;self.table.blockSignals(True);self.table.setRowCount(len(rows))
        colors={'已加入':'#13856c','已处理':'#6358bf','待处理':'#4c6aa9','有更新':'#aa721b','待重生成':'#aa721b','失败':'#b24b54'}
        selected=0
        for i,row in enumerate(rows):
            check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);check.setCheckState(Qt.CheckState.Checked if row['status'] in ('待处理','有更新','待重生成','失败') else Qt.CheckState.Unchecked);self.table.setItem(i,0,check)
            item=QTableWidgetItem(nice_name(row['name']));item.setToolTip(row['path']);self.table.setItem(i,1,item)
            status=QTableWidgetItem(row['status']);status.setForeground(QColor(colors.get(row['status'],'#667085')));status.setToolTip(row.get('error',''));self.table.setItem(i,2,status)
            self.table.setItem(i,3,QTableWidgetItem(f"{row['bytes']/1024/1024:.1f} MB"));self.table.setRowHeight(i,44)
            if row['path']==previous:selected=i
        self.table.blockSignals(False);self.count.setText(f'{len(rows)} 段素材');self.filter_rows()
        if rows:self.table.selectRow(selected);self.selection_changed()
        else:self.current_row=None;self.canvas.clear('没有素材，点击“添加视频”或更换目录。')
        pending=sum(r['status'] in ('待处理','有更新','待重生成','失败') for r in rows)
        self.status.setText(self.result_notice or f'{len(rows)} 段素材 · {pending} 段待处理。'+('已有处理结果待加入桌宠。' if info.get('pending') else '点击名称预览，勾选后处理。'))
        if self.focus_processed and self.current_row and self.current_row['processed']:
            self.tabs.setCurrentIndex(1);self.load_preview();self.focus_processed=False
        self.update_actions()
    def filter_rows(self):
        text=self.search.text().strip().lower();kind=self.filter.currentText()
        for i,row in enumerate(self.rows):
            visible=(not text or text in (row['name']+' '+row['file']).lower()) and (kind=='全部' or row['status']==kind or kind=='待处理' and row['status'] in ('有更新','待重生成'))
            self.table.setRowHidden(i,not visible)
        self.update_actions()
    def checked_paths(self):return [r['path'] for i,r in enumerate(self.rows) if not self.table.isRowHidden(i) and self.table.item(i,0).checkState()==Qt.CheckState.Checked]
    def select_all(self,value):
        self.table.blockSignals(True)
        for i in range(len(self.rows)):
            if not self.table.isRowHidden(i):self.table.item(i,0).setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        self.table.blockSignals(False);self.update_actions()
    def select_pending(self):
        self.table.blockSignals(True)
        for i,row in enumerate(self.rows):self.table.item(i,0).setCheckState(Qt.CheckState.Checked if row['status'] in ('待处理','有更新','待重生成','失败') else Qt.CheckState.Unchecked)
        self.table.blockSignals(False);self.update_actions()
    def update_actions(self,*args):
        count=len(self.checked_paths()) if self.rows else 0;self.process_button.setText(f'处理选中（{count}）')
        self.process_button.setEnabled(bool(count) and not self.busy);self.process_all_button.setEnabled(bool(self.rows) and not self.busy)
        ready=bool(self.inventory.get('ready'));pending=bool(self.inventory.get('pending'))
        self.apply_button.setText('先重新生成' if self.inventory.get('unprepared_adjustments') else '已加入桌宠' if ready and not pending else '加入桌宠')
        self.apply_button.setEnabled(ready and pending and not self.busy and not self.inventory.get('unprepared_adjustments'))
        self.adjust_button.setEnabled(not self.busy and bool(self.current_row and self.current_row.get('record') and Path(self.current_row['record'].get('cache','')).is_file()))
        self.edit_button.setEnabled(not self.busy and bool(self.current_row))
        for widget in (self.add_button,self.change_button,self.refresh_button,self.settings_button,self.rename_button,self.auto_apply):widget.setEnabled(not self.busy)
    def selection_changed(self):
        index=self.table.currentRow()
        if not 0<=index<len(self.rows):return
        self.current_row=self.rows[index];self.preview_title.setText(nice_name(self.current_row['name']))
        self.tabs.setTabEnabled(1,bool(self.current_row['processed']));self.load_preview()
        self.update_actions()
        if self.current_row.get('error'):self.status.setText('这条素材未通过：'+self.current_row['error'])
    def load_preview(self,*args):
        row=self.current_row
        if not row:return
        processed=self.tabs.currentIndex()==1;path=row['processed'] if processed else row['path']
        if not path:self.canvas.clear('还没有处理结果，请先处理这条素材。');return
        self.view_mode.setEnabled(processed);self.ghost.setEnabled(processed);self.panel_reference.setEnabled(processed)
        if not processed:self.view_mode.setCurrentText('适合窗口')
        self.preview_note.setText(GUIDE_LEGEND+'<br>面板＋胶囊为两种模式叠加，适合窗口可看全。' if processed else '原素材按画布缩放显示；桌宠大小、脚底与上方面板参照请切到“处理后”。')
        meta=dict(row.get('meta') or {})
        if processed and meta:meta['size']=None
        self.canvas.actual_scale=display_factor(self.config)
        layout=self.inventory.get('layout') if processed else None
        if layout:
            sw,sh=layout['canvas'];self.canvas.set_scene(dict(canvas=[sw,sh],image_rect=[0,0,sw,sh],reference_rect=[(sw-720)/2,(sh-720)/2,720,720],anchor=layout['anchor'],desktop_reference=load_desktop_reference(self.config)))
        else:self.canvas.set_scene(None)
        self.canvas.load(path,True,known_meta=meta);self.play_button.setEnabled(True)
        if processed and not row.get('processed_current'):self.status.setText('这里是旧处理结果；源文件或手动参数已更新，需要重新生成。')
    def preview_flag(self,name,value):setattr(self.canvas,name,value);self.canvas.update()
    def edit_clips(self):
        from clip_editor import ClipEditor
        if self.busy or not self.current_row:return
        row=self.current_row;processed=self.tabs.currentIndex()==1
        paths=[row['processed']] if processed and row.get('processed') else [row['path']]
        playing=self.canvas.playing;self.canvas.set_playing(False)
        profiles={}
        if processed and self.inventory.get('layout'):
            from processed_profile import from_layout
            profiles={paths[0]:from_layout(self.inventory['layout'],baked=bool((row.get('record') or {}).get('stabilization')))}
        dialog=ClipEditor(paths,self.config,self,profiles=profiles)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.saved_path:
            self.current_row={'path':dialog.saved_path};self.refresh()
        else:self.canvas.set_playing(playing)
    def adjust_alignment(self):
        row=self.current_row
        if self.busy or not row or not row.get('record'):return
        self.canvas.set_playing(False);dialog=AlignmentDialog(row,self.config,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.config.setdefault('stabilize_actions',{})[row['file']]=dialog.result_stabilize
            self.config.setdefault('automatic_actions',{})[row['file']]=dialog.result_automatic
            self.config.setdefault('adjustments',{})[row['file']]=dialog.result_adjustment;save_config(self.config_path,self.config)
            self.start_processing(selected_files=[row['path']],preview_only=True)
    def playing_changed(self,value):self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause if value else QStyle.StandardPixmap.SP_MediaPlay))
    def frame_changed(self,index,meta):
        count=max(1,int(meta.get('frames',1)));fps=max(.01,float(meta.get('fps',24)));duration=float(meta.get('duration',0))
        if not self.seeking:self.position.setRange(0,count-1);self.position.setValue(min(index,count-1))
        def stamp(t):return f'{int(t)//60:02d}:{int(t)%60:02d}'
        self.time_label.setText(f'{stamp(index/fps)} / {stamp(duration)}')
        w,h=meta.get('size') or (0,0);self.meta.setText(f"{w} × {h}  ·  {fps:.1f} fps  ·  {duration:.2f} 秒  ·  {'透明素材' if meta.get('alpha') else '原视频'}")
    def begin_seek(self):self.seeking=True
    def end_seek(self):self.seeking=False;self.canvas.seek(self.position.value())
    def preview_error(self,error):self.status.setText('预览失败：'+error);self.append(error)
    def rename_action(self):
        if not self.current_row:return
        name,ok=QInputDialog.getText(self,'动作名称','在桌宠菜单中显示的名称：',text=nice_name(self.current_row['name']))
        if ok and name.strip():
            self.config.setdefault('action_names',{})[self.current_row['file']]=name.strip();save_config(self.config_path,self.config)
            self.status.setText('名称已保存；处理这条素材并加入桌宠后生效。');self.refresh()
    def settings_dialog(self):
        dialog=QDialog(self);dialog.setWindowTitle('工作台设置');dialog.resize(610,240);form=QFormLayout(dialog)
        scale=QDoubleSpinBox();scale.setRange(.5,1.5);scale.setSingleStep(.05);scale.setDecimals(2);scale.setValue(float(self.config.get('extra_scale',1)));form.addRow('新增人物倍率（1.00 匹配现有白龙）',scale)
        source=QLineEdit(self.config.get('app_root',''));source_row=QWidget();row=QHBoxLayout(source_row);row.setContentsMargins(0,0,0,0);row.addWidget(source,1)
        browse=QPushButton('选择');browse.clicked.connect(lambda:source.setText(QFileDialog.getExistingDirectory(dialog,'选择白龙源码目录',source.text()) or source.text()));row.addWidget(browse);form.addRow('白龙源码目录',source_row)
        info=label('Windows / macOS 分别保存路径配置。换电脑后在这里指定源码目录。','muted');info.setWordWrap(True);form.addRow(info)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.config['extra_scale']=scale.value();self.config['app_root']=source.text().strip()
            root=Path(self.config['app_root']);exe=root/('.venv/Scripts/python.exe' if sys.platform=='win32' else '.venv/bin/python')
            if exe.is_file():self.config['python']=str(exe)
            save_config(self.config_path,self.config);self.status.setText('设置已保存。倍率变化在下次处理选中素材时生效。')
    def validate_environment(self):
        root=Path(self.config.get('app_root',''))
        if not (root/'run_source.py').is_file():self.status.setText('请先在“设置”中选择白龙桌宠源码目录。');return False
        if not Path(self.config.get('python','')).is_file():self.status.setText('找不到处理程序的 Python 环境，请检查“设置”中的源码目录。');return False
        return True
    def start_processing(self,all_files=False,selected_files=None,preview_only=False):
        if self.busy or not self.validate_environment():return
        selected=selected_files if selected_files is not None else [r['path'] for r in self.rows] if all_files else self.checked_paths()
        if not selected:self.status.setText('先勾选需要处理的素材。');return
        for index,row in enumerate(self.rows):
            if row['path'] in selected:self.table.item(index,2).setText('处理中');self.table.item(index,2).setForeground(QColor('#6455cb'))
        self.config['auto_apply']=self.auto_apply.isChecked();save_config(self.config_path,self.config)
        request=Path(self.config['state_dir'])/'ui-requests'/(uuid.uuid4().hex+'.json');request.parent.mkdir(parents=True,exist_ok=True);request.write_text(json.dumps(selected,ensure_ascii=False),encoding='utf-8')
        args=['--config',str(self.config_path),'--selection-file',str(request)]
        if preview_only or not self.auto_apply.isChecked():args.append('--prepare-only')
        self.start_process(args,'prepare')
    def activate(self):
        if self.busy or not self.validate_environment():return
        self.start_process(['--config',str(self.config_path),'--activate-only'],'apply')
    def start_process(self,args,mode):
        self.busy=True;self.process_mode=mode;self.buffer=b'';self.last_report=None;self.last_error='';self.result_notice='';self.update_actions()
        self.status.setText('正在处理选中素材…' if mode=='prepare' else '正在校验并加入桌宠…');self.progress.setRange(0,0)
        env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONUTF8','1');self.process.setProcessEnvironment(env)
        self.process.start(self.config['python'],[str(BASE/'updater.py'),*args])
    def read_output(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1);self.handle_line(line.decode('utf-8',errors='replace'))
    def handle_line(self,line):
        if not line.strip():return
        self.append(line)
        try:item=json.loads(line)
        except ValueError:return
        if not isinstance(item,dict):return
        message=item.get('message','')
        if message=='更新完成':self.last_report=item;return
        if item.get('error'):self.last_error=str(item['error'])
        if message=='新增素材编码进度' and item.get('total'):
            self.progress.setRange(0,int(item['total']));self.progress.setValue(int(item['frame']));self.status.setText(f"正在处理：{item['frame']} / {item['total']} 帧")
        elif message:self.status.setText(message+(' · '+str(item['file']) if item.get('file') else ''))
    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:self.last_error='处理程序无法启动，请检查 Python 环境。';self.process_finished(1,QProcess.ExitStatus.CrashExit)
    def process_finished(self,code,status=None):
        self.read_output()
        if self.buffer:self.handle_line(self.buffer.decode('utf-8',errors='replace'));self.buffer=b''
        self.busy=False;self.progress.setRange(0,100);self.progress.setValue(100 if self.last_report else 0)
        if self.last_report:
            report=self.last_report;failed=len(report.get('failed',[]))
            if report.get('prepared_only'):text='处理完成，可以切到“处理后”预览；满意后点击“加入桌宠”。'
            elif report.get('restarted'):text=f"桌宠已更新：{report.get('base_actions',0)} 个原动作 + {report.get('custom_actions',0)} 个自定义动作。"
            else:text='当前桌宠已经是这套素材，无需重启。'
            if failed:text+=f' {failed} 个文件未更新，原因见对应素材状态和详细记录。'
            self.result_notice=text;self.status.setText(text);self.focus_processed=bool(report.get('prepared_only'));QTimer.singleShot(10,self.refresh)
        else:self.status.setText('本次没有完成：'+(self.last_error or '请打开详细记录查看原因。'));self.log_button.setChecked(True)
        self.update_actions()
    def toggle_logs(self,value):self.logs.setVisible(value);self.log_button.setText('收起记录' if value else '详细记录')
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'还在处理','处理尚未结束，可以先最小化窗口。');event.ignore();return
        for worker in list(self.scan_workers):
            worker.requestInterruption()
            if not worker.wait(2000):self.status.setText('正在结束目录扫描，请稍后再关闭。');event.ignore();return
        self.canvas.close_player();event.accept()

def main():
    app=QApplication.instance() or QApplication(sys.argv);app.setApplicationName('白龙素材工作台');app.setStyle('Fusion')
    app.setFont(QFont('PingFang SC' if sys.platform=='darwin' else 'Microsoft YaHei UI' if sys.platform=='win32' else 'Noto Sans',10))
    window=MaterialWorkbench();screen=app.primaryScreen().availableGeometry();window.resize(min(1180,screen.width()-60),min(780,screen.height()-70));window.show();return app.exec()
if __name__=='__main__':sys.exit(main())
