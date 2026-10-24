"""Non-modal settings, live controls and character diagnostics."""
import copy
import sys
import threading
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,
    QCheckBox,QDoubleSpinBox,QPlainTextEdit,QPushButton,QComboBox,QLabel,QFileDialog,QMessageBox,QScrollArea,QLineEdit)
from desktop_core import DEFAULTS,VERSION
from desktop_services import autostart_enabled,set_autostart,import_character,validate_character,all_items
from settings_draft import SettingsDraft
from connection_widgets import CapabilityPanel
from ui_theme import MUTED,PRIMARY,BORDER
from card_motion import AnimatedDisclosure

class ConnectionJob(QThread):
    report=Signal(object)
    def __init__(self,parent=None):super().__init__(parent);self.cancel=threading.Event()
    def run(self):
        from codex_connection import check_connection
        try:self.report.emit(check_connection(cancel=self.cancel))
        except Exception:self.report.emit(dict(summary='连接检查暂不可用，请稍后重试。'))

class LibraryJob(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,source,destination=None,parent=None):super().__init__(parent);self.source=source;self.destination=destination
    def run(self):
        try:
            if self.destination:self.result.emit(import_character(self.source,self.destination))
            else:self.result.emit(validate_character(self.source))
        except Exception as error:self.failed.emit(str(error)[:250])

class ConverterJob(LibraryJob):
    def run(self):
        from optional_tools import save_ffmpeg
        try:save_ffmpeg(self.source);self.result.emit(str(self.source))
        except (OSError,ValueError) as error:self.failed.emit(str(error))

class PathsJob(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,values,parent=None):super().__init__(parent);self.values=values
    def run(self):
        from codex_connection import validate_paths
        try:self.result.emit(validate_paths(self.values))
        except (OSError,ValueError) as error:self.failed.emit(str(error))

class SettingsDialog(QDialog):
    def __init__(self,pet,embedded=False):
        super().__init__(pet,Qt.WindowType.Widget if embedded else Qt.WindowType.Dialog);self.pet=pet;self.embedded=embedded;self.fields={};self.job=None;self.connection_job=None
        self.field_tabs={};self.field_titles={};self.factors={};self._writing_widgets=True;self.draft=None;self.path_job=None
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('白龙桌宠 · 设置');self.resize(590,680)
        outer=QVBoxLayout(self);self.tabs=QTabWidget();self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone);outer.addWidget(self.tabs,1)
        appearance=self.tab('常规与外观')
        self.section(appearance,'桌面与显示','这里的偏好点击“应用”后生效；切页会保留草稿。')
        self.startup=QCheckBox('登录 macOS 时启动' if sys.platform=='darwin' else '登录 Windows 时启动');appearance.addRow(self.startup)
        self.field_tabs['startup']=self.tabs.count()-1;self.field_titles['startup']='开机启动'
        self.startup.toggled.connect(lambda:self.edited('startup'))
        self.codex_startup=QCheckBox('打开 Codex 时自动启动桌宠');appearance.addRow(self.codex_startup)
        if sys.platform!='win32':
            self.codex_startup.setEnabled(False);self.codex_startup.setToolTip('此启动监听目前仅支持 Windows；Mac 可使用登录启动。')
        self.field_tabs['codex_startup']=0;self.field_titles['codex_startup']='随 Codex 启动'
        self.codex_startup.toggled.connect(lambda:self.edited('codex_startup'))
        note=QLabel('登录时运行轻量监听；识别 Codex 桌面端，不依赖 Codex++。手动退出桌宠后，本次 Codex 使用期间不再拉起。关闭 Codex 不会强制退出桌宠。');note.setWordWrap(True);note.setStyleSheet(f'font-size:10px;color:{MUTED};');appearance.addRow(note)
        self.number(appearance,'scale','角色大小（倍）',.4,2.5,.1)
        for key,title in [('character_visible','显示人物（关闭后仅保留独立卡片）'),('on_top','始终置顶'),('video_fullscreen_yield','视频全屏时临时取消置顶（完成提醒优先）'),('mouse_through','鼠标穿透（从托盘找回）'),('bubble','显示状态卡片'),('quota_visible','显示额度和重置时间'),('commentary','展示 Codex 回复摘要')]:
            self.check(appearance,key,title)
            if key=='video_fullscreen_yield':
                note=QLabel('完成提醒确认后继续让位。Mac 浏览器识别需在系统设置中授予运行此程序的 Python 辅助功能权限；不读取标题或网址。' if sys.platform=='darwin' else '完成提醒确认后，视频仍全屏则继续让位；退出全屏恢复当前置顶设置。')
                note.setWordWrap(True);note.setStyleSheet(f'font-size:10px;color:{MUTED};');appearance.addRow(note)
        self.check(appearance,'conversation_auto_scroll','自动轮换状态会话（保留两条，悬停时暂停）')
        self.number(appearance,'conversation_scroll_seconds','会话轮换间隔（秒）',2,120,1)
        self.mode=QComboBox();self.mode.addItem('自动：正常卡片 / 闲置时胶囊','auto');self.mode.addItem('胶囊：状态和快捷圆','mini');self.mode.addItem('极简：仅额度百分比','minimal')
        appearance.addRow('卡片显示模式',self.mode);self.fields['bubble_mode']=self.mode;self.field_tabs['bubble_mode']=0;self.field_titles['bubble_mode']='卡片显示模式'
        self.mode.currentIndexChanged.connect(lambda:self.edited('bubble_mode'))
        from quick_actions import ACTIONS
        self.shortcut=QComboBox()
        for key,title,icon in ACTIONS:self.shortcut.addItem(title,key)
        appearance.addRow('胶囊左侧快捷功能',self.shortcut);self.fields['capsule_action']=self.shortcut;self.field_tabs['capsule_action']=0;self.field_titles['capsule_action']='胶囊快捷功能'
        self.shortcut.currentIndexChanged.connect(lambda:self.edited('capsule_action'))
        self.website=QLineEdit();self.website.setPlaceholderText('https://…');self.website.setAccessibleName('自定义网页地址');self.website.setMaxLength(2048)
        appearance.addRow('自定义网页地址',self.website);self.fields['capsule_website']=self.website;self.field_tabs['capsule_website']=0;self.field_titles['capsule_website']='自定义网页地址'
        self.website.textChanged.connect(lambda:self.edited('capsule_website'))
        note=QLabel('仅卡片时可拖动空白处或极简圆；点击极简圆回到正常卡片，右键可切换显示模式。人物隐藏后暂停动画，Codex 联动继续。');note.setWordWrap(True);appearance.addRow(note)
        behavior=self.tab('动作与陪伴')
        self.section(behavior,'人物行为','先选择陪伴方式，再按需展开高级参数。')
        self.check(behavior,'no_move','锁定人物位置（禁止拖动和自主走动）')
        self.check(behavior,'wandering','允许自主走动（不影响手动拖动）')
        self.movement_note=QLabel();self.movement_note.setWordWrap(True);behavior.addRow(self.movement_note)
        self.check(behavior,'random_actions','自动随机动作')
        self.check(behavior,'status_actions','根据 Codex 当前状态播放动作（播完后再切换）')
        self.check(behavior,'sound','主动点击人物或手动动作时播放音效')
        self.check(behavior,'self_talk','启用自言自语（自动台词无声）')
        self.advanced_button=QPushButton('展开高级参数与台词');self.advanced_button.setCheckable(True);behavior.addRow(self.advanced_button)
        advanced=QWidget();advanced_form=QFormLayout(advanced);advanced_form.setContentsMargins(0,0,0,0)
        self.number(advanced_form,'status_action_interval','单次状态动作重复间隔（秒）',8,120,1)
        self.check(advanced_form,'drag_physics','拖拽松手后启用惯性与反弹')
        for key,title,lo,hi,step in [('playback_speed','播放速度（倍）',.25,3,.25),('action_gap','动作结束后等待（秒）',0,60,1),('random_interval','自主动作间隔（秒）',3,600,1),('move_speed','自主走动速度（像素/秒）',10,300,5)]:self.number(advanced_form,key,title,lo,hi,step)
        self.number(advanced_form,'move_range','自主活动范围',.1,1,.1,factor=100,suffix='% 屏幕')
        note=QLabel('思考/阅读和处理任务在状态稳定1.5秒后进入，保持中段循环，状态改变后自然收尾。其他动作完整播放并按间隔检查。完成消息立即提醒，庆祝等待安全边界。');note.setWordWrap(True);note.setStyleSheet('font-size:10px;color:#706879;');behavior.addRow(note)
        self.check(advanced_form,'talk_quiet','Codex 工作时不自言自语')
        self.number(advanced_form,'talk_min','台词最短间隔（秒）',5,3600,5);self.number(advanced_form,'talk_max','台词最长间隔（秒）',5,7200,5)
        self.lines=QPlainTextEdit();self.lines.setMaximumHeight(100);self.lines.setPlaceholderText('每行一句，自动台词不会播放声音');advanced_form.addRow('自定义台词',self.lines)
        self.field_tabs['talk_lines']=self.tabs.count()-1;self.field_titles['talk_lines']='自定义台词';self.lines.textChanged.connect(lambda:self.edited('talk_lines'))
        self.advanced_card=AnimatedDisclosure(advanced);behavior.addRow(self.advanced_card)
        self.advanced_button.toggled.connect(self.advanced_card.set_expanded)
        self.advanced_button.toggled.connect(lambda checked:self.advanced_button.setText('收起高级参数与台词' if checked else '展开高级参数与台词'))
        connection=self.tab('连接与数据')
        self.section(connection,'Codex 连接健康','各项独立检测；失败不会当作已读、零额度或零用量。')
        self.connection_button=QPushButton('检测连接与额度');self.connection_button.setProperty('role','primary');self.connection_button.clicked.connect(self.check_connection);connection.addRow(self.connection_button)
        self.health_panel=CapabilityPanel();self.health_panel.set_snapshot(pet.connection_health.snapshot());connection.addRow(self.health_panel)
        pet.connectionHealthChanged.connect(self.health_panel.set_snapshot)
        row=QWidget();buttons=QHBoxLayout(row);buttons.setContentsMargins(0,0,0,0);self.refresh_buttons={}
        for key,title,slot in [('quota','刷新额度',pet.refresh_quota),('reset','刷新重置消息',pet.refresh_reset_feed),('token','刷新 Token',pet.refresh_tokens)]:
            button=QPushButton(title);button.clicked.connect(slot);buttons.addWidget(button);self.refresh_buttons[key]=(button,title)
        connection.addRow(row)
        if not getattr(sys,'frozen',False):
            from mac_bridge import BridgeSettingsPanel
            self.section(connection,'SSH 远程会话','填写本机已配置且可免交互连接的 SSH 别名。')
            connection.addRow(BridgeSettingsPanel())
        self.section(connection,'白龙聊天服务','与 Codex 的只读联动独立；仅主动发送时调用。')
        button=QPushButton('配置白龙聊天服务…');button.clicked.connect(pet.open_chat_service);connection.addRow(button)
        self.path_toggle=QPushButton('连接路径与检测报告');self.path_toggle.setCheckable(True);connection.addRow(self.path_toggle)
        path_body=QWidget();paths=QFormLayout(path_body);paths.setContentsMargins(0,4,0,4)
        from codex_connection import saved_paths,data_home
        saved=saved_paths();self.path_fields={}
        for key,title in [('home','Codex 数据目录'),('cli','Codex CLI 程序')]:
            row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
            field=QLineEdit(saved.get(key,''));field.setPlaceholderText('留空自动识别');field.setAccessibleName(title);self.path_fields[key]=field;layout.addWidget(field,1)
            browse=QPushButton('选择…');browse.clicked.connect(lambda checked=False,k=key:self.choose_path(k));layout.addWidget(browse);paths.addRow(title,row)
        self.active_path=QLabel('当前生效目录：'+str(data_home()));self.active_path.setWordWrap(True);self.active_path.setStyleSheet(f'font-size:10px;color:{MUTED};');paths.addRow(self.active_path)
        note=QLabel('保存后重启桌宠生效；环境变量优先。只修改本桌宠的路径，不更改 Codex 或登录凭据。');note.setWordWrap(True);note.setStyleSheet(f'font-size:10px;color:{MUTED};');paths.addRow(note)
        row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
        self.save_paths_button=QPushButton('验证并保存路径');self.save_paths_button.clicked.connect(self.validate_paths);layout.addWidget(self.save_paths_button)
        reset=QPushButton('改为自动识别');reset.clicked.connect(lambda:[field.clear() for field in self.path_fields.values()]);layout.addWidget(reset);paths.addRow(row)
        self.path_status=QLabel();self.path_status.setWordWrap(True);paths.addRow(self.path_status)
        self.connection_text=QPlainTextEdit();self.connection_text.setReadOnly(True);self.connection_text.setMaximumHeight(140);self.connection_text.setAccessibleName('最近一次连接检测报告')
        self.connection_text.setPlainText('点击“检测连接与额度”生成只读报告；不会发送对话或消耗 Token。');paths.addRow(self.connection_text)
        self.paths_card=AnimatedDisclosure(path_body);connection.addRow(self.paths_card);self.path_toggle.toggled.connect(self.paths_card.set_expanded)
        library=self.tab('角色与动作')
        if hasattr(pet,'materials'):
            self.section(library,'内置白龙画质','素材与程序独立；下载和切换立即执行，不属于设置草稿。')
            from material_controller import MaterialPanel
            self.material_panel=MaterialPanel(pet.materials);library.addRow(self.material_panel)
        self.section(library,'角色资源','切换、导入和预览立即执行；预览始终静音。')
        self.characters=QComboBox();library.addRow('当前角色',self.characters)
        button=QPushButton('切换到所选角色');button.clicked.connect(self.switch_character);library.addRow(button)
        button=QPushButton('导入角色文件夹（WebP / GIF / WebM）');button.clicked.connect(self.import_pack);library.addRow(button)
        tool=QPushButton('WebM 转换工具…');tool.clicked.connect(self.select_converter);library.addRow(tool)
        self.actions=QComboBox();library.addRow('动作分类与预览',self.actions)
        button=QPushButton('静音预览所选动作');button.clicked.connect(self.preview);library.addRow(button)
        button=QPushButton('检查所有素材');button.clicked.connect(self.validate);library.addRow(button)
        self.library_status=QLabel();self.library_status.setWordWrap(True);library.addRow(self.library_status)
        maintenance=self.tab('维护与数据')
        if not getattr(sys,'frozen',False) or sys.platform=='darwin':
            from mac_maintenance import SourceMaintenancePanel
            self.section(maintenance,'源码维护','修改后重新启动即可生效；设置、聊天和统计独立保存。')
            maintenance.addRow(SourceMaintenancePanel(pet))
        else:
            self.section(maintenance,'软件更新','检查 GitHub 公开稳定版；下载和安装由你主动发起。')
            self.check(maintenance,'update_checks','自动检查更新（不自动下载）')
            if hasattr(pet,'updates'):
                from update_widgets import UpdatePanel
                self.update_panel=UpdatePanel(pet.updates);maintenance.addRow(self.update_panel)
        self.section(maintenance,'诊断与数据','维护操作立即执行；不属于设置草稿。')
        for title,slot in [('打开配置与聊天记录目录',pet.open_data),('导出诊断报告（不含对话和密钥）',pet.export_diagnostics),('备份设置（不含密钥与对话）',pet.backup_settings),('恢复设置备份',pet.restore_settings)]:
            button=QPushButton(title);button.clicked.connect(slot);maintenance.addRow(button)
        maintenance.addRow(QLabel('版本 '+VERSION+' · 旧配置自动迁移，退出后保存位置和朝向'))
        self.draft_status=QLabel();self.draft_status.setWordWrap(True);outer.addWidget(self.draft_status)
        self.status=QLabel();self.status.setWordWrap(True);outer.addWidget(self.status)
        row=QHBoxLayout()
        self.defaults_button=QPushButton('本页恢复默认');self.defaults_button.clicked.connect(self.defaults);row.addWidget(self.defaults_button)
        self.discard_button=QPushButton('放弃修改');self.discard_button.clicked.connect(self.reload);row.addWidget(self.discard_button)
        self.apply_button=QPushButton('应用');self.apply_button.clicked.connect(self.apply);row.addWidget(self.apply_button)
        button=QPushButton('返回' if embedded else '关闭');button.clicked.connect(self.dismiss);row.addWidget(button)
        for control in self.findChildren(QPushButton):control.setAutoDefault(False)
        self.apply_button.setProperty('role','primary');self.apply_button.setAutoDefault(True);self.apply_button.setDefault(True)
        self.save_shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Save),self);self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);self.save_shortcut.activated.connect(self.apply)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        outer.addLayout(row);self.tabs.currentChanged.connect(self.update_draft_state);self.reload()
        if hasattr(pet,'settingsChanged'):pet.settingsChanged.connect(self.sync_from_pet)
        pet.bubble.dataBusyChanged.connect(self.update_refresh_state)
        for key in self.refresh_buttons:self.update_refresh_state(key,getattr(pet.bubble,key+'_busy'))
    def section(self,form,title,note):
        name=QLabel(title);name.setStyleSheet(f'font-size:13px;font-weight:600;color:{PRIMARY};margin-top:3px;');form.addRow(name)
        label=QLabel(note);label.setWordWrap(True);label.setStyleSheet(f'font-size:10px;color:{MUTED};margin-bottom:3px;');form.addRow(label)
    def choose_path(self,key):
        if key=='home':value=QFileDialog.getExistingDirectory(self,'选择 Codex 数据目录',self.path_fields[key].text())
        else:value,_=QFileDialog.getOpenFileName(self,'选择 Codex CLI（不是桌面主程序）',self.path_fields[key].text(),'所有文件 (*)' if sys.platform=='darwin' else '程序 (*.exe);;所有文件 (*)')
        if value:self.path_fields[key].setText(value)
    def validate_paths(self):
        if self.path_job and self.path_job.isRunning():return
        values={key:field.text().strip().strip('"') for key,field in self.path_fields.items()}
        self.save_paths_button.setEnabled(False);self.path_status.setText('正在验证路径与 CLI 版本…')
        self.path_job=PathsJob(values,self);self.path_job.result.connect(self.paths_done);self.path_job.failed.connect(self.path_status.setText)
        self.path_job.finished.connect(lambda:self.save_paths_button.setEnabled(True));self.path_job.start()
    def paths_done(self,values):
        if any(self.path_fields[key].text().strip().strip('"')!=self.path_job.values[key] for key in self.path_fields):
            self.path_status.setText('验证期间输入已改变，请重新验证；未保存。');return
        from desktop import STATE_DIR
        from codex_connection import save_paths
        try:save_paths(values,STATE_DIR/'connection-paths.json')
        except OSError:self.path_status.setText('路径保存失败，输入仍保留。');return
        for key,value in values.items():self.path_fields[key].setText(value)
        self.path_status.setText('已验证并保存，重启桌宠后生效；当前监测继续使用原路径。')
    def update_refresh_state(self,key,busy):
        button,title=self.refresh_buttons[key];button.setEnabled(not busy);button.setText('查询中…' if busy else title)
    def tab(self,title):
        widget=QWidget();form=QFormLayout(widget)
        if self.embedded:
            widget.setObjectName('settings_category');widget.setStyleSheet('QWidget#settings_category{background:#f5f2f7;}')
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            area=QScrollArea();area.setWidgetResizable(True)
            # Reserve the gutter so opening a disclosure cannot rewrap its body.
            area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn);area.setWidget(widget)
            index=self.tabs.addTab(area,{'常规与外观':'常规','动作与陪伴':'动作','角色与动作':'角色','维护与数据':'维护','连接与数据':'连接'}.get(title,title))
            self.tabs.setTabToolTip(index,title)
        else:self.tabs.addTab(widget,title)
        return form
    def dismiss(self):
        if self.embedded:self.pet.bubble.return_to_status()
        else:self.hide()
    def keyPressEvent(self,event):
        if self.embedded and event.key()==Qt.Key.Key_Escape:self.dismiss();event.accept();return
        super().keyPressEvent(event)
    def check(self,form,key,title):
        widget=QCheckBox(title);self.fields[key]=widget;form.addRow(widget);self.field_tabs[key]=self.tabs.count()-1;self.field_titles[key]=title
        widget.toggled.connect(lambda:self.edited(key))
    def number(self,form,key,title,lo,hi,step,factor=1,suffix=''):
        widget=QDoubleSpinBox();widget.setRange(lo*factor,hi*factor);widget.setSingleStep(step*factor);widget.setDecimals(0 if step*factor>=1 else 2);widget.setSuffix(suffix)
        self.fields[key]=widget;self.factors[key]=factor;self.field_tabs[key]=self.tabs.count()-1;self.field_titles[key]=title;form.addRow(title,widget)
        widget.valueChanged.connect(lambda:self.edited(key))
    def fill(self,settings):
        self._writing_widgets=True
        for key,widget in self.fields.items():
            if isinstance(widget,QCheckBox):widget.setChecked(settings.get(key,DEFAULTS[key]))
            elif isinstance(widget,QComboBox):widget.setCurrentIndex(widget.findData(settings.get(key,DEFAULTS[key])))
            elif isinstance(widget,QLineEdit):widget.setText(settings.get(key,DEFAULTS[key]))
            else:widget.setValue(settings.get(key,DEFAULTS[key])*self.factors.get(key,1))
        lines='\n'.join(settings.get('talk_lines',DEFAULTS['talk_lines']))
        current=[line.strip() for line in self.lines.toPlainText().splitlines() if line.strip()]
        if current!=settings.get('talk_lines',DEFAULTS['talk_lines']):self.lines.setPlainText(lines)
        self.startup.setChecked(bool(settings.get('startup',False)));self.codex_startup.setChecked(bool(settings.get('codex_startup',False)));self._writing_widgets=False
    def values_from_pet(self,read_startup=False):
        values={key:copy.deepcopy(self.pet.settings.get(key,DEFAULTS[key])) for key in self.fields}
        values['talk_lines']=copy.deepcopy(self.pet.settings.get('talk_lines',DEFAULTS['talk_lines']))
        if read_startup:
            from codex_startup import enabled
            try:values['startup']=autostart_enabled();values['codex_startup']=enabled()
            except OSError:self.status.setText('开机启动状态读取失败；其他设置仍可修改。')
        return values
    def reload(self):
        self.status.clear();values=self.values_from_pet(read_startup=True);values.setdefault('startup',False)
        self.draft=SettingsDraft(values);self.fill(self.draft.values);self.refresh_library();self.update_draft_state()
    def sync_from_pet(self,changes=None,read_startup=False):
        if self.draft is None:return
        self.draft.rebase(self.values_from_pet(read_startup));self.fill(self.draft.values);self.update_draft_state()
    def edited(self,key):
        if self._writing_widgets or self.draft is None:return
        if key=='startup':value=self.startup.isChecked()
        elif key=='codex_startup':value=self.codex_startup.isChecked()
        elif key=='talk_lines':value=[line.strip() for line in self.lines.toPlainText().splitlines() if line.strip()]
        else:
            widget=self.fields[key];value=widget.isChecked() if isinstance(widget,QCheckBox) else widget.currentData() if isinstance(widget,QComboBox) else widget.text() if isinstance(widget,QLineEdit) else widget.value()/self.factors.get(key,1)
        self.draft.set(key,value);self.status.clear();self.update_draft_state()
    def update_draft_state(self,*args):
        if self.draft is None:return
        self.website.setEnabled(self.shortcut.currentData()=='website')
        count=len(self.draft.dirty);self.apply_button.setEnabled(bool(count));self.discard_button.setEnabled(bool(count))
        shortcut='⌘S' if sys.platform=='darwin' else 'Ctrl+S'
        text=f'有 {count} 项未保存修改 · {shortcut} 应用 · 切页保留草稿' if count else f'设置已保存 · {shortcut} 应用修改'
        if self.draft.conflicts:
            names='、'.join(self.field_titles[k] for k in sorted(self.draft.conflicts))
            text+='\n外部也修改了：'+names+'。应用将采用此处草稿；放弃修改将采用当前值。'
        self.draft_status.setText(text)
        self.defaults_button.setEnabled(any(tab==self.tabs.currentIndex() and key in DEFAULTS for key,tab in self.field_tabs.items()))
        locked=self.fields['no_move'].isChecked()
        for key in ('wandering','drag_physics','move_speed','move_range'):self.fields[key].setEnabled(not locked)
        self.movement_note.setText('位置已锁定：禁止拖动和自主走动；下方移动偏好会保留，解除锁定后恢复。' if locked else '自主走动关闭时仍可手动拖动；工作动作优先于自动随机动作。')
        self.fields['status_action_interval'].setEnabled(self.fields['status_actions'].isChecked())
        talking=self.fields['self_talk'].isChecked()
        for key in ('talk_quiet','talk_min','talk_max'):self.fields[key].setEnabled(talking)
        self.lines.setEnabled(talking)
    def defaults(self):
        for key,tab in self.field_tabs.items():
            if tab==self.tabs.currentIndex() and key in DEFAULTS:self.draft.set(key,DEFAULTS[key])
        self.fill(self.draft.values);self.update_draft_state();self.status.setText('已载入本页默认值，应用后生效；不影响开机启动、角色及聊天服务。')
    def apply(self):
        values=self.draft.changes();startup=values.pop('startup',None);codex_startup=values.pop('codex_startup',None);messages=[]
        if values:
            try:
                self.pet.apply_settings(values)
                for key in values:
                    self.draft.values[key]=copy.deepcopy(self.pet.settings[key]);self.draft.baseline[key]=copy.deepcopy(self.pet.settings[key]);self.draft.conflicts.discard(key)
                messages.append('桌宠设置已保存。')
            except (OSError,ValueError) as error:messages.append('桌宠设置保存失败：'+str(error))
        if startup is not None:
            try:set_autostart(startup);self.draft.rebase({'startup':startup});messages.append('开机启动已保存。')
            except OSError as error:messages.append('开机启动保存失败：'+str(error)+'；可单独重试。')
        if codex_startup is not None:
            from codex_startup import configure
            try:configure(codex_startup);self.draft.rebase({'codex_startup':codex_startup});messages.append('Codex 启动联动已保存。')
            except OSError as error:messages.append('Codex 启动联动保存失败：'+str(error)+'；可单独重试。')
        self.fill(self.draft.values);self.update_draft_state();self.status.setText('\n'.join(messages))
    def refresh_library(self):
        self.characters.clear()
        for key,name in self.pet.character_choices():self.characters.addItem(name,key)
        self.characters.setCurrentIndex(self.characters.findData(self.pet.settings.get('character','builtin')))
        self.actions.clear()
        for group,items in self.pet.action_groups().items():
            for item in items:self.actions.addItem(group+' / '+item.get('name',item['id']),item)
        self.library_status.setText(f'当前 {len(all_items(self.pet.manifest))} 段素材；缺省类别使用待机或现有动作回退。')
    def switch_character(self):
        try:self.pet.switch_character(self.characters.currentData());self.refresh_library()
        except (OSError,ValueError,KeyError) as error:self.library_status.setText('切换失败：'+str(error))
    def preview(self):
        item=self.actions.currentData()
        if item:self.pet.choose(item,interactive=False,manual=True)
    def select_converter(self):
        if self.job and self.job.isRunning():self.library_status.setText('正在检查或导入，请稍等…');return
        path,_=QFileDialog.getOpenFileName(self,'选择 FFmpeg 转换工具（仅导入 WebM 时使用）','','所有文件 (*)' if sys.platform=='darwin' else 'FFmpeg (ffmpeg*.exe);;所有文件 (*)')
        if not path:return
        self.library_status.setText('正在后台验证转换工具…')
        self.job=ConverterJob(path,None,self)
        self.job.result.connect(lambda _:self.library_status.setText('转换工具已验证，导入 WebM 时使用；日常动画播放不依赖它。'))
        self.job.failed.connect(self.library_status.setText);self.job.start()
    def import_pack(self):
        source=QFileDialog.getExistingDirectory(self,'选择包含素材清单或分类素材文件夹的角色包')
        if source:self.start_job(source,self.pet.character_dir)
    def validate(self):self.start_job(self.pet.asset_root)
    def start_job(self,source,destination=None):
        if self.job and self.job.isRunning():self.library_status.setText('正在检查或导入，请稍等…');return
        self.library_status.setText('后台检查 / 转换中，桌宠仍可操作…')
        self.job=LibraryJob(source,destination,self)
        self.job.result.connect(lambda value:self.job_done(value,destination));self.job.failed.connect(lambda error:self.library_status.setText('素材检查失败：'+error));self.job.start()
    def job_done(self,value,destination):
        self.refresh_library();self.library_status.setText('角色已导入，可在上方切换。' if destination else '所有素材已逐帧检查，可正常读取。')
    def check_connection(self):
        if self.connection_job and self.connection_job.isRunning():return
        self.connection_button.setEnabled(False);self.connection_text.setPlainText('正在检查本机 Codex 和账户额度…')
        self.connection_job=ConnectionJob(self);self.connection_job.report.connect(self.connection_done)
        self.connection_job.finished.connect(lambda:self.connection_button.setEnabled(True));self.connection_job.start()
    def connection_done(self,report):
        from desktop import STATE_DIR
        from desktop_core import atomic_json
        self.pet.update_connection_health(report.get('capabilities',{}))
        path=STATE_DIR/'codex-connection-check.json'
        try:atomic_json(path,report);note='\n\n报告已保存：'+str(path)
        except OSError:note='\n\n报告文件保存失败；检测结果仍可查看。'
        self.connection_text.setPlainText(report.get('summary','检查完成')+note)
    def closeEvent(self,event):self.hide();event.ignore()
