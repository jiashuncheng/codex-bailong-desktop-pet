"""One editor for trimming, ordering and repeating segments before saving a copy."""
from pathlib import Path
from dataclasses import replace
import uuid
from PySide6.QtCore import Qt,QThread,Signal,QSignalBlocker,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,
    QListWidgetItem,QAbstractItemView,QDoubleSpinBox,QSpinBox,QFormLayout,QSlider,
    QFileDialog,QSplitter,QWidget,QMessageBox)
from clip_editing import Clip,probe,export,publish,publish_batch,bounds
from preview_player import PreviewCanvas
from encoding_presets import PRESETS,preset
from modern_controls import ModernComboBox as QComboBox,EncodingSelector,dropdown_style
from size_estimation import estimate,identity as estimate_identity,format_estimate,remember_actual

FILTER='视频 / 动画 (*.webp *.webm *.mp4 *.mov *.mkv *.gif)'

class EstimateWorker(QThread):
    estimated=Signal(dict);failed=Signal(str)
    def __init__(self,key,clips,infos,directory,parent=None):
        super().__init__(parent);self.key=key;self.clips=clips;self.infos=infos;self.directory=directory
    def run(self):
        try:self.estimated.emit(estimate(self.clips,self.infos,directory=self.directory,cancel=self.isInterruptionRequested))
        except InterruptedError:pass
        except Exception as error:self.failed.emit(str(error))

class EditWorker(QThread):
    scanned=Signal(list,list)
    exported=Signal(dict)
    variants=Signal(list)
    saved=Signal(str)
    saved_many=Signal(list)
    failed=Signal(str)
    progress=Signal(str,int,int)
    def __init__(self,paths=None,clips=None,target=None,infos=None,copy_source=None,parent=None,encodings=None,copy_jobs=None):
        super().__init__(parent);self.paths=paths;self.clips=clips;self.target=target;self.infos=infos;self.copy_source=copy_source;self.encodings=encodings or ['lossless'];self.copy_jobs=copy_jobs
    def run(self):
        try:
            if self.copy_jobs is not None:
                self.saved_many.emit(publish_batch(self.copy_jobs,self.isInterruptionRequested))
            elif self.copy_source is not None:
                publish(self.copy_source,self.target,self.isInterruptionRequested);self.saved.emit(str(Path(self.target).resolve()))
            elif self.paths is not None:
                result=[];errors=[]
                for path in self.paths:
                    if self.isInterruptionRequested():raise InterruptedError('已取消读取')
                    try:result.append(probe(path,self.isInterruptionRequested))
                    except InterruptedError:raise
                    except Exception as error:errors.append(Path(path).name+'：'+str(error))
                self.scanned.emit(result,errors)
            else:
                results=[]
                for code in self.encodings:
                    if self.isInterruptionRequested():raise InterruptedError('已取消生成')
                    target=self.target if len(self.encodings)==1 else Path(self.target).with_name(Path(self.target).stem+'-'+code+'.webp')
                    result=export(self.clips,target,self.infos,self.isInterruptionRequested,lambda n,total,c=code:self.progress.emit(c,n,total),encoding=code)
                    results.append(result)
                self.variants.emit(results)
        except Exception as error:self.failed.emit(str(error))

class ClipEditor(QDialog):
    def __init__(self,paths,config,parent=None,profiles=None):
        super().__init__(parent);self.config=config;self.entries={};self.infos={};self.worker=None
        self.profiles={str(Path(k).resolve()):v for k,v in (profiles or {}).items()}
        self.preview_result=None;self.result_signature=None;self.result_path=None;self.saved_path=None
        self.preview_results=[];self.saved_paths=[]
        self.estimator=None;self.estimate_key=None;self.estimate_values={};self.estimate_memory={}
        self.pending_close=False;self.loading=False;self.seeking=False;self.showing_result=False;self.owned_previews=[]
        self.setWindowTitle('裁剪 / 拼接 · 保留原文件');self.resize(980,740);self.setMinimumSize(820,600)
        self.setStyleSheet(dropdown_style())
        layout=QVBoxLayout(self)
        hint=QLabel('拖动左侧片段调整顺序；拖动进度条找画面，设起止点。可复制或重复片段来延长时长。先生成预览，再保存为新素材。')
        hint.setWordWrap(True);layout.addWidget(hint)
        split=QSplitter(Qt.Orientation.Horizontal);left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,0,0)
        self.list=QListWidget();self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.list.currentItemChanged.connect(self.selected)
        self.list.model().rowsMoved.connect(self.changed);ll.addWidget(self.list,1)
        actions=QHBoxLayout();self.add_button=QPushButton('添加片段');self.add_button.clicked.connect(self.add_files);actions.addWidget(self.add_button)
        self.copy_button=QPushButton('复制');self.copy_button.clicked.connect(self.copy_current);actions.addWidget(self.copy_button)
        self.remove_button=QPushButton('移除');self.remove_button.clicked.connect(self.remove_current);actions.addWidget(self.remove_button);ll.addLayout(actions)
        fields=QFormLayout();self.start=QDoubleSpinBox();self.end=QDoubleSpinBox()
        for spin in (self.start,self.end):spin.setDecimals(3);spin.setSuffix(' 秒');spin.setSingleStep(.04);spin.setRange(0,60);spin.valueChanged.connect(self.update_segment)
        self.repeat=QSpinBox();self.repeat.setRange(1,20);self.repeat.valueChanged.connect(self.update_segment)
        fields.addRow('起点',self.start);fields.addRow('终点',self.end);fields.addRow('重复次数',self.repeat);ll.addLayout(fields)
        marks=QHBoxLayout();self.mark_start=QPushButton('当前帧设为起点');self.mark_start.clicked.connect(self.set_start_here);marks.addWidget(self.mark_start)
        self.mark_end=QPushButton('当前帧设为终点');self.mark_end.clicked.connect(self.set_end_here);marks.addWidget(self.mark_end);ll.addLayout(marks)
        self.total=QLabel('尚未添加片段');self.total.setWordWrap(True);ll.addWidget(self.total)
        self.encoding_selector=EncodingSelector(config.get('clip_encodings',['lossless']));ll.addWidget(self.encoding_selector)
        self.size_summary=QLabel('预计大小：添加片段后自动估算');self.size_summary.setWordWrap(True);ll.addWidget(self.size_summary)
        quality_note=QLabel('可多选生成对比；各档均保持分辨率、帧时序和透明度。Q95 / Q90 / Q85 只压缩颜色。');quality_note.setWordWrap(True);ll.addWidget(quality_note)
        split.addWidget(left);right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(0,0,0,0)
        heading=QHBoxLayout();self.preview_label=QLabel('原片预览 · 选段范围在左侧设置');self.preview_label.setWordWrap(True);heading.addWidget(self.preview_label,1)
        self.result_button=QPushButton('查看合成');self.result_button.clicked.connect(self.show_result);self.result_button.setEnabled(False);heading.addWidget(self.result_button);rl.addLayout(heading)
        self.version=QComboBox();self.version.setMaximumWidth(265);self.version.hide();self.version.currentIndexChanged.connect(self.select_version);heading.insertWidget(1,self.version)
        self.canvas=PreviewCanvas();self.canvas.guides=False;self.canvas.setMinimumSize(260,180);rl.addWidget(self.canvas,1)
        self.canvas.frameChanged.connect(self.frame_changed);self.canvas.errorOccurred.connect(lambda e:self.status.setText('预览失败：'+e))
        playback=QHBoxLayout();self.play_button=QPushButton('播放 / 暂停');self.play_button.clicked.connect(self.canvas.toggle);playback.addWidget(self.play_button)
        self.position=QSlider(Qt.Orientation.Horizontal);self.position.setRange(0,0);self.position.sliderPressed.connect(self.begin_seek);self.position.sliderReleased.connect(self.end_seek);playback.addWidget(self.position,1)
        self.clock=QLabel('0.000 / 0.000 秒');playback.addWidget(self.clock);rl.addLayout(playback)
        note=QLabel('保留原分辨率与透明度。透明片段画布不同时只补透明留白，底部居中，不拉伸人物；建议先统一人物大小和脚底后再拼接。首尾姿态相近时接缝更自然。')
        note.setWordWrap(True);rl.addWidget(note);split.addWidget(right);split.setSizes([330,620]);layout.addWidget(split,1)
        self.status=QLabel('请添加片段。');self.status.setWordWrap(True);layout.addWidget(self.status)
        footer=QHBoxLayout();self.cancel_button=QPushButton('关闭');self.cancel_button.clicked.connect(self.reject);footer.addWidget(self.cancel_button);footer.addStretch()
        self.save_all_button=QPushButton('保存全部档位');self.save_all_button.clicked.connect(self.save_all);self.save_all_button.hide();footer.addWidget(self.save_all_button)
        self.generate_button=QPushButton('生成预览');self.generate_button.setObjectName('primary');self.generate_button.clicked.connect(self.generate_or_save);footer.addWidget(self.generate_button);layout.addLayout(footer)
        self.preview_dir=Path(config['state_dir'])/'edit-previews';self.preview_dir.mkdir(parents=True,exist_ok=True)
        self.controls=(self.list,self.add_button,self.copy_button,self.remove_button,self.start,self.end,self.repeat,self.mark_start,self.mark_end,self.encoding_selector,self.version)
        self.estimate_timer=QTimer(self);self.estimate_timer.setSingleShot(True);self.estimate_timer.setInterval(400);self.estimate_timer.timeout.connect(self.start_estimates)
        self.encoding_selector.changed.connect(self.changed)
        self.changed()
        if paths:QTimer.singleShot(0,lambda:self.add_paths(paths))
        if parent:
            area=parent.screen().availableGeometry();self.resize(min(980,area.width()-50),min(740,area.height()-60))

    def current(self):
        item=self.list.currentItem();return self.entries.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
    def clips(self):return [self.entries[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]
    def signature(self):return (tuple((c.path,c.start_ms,c.end_ms,c.repeat) for c in self.clips()),tuple(self.encoding_selector.values()))
    def add_item(self,clip):
        key=uuid.uuid4().hex;self.entries[key]=clip;item=QListWidgetItem();item.setData(Qt.ItemDataRole.UserRole,key);self.list.addItem(item);self.update_label(item,clip)
        return item
    def update_label(self,item,clip):
        item.setText(f'{Path(clip.path).name}\n{clip.start_ms/1000:.3f} → {clip.end_ms/1000:.3f} 秒  × {clip.repeat}')
        item.setToolTip(clip.path)
    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'添加要裁剪或拼接的素材',self.config['input_dir'],FILTER)
        if paths:self.add_paths(paths)
    def add_paths(self,paths):
        if self.worker:return
        worker=EditWorker(paths=list(paths),parent=self);worker.scanned.connect(self.add_scanned)
        self.begin_worker(worker,'正在读取逐帧时序…')
    def add_scanned(self,infos,errors):
        first=None
        for info in infos:
            inherited=self.profiles.get(info.path) or self.config.get('processed_profiles',{}).get(Path(info.path).name)
            if inherited and not info.profile:
                from processed_profile import validate
                try:info=replace(info,profile=validate(inherited,info.size))
                except ValueError as error:errors.append(Path(info.path).name+'：'+str(error));continue
            self.infos[info.path]=info;item=self.add_item(Clip(info.path,0,info.duration_ms))
            if first is None:first=item
        if first:self.list.setCurrentItem(first)
        self.changed();self.status.setText('；'.join(errors) if errors else f'已读入 {len(infos)} 段。预览为完整原片，生成后查看裁剪和拼接结果。')
    def copy_current(self):
        clip=self.current()
        if clip:self.list.setCurrentItem(self.add_item(replace(clip)));self.changed()
    def remove_current(self):
        item=self.list.takeItem(self.list.currentRow())
        if item:self.entries.pop(item.data(Qt.ItemDataRole.UserRole),None)
        self.changed()
    def selected(self,*args):
        clip=self.current();self.loading=True
        try:
            if not clip:return
            info=self.infos[clip.path]
            for spin,value in ((self.start,clip.start_ms/1000),(self.end,clip.end_ms/1000),(self.repeat,clip.repeat)):
                with QSignalBlocker(spin):
                    if spin is not self.repeat:spin.setMaximum(info.duration_ms/1000)
                    spin.setValue(value)
            self.showing_result=False;self.preview_label.setText('原片预览 · '+Path(clip.path).name)
            self.canvas.load(clip.path,False,info.index_at(clip.start_ms),info.preview_meta())
        finally:self.loading=False
        self.changed()
    def update_segment(self,*args):
        if self.loading:return
        clip=self.current()
        if clip:
            clip=replace(clip,start_ms=round(self.start.value()*1000),end_ms=round(self.end.value()*1000),repeat=self.repeat.value())
            item=self.list.currentItem();self.entries[item.data(Qt.ItemDataRole.UserRole)]=clip;self.update_label(item,clip)
        self.changed()
    def changed(self,*args):
        valid=bool(self.list.count()) and bool(self.encoding_selector.values());total=0
        try:
            for clip in self.clips():
                start,end,repeat=bounds(clip,self.infos[clip.path]);total+=(end-start)*repeat
            if total>60000:raise ValueError('合成超过60秒，请缩短选段或减少重复')
            self.total.setText(f'{self.list.count()} 段 · 合成 {total/1000:.3f} 秒')
        except ValueError as error:valid=False;self.total.setText(str(error))
        same=self.preview_result is not None and self.result_signature==self.signature()
        self.result_button.setEnabled(self.preview_result is not None and not self.worker)
        self.generate_button.setText(('保存当前档位' if len(self.preview_results)>1 else '保存到素材列表') if same else '重新生成预览' if self.preview_result else ('生成对比预览' if len(self.encoding_selector.values())>1 else '生成预览'))
        self.generate_button.setEnabled(valid and not self.worker)
        self.save_all_button.setVisible(same and len(self.preview_results)>1);self.save_all_button.setEnabled(not self.worker)
        for control in (self.copy_button,self.remove_button,self.start,self.end,self.repeat,self.mark_start,self.mark_end):control.setEnabled(bool(self.current()) and not self.worker)
        if self.showing_result:
            self.mark_start.setEnabled(False);self.mark_end.setEnabled(False)
            if not same:self.preview_label.setText('旧合成预览 · 参数已改变，需要重新生成')
        self.schedule_estimates(valid)
    def schedule_estimates(self,valid):
        if not valid or not self.clips():
            self.estimate_timer.stop();self.estimate_key=None
            if self.estimator:self.estimator.requestInterruption()
            self.estimate_values={};self.encoding_selector.set_estimates({})
            self.size_summary.setText('预计大小：请设置有效选段并选择档位');return
        key=estimate_identity(self.clips(),self.infos,'lossless')
        if key==self.estimate_key:self.update_size_summary();return
        self.estimate_key=key;self.estimate_values=self.estimate_memory.get(key,{})
        self.encoding_selector.set_estimates(self.estimate_values)
        if self.estimator:self.estimator.requestInterruption()
        self.update_size_summary()
        if not self.estimate_values:self.estimate_timer.start()
    def start_estimates(self):
        if self.pending_close or self.worker or not self.estimate_key:return
        if self.estimator:return
        worker=EstimateWorker(self.estimate_key,self.clips(),dict(self.infos),Path(self.config['state_dir']),self);self.estimator=worker
        worker.estimated.connect(lambda values,w=worker:self.estimates_ready(w.key,values))
        worker.failed.connect(lambda error,w=worker:self.estimates_failed(w.key,error));worker.finished.connect(self.estimates_finished);worker.start()
    def estimates_ready(self,key,values):
        self.estimate_memory[key]=values
        if key!=self.estimate_key or self.pending_close:return
        self.estimate_values=values;self.encoding_selector.set_estimates(values);self.update_size_summary()
    def estimates_failed(self,key,error):
        if key==self.estimate_key and not self.worker and not self.pending_close:self.size_summary.setText('暂无法预估：'+error)
    def estimates_finished(self):
        worker=self.estimator;self.estimator=None;worker.deleteLater()
        if self.pending_close and not self.worker:self.reject()
        elif worker.key!=self.estimate_key and self.estimate_key:self.estimate_timer.start(0)
    def update_size_summary(self):
        actual={r['encoding']:r for r in self.preview_results} if self.result_signature==self.signature() else {}
        lines=[];details=[]
        for code in self.encoding_selector.values():
            prediction=self.estimate_values.get(code);description=format_estimate(prediction)
            if code in actual:
                size=actual[code]['bytes'];description=f'实测 {size/1048576:.2f} MB'
                if prediction:
                    deviation=(size/max(1,prediction['bytes'])-1)*100
                    details.append(preset(code)['label']+'：'+format_estimate(prediction)+f'；实测 {size/1048576:.2f} MB；相对预计中值 {deviation:+.1f}%')
            lines.append(preset(code)['label']+'：'+description)
        self.size_summary.setText('\n'.join(lines) if self.estimate_values or actual else '预计大小：正在抽样编码估算…')
        self.size_summary.setToolTip('\n'.join(details) if details else '按当前选段的原分辨率画面抽样编码估算；不是固定压缩比例，实际大小可能超出区间。')
    def frame_changed(self,index,meta):
        count=max(1,int(meta.get('frames',1)))
        if not self.seeking:
            with QSignalBlocker(self.position):self.position.setRange(0,count-1);self.position.setValue(index)
        clip=self.current()
        if clip and not self.showing_result:
            info=self.infos[clip.path];time=info.starts[min(index,len(info.durations))]/1000;duration=info.duration_ms/1000
        elif self.preview_result:
            time=sum(self.preview_result['durations'][:index])/1000;duration=self.preview_result['durationMs']/1000
        else:time=0;duration=0
        self.clock.setText(f'{time:.3f} / {duration:.3f} 秒')
    def begin_seek(self):self.seeking=True;self.seek_was_playing=self.canvas.playing;self.canvas.set_playing(False)
    def end_seek(self):
        self.canvas.seek(self.position.value());self.seeking=False;self.canvas.set_playing(getattr(self,'seek_was_playing',False))
    def set_start_here(self):
        clip=self.current()
        if clip and not self.showing_result:
            info=self.infos[clip.path];self.start.setValue(info.starts[min(self.canvas.index,len(info.durations)-1)]/1000)
    def set_end_here(self):
        clip=self.current()
        if clip and not self.showing_result:
            info=self.infos[clip.path];self.end.setValue(info.starts[min(self.canvas.index+1,len(info.durations))]/1000)
    def begin_worker(self,worker,message):
        if self.estimator:self.estimator.requestInterruption()
        self.worker=worker
        for control in self.controls:control.setEnabled(False)
        self.generate_button.setEnabled(False);self.cancel_button.setText('取消任务');self.status.setText(message)
        self.result_button.setEnabled(False)
        self.save_all_button.setEnabled(False)
        worker.failed.connect(self.status.setText);worker.finished.connect(self.worker_finished);worker.start()
    def worker_finished(self):
        worker=self.worker;self.worker=None;worker.deleteLater()
        for control in self.controls:control.setEnabled(True)
        self.cancel_button.setText('关闭');self.changed()
        if not self.pending_close and not self.estimate_values:self.estimate_timer.start(0)
        if self.saved_path:self.accept()
        elif self.pending_close:self.reject()
    def generate_or_save(self):
        if self.worker:return
        if self.preview_result is not None and self.result_signature==self.signature():self.save_result();return
        self.canvas.set_playing(False);self.rendering_signature=self.signature()
        path=self.preview_dir/(uuid.uuid4().hex+'.webp');self.owned_previews.append(path)
        codes=self.encoding_selector.values()
        if len(codes)>1:self.owned_previews.extend(path.with_name(path.stem+'-'+code+'.webp') for code in codes)
        self.config['clip_encodings']=codes
        parent=self.parent()
        if parent and hasattr(parent,'config_path'):
            from config_store import save_config
            save_config(parent.config_path,self.config)
        worker=EditWorker(clips=self.clips(),target=path,infos=dict(self.infos),parent=self,encodings=codes)
        worker.variants.connect(self.generated_many);worker.progress.connect(lambda code,n,total:self.status.setText(f"正在生成{preset(code)['label']}  {n} / {total} 帧…"))
        self.begin_worker(worker,'正在生成预览，保留透明度和原分辨率…')
    def generated_many(self,results):
        self.preview_results=results
        try:remember_actual(self.config['state_dir'],self.clips(),self.infos,results)
        except OSError:pass
        for result in results:
            code=result['encoding']
            if code not in self.estimate_values:
                size=result['bytes'];self.estimate_values[code]=dict(bytes=size,low=size,high=size,exact=True,source='previous-export')
        self.encoding_selector.set_estimates(self.estimate_values)
        with QSignalBlocker(self.version):
            self.version.clear()
            for result in results:self.version.addItem(preset(result['encoding'])['label']+f" · {result['bytes']/1048576:.2f} MB")
        self.version.setVisible(len(results)>1);self.generated(results[0])
    def select_version(self,index):
        if 0<=index<len(self.preview_results):self.generated(self.preview_results[index])
    def generated(self,result):
        self.preview_result=result;self.result_signature=self.rendering_signature;self.result_path=Path(result['path'])
        self.show_result()
        self.status.setText('预览已生成；可切换档位对比画质和文件大小，保存当前档或全部档位。不会自动替换桌宠。')
    def show_result(self):
        if self.preview_result is None:return
        result=self.preview_result
        self.showing_result=True;self.preview_label.setText('合成结果 · '+preset(result.get('encoding','lossless'))['label']+f" · {result.get('bytes',0)/1048576:.2f} MB")
        self.canvas.load(self.result_path,True,known_meta=dict(size=result['size'],frames=result['frames'],duration=result['durationMs']/1000,fps=result['frames']*1000/result['durationMs']))
        self.changed()
    def save_result(self):
        root=Path(self.config['input_dir']);folder=root/'导出结果' if (root/'导出结果').is_dir() else root;folder.mkdir(parents=True,exist_ok=True)
        suggested=folder/f"剪辑_{uuid.uuid4().hex[:8]}_{self.preview_result.get('encoding','lossless')}.webp"
        path,_=QFileDialog.getSaveFileName(self,'保存为新的桌宠素材',str(suggested),'动画 WebP (*.webp)')
        if not path:return
        if not Path(path).suffix:path+='.webp'
        try:
            if Path(path).suffix.lower()!='.webp':raise ValueError('请使用 .webp，保留透明度')
            if not Path(path).resolve().is_relative_to(folder.resolve()):raise ValueError('请保存到当前素材目录内，才能出现在素材列表：'+str(folder))
            if Path(path).exists():raise FileExistsError('文件已存在，请换一个名称；原文件不会覆盖')
        except Exception as error:QMessageBox.warning(self,'未保存',str(error));return
        worker=EditWorker(copy_source=self.result_path,target=Path(path),parent=self)
        worker.saved.connect(self.saved);self.begin_worker(worker,'正在保存新素材，原文件保持不变…')
    def saved(self,path):self.saved_path=path
    def save_all(self):
        if self.worker or len(self.preview_results)<2:return
        root=Path(self.config['input_dir']);folder=root/'导出结果' if (root/'导出结果').is_dir() else root
        chosen=QFileDialog.getExistingDirectory(self,'选择保存全部对比档位的素材目录',str(folder))
        if not chosen:return
        if not Path(chosen).resolve().is_relative_to(folder.resolve()):QMessageBox.warning(self,'未保存','请保存到当前素材目录内。');return
        prefix='剪辑_'+uuid.uuid4().hex[:8]
        jobs=[(Path(result['path']),Path(chosen)/(prefix+'_'+result['encoding']+'.webp')) for result in self.preview_results]
        worker=EditWorker(copy_jobs=jobs,parent=self);worker.saved_many.connect(self.saved_many)
        self.begin_worker(worker,'正在保存全部对比档位…')
    def saved_many(self,paths):self.saved_paths=paths;self.saved_path=paths[0] if paths else None
    def done(self,result):
        self.estimate_timer.stop()
        if self.worker:
            self.pending_close=True;self.worker.requestInterruption();self.status.setText('正在取消，等待当前编码结束；原文件不会修改。');return
        if self.estimator:
            self.pending_close=True;self.estimator.requestInterruption();self.status.setText('正在停止大小估算…');return
        self.canvas.close_player()
        for path in self.owned_previews:
            try:path.unlink(missing_ok=True)
            except OSError:pass  # A decoder may still be releasing its file handle.
        super().done(result)
    def closeEvent(self,event):
        if self.worker or self.estimator:self.reject();event.ignore();return
        super().closeEvent(event)
