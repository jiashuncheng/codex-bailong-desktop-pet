"""User initiated, OpenAI-compatible SSE chat, separate from Codex monitoring."""
import copy
import sys
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,QObject,Signal,QTimer,QUrl
from PySide6.QtGui import QTextCursor
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,
    QPlainTextEdit,QLabel,QCheckBox,QMessageBox,QDialog,QFormLayout,QLineEdit,QSpinBox,QStackedWidget,QScrollArea,QMenu)
from desktop_core import atomic_json
from desktop_services import SecretStore
from inline_confirmation import InlineConfirmation

CHAT_DEFAULT=dict(providers=[],active='',system_prompt='你是白龙娘，是陪伴用户工作的桌面伙伴。用自然、简洁的中文回应。',history_messages=40,history_chars=24000)
def load_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return copy.deepcopy(default)

def trim_messages(messages,count,chars):
    result=[];total=0
    for message in reversed(messages[-max(1,count):]):
        text=str(message.get('content',''))
        if total+len(text)>chars:
            if not result:result.append(dict(role=message['role'],content=text[-chars:]))
            break
        result.append(dict(role=message['role'],content=text));total+=len(text)
    result.reverse()
    while len(result)>1 and result[0]['role']=='assistant':result.pop(0)
    return result

class SessionStore:
    def __init__(self,root,character):
        self.path=Path(root)/('sessions-'+__import__('hashlib').sha256(character.encode()).hexdigest()[:16]+'.json')
        self.sessions=load_json(self.path,[])
        if not isinstance(self.sessions,list):self.sessions=[]
    def save(self):atomic_json(self.path,self.sessions)
    def new(self):
        session=dict(id=uuid.uuid4().hex,title='新对话',messages=[],at=time.time())
        self.sessions.insert(0,session);self.save();return session

class ChatStream(QObject):
    delta=Signal(str);done=Signal(str);failed=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.manager=QNetworkAccessManager(self);self.reply=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.timeout)
        self.buffer=b'';self.text='';self.cancelled=False;self.completed=False
    def start(self,provider,key,messages):
        url=provider.get('base_url','').strip().rstrip('/')
        parts=urlsplit(url)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('服务地址需为有效的 http/https API 基础地址')
        if parts.scheme=='http' and parts.hostname not in ('localhost','127.0.0.1','::1'):
            raise ValueError('远程服务请使用 HTTPS；本地服务可以使用 HTTP')
        if not provider.get('model','').strip():raise ValueError('请先填写模型名称')
        if not url.endswith('/chat/completions'):url+='/chat/completions'
        self.buffer=b'';self.text='';self.cancelled=False;self.completed=False
        request=QNetworkRequest(QUrl(url));request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        request.setRawHeader(b'Accept',b'text/event-stream')
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if key:request.setRawHeader(b'Authorization',('Bearer '+key).encode())
        body=json.dumps(dict(model=provider['model'],messages=messages,stream=True),ensure_ascii=False).encode('utf-8')
        self.reply=self.manager.post(request,body);reply=self.reply
        reply.readyRead.connect(lambda:self.read(reply))
        reply.finished.connect(lambda:self.finish(reply))
        self.timer.start(max(5,min(600,int(provider.get('timeout',90))))*1000)
    def read(self,reply):
        if self.cancelled or reply is not self.reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and int(status)>=300:reply.readAll();return
        self.buffer+=bytes(reply.readAll())
        if len(self.buffer)>2_000_000:self.fail('接口返回数据过大');return
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1);line=line.rstrip(b'\r')
            if not line.startswith(b'data:'):continue
            data=line[5:].strip()
            if data==b'[DONE]':self.completed=True;continue
            try:
                event=json.loads(data)
                if event.get('error'):self.fail('模型服务返回错误，请检查服务配置');return
                for choice in event.get('choices',[]):
                    value=choice.get('delta',{}).get('content')
                    if isinstance(value,str):
                        if len(self.text)+len(value)>500000:self.fail('回复过长，已停止');return
                        self.text+=value;self.delta.emit(value)
                    if choice.get('finish_reason'):self.completed=True
            except (ValueError,TypeError,AttributeError):self.fail('无法解析服务的流式响应');return
    def finish(self,reply):
        if reply is not self.reply:reply.deleteLater();return
        if not self.cancelled:self.read(reply)
        self.timer.stop();self.reply=None
        if not self.cancelled:
            status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status and int(status)>=300:self.failed.emit(f'模型服务 HTTP {int(status)}；请检查地址、模型和密钥')
            elif reply.error()!=QNetworkReply.NetworkError.NoError:self.failed.emit('连接中断或服务不可用；请检查网络后重试')
            elif not self.completed:self.failed.emit('服务在回复完成前断开，可以重试')
            else:self.done.emit(self.text)
        reply.deleteLater()
    def fail(self,message):
        self.cancel();self.failed.emit(message)
    def timeout(self):self.fail('请求超时，可调整服务超时后重试')
    def cancel(self):
        self.cancelled=True;self.timer.stop()
        if self.reply:self.reply.abort()

class ProviderDialog(QDialog):
    def __init__(self,root,parent=None,embedded=False):
        super().__init__(parent,Qt.WindowType.Widget if embedded else Qt.WindowType.Dialog);self.root=Path(root);self.path=self.root/'chat.json'
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget);self.setObjectName('provider_settings');self.setStyleSheet('QWidget#provider_settings{background:#f5f2f7;}')
        self.config=load_json(self.path,CHAT_DEFAULT);self.secrets=SecretStore(self.root/'credentials.dpapi.json')
        self.drafts={};self.current=None
        self.setWindowTitle('白龙 · 模型服务');self.resize(530,550);layout=QVBoxLayout(self)
        row=QHBoxLayout();self.select=QComboBox();row.addWidget(self.select,1)
        for title,slot in [('添加',self.add),('删除',self.remove)]:
            b=QPushButton(title);b.clicked.connect(slot);row.addWidget(b)
            if title=='删除':b.setProperty('role','danger')
        layout.addLayout(row);self.confirmation=InlineConfirmation();layout.addWidget(self.confirmation)
        self.status=QLabel('编辑内容切换服务时保留；点击保存后生效。删除和清密钥需单独确认。');self.status.setWordWrap(True);layout.addWidget(self.status)
        form=QFormLayout();layout.addLayout(form)
        self.fields={}
        for key,title in [('name','服务名称'),('base_url','API基础地址（含 /v1）'),('model','模型名称'),('key','API密钥')]:
            w=QLineEdit();self.fields[key]=w
            if key=='key':w.setEchoMode(QLineEdit.EchoMode.Password);w.setPlaceholderText('留空保留；输入新密钥可替换')
            form.addRow(title,w)
        self.timeout=QSpinBox();self.timeout.setRange(5,600);form.addRow('超时（秒）',self.timeout)
        self.prompt=QPlainTextEdit();self.prompt.setPlainText(self.config.get('system_prompt',CHAT_DEFAULT['system_prompt']));form.addRow('角色系统提示词',self.prompt)
        self.count=QSpinBox();self.count.setRange(2,200);self.count.setValue(self.config.get('history_messages',40));form.addRow('历史消息上限',self.count)
        self.chars=QSpinBox();self.chars.setRange(1000,200000);self.chars.setSingleStep(1000);self.chars.setValue(self.config.get('history_chars',24000));form.addRow('历史字符上限',self.chars)
        note=QLabel('仅在你点击发送时请求此服务。Codex 会话不会自动发送。\n'+('密钥保存在当前 macOS 用户的系统钥匙串中。' if sys.platform=='darwin' else '密钥使用当前 Windows 用户的 DPAPI 加密保存。'));note.setWordWrap(True);note.setStyleSheet('font-size:10px;color:#706879;');layout.addWidget(note)
        row=QHBoxLayout();save=QPushButton('保存并设为当前服务');save.setProperty('role','primary');save.clicked.connect(self.save);row.addWidget(save)
        clear=QPushButton('清除此服务密钥');clear.setProperty('role','danger');clear.clicked.connect(self.clear_key);row.addWidget(clear);layout.addLayout(row)
        if embedded:
            back=QPushButton('返回聊天（保留未保存输入）');back.clicked.connect(self.reject);layout.addWidget(back)
        self.select.currentIndexChanged.connect(self.change);self.reload()
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        from PySide6.QtGui import QShortcut,QKeySequence
        self.save_shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Save),self);self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);self.save_shortcut.activated.connect(self.save)
    def reload(self):
        self.current=None
        self.select.blockSignals(True);self.select.clear()
        for p in self.config.get('providers',[]):self.select.addItem(p.get('name','未命名'),p['id'])
        idx=self.select.findData(self.config.get('active'));self.select.setCurrentIndex(max(0,idx));self.select.blockSignals(False);self.change()
    def change(self):
        self.confirmation.cancel()
        if self.current:self.drafts[self.current['id']]={**{key:w.text() for key,w in self.fields.items()},'timeout':self.timeout.value()}
        self.current=next((p for p in self.config.get('providers',[]) if p['id']==self.select.currentData()),None)
        values=self.drafts.get(self.current['id'],self.current) if self.current else {}
        for k,w in self.fields.items():w.setText(values.get(k,''))
        self.timeout.setValue(values.get('timeout',90))
    def add(self):
        if self.current:self.drafts[self.current['id']]={**{key:w.text() for key,w in self.fields.items()},'timeout':self.timeout.value()}
        self.config.setdefault('providers',[]).append(dict(id=uuid.uuid4().hex,name='新服务',base_url='',model='',timeout=90))
        self.config['active']=self.config['providers'][-1]['id'];self.reload()
    def remove(self):
        if not self.current:return
        key=self.current['id'];name=self.fields['name'].text().strip() or self.current.get('name','未命名服务')
        self.confirmation.request(f'删除服务“{name}”及其已保存的密钥？聊天记录会保留。',lambda:self.remove_confirmed(key))
    def remove_confirmed(self,key):
        candidate=copy.deepcopy(self.config);candidate['providers']=[p for p in candidate['providers'] if p['id']!=key]
        if candidate.get('active')==key:candidate['active']=candidate['providers'][0]['id'] if candidate['providers'] else ''
        try:atomic_json(self.path,candidate)
        except OSError:self.status.setText('服务删除失败，原配置已保留。');return
        self.config=candidate;self.drafts.pop(key,None);self.reload()
        try:self.secrets.put(key,'');self.status.setText('服务及密钥已删除；聊天记录保留。')
        except OSError:self.status.setText('服务已删除，但密钥清理失败；请检查用户目录权限。')
    def clear_key(self):
        if not self.current:return
        key=self.current['id'];name=self.fields['name'].text().strip() or self.current.get('name','未命名服务')
        self.confirmation.request(f'清除服务“{name}”的密钥？下次发送前需要重新填写。',lambda:self.clear_key_confirmed(key),'确认清除密钥')
    def clear_key_confirmed(self,key):
        try:self.secrets.put(key,'')
        except OSError:self.status.setText('密钥清除失败，请检查用户目录权限。');return
        if key in self.drafts:self.drafts[key]['key']=''
        if self.current and self.current['id']==key:self.fields['key'].clear();self.fields['key'].setPlaceholderText('已清除密钥，请重新填写')
        self.status.setText('密钥已清除，其他输入尚未保存。')
    def reject(self):
        self.confirmation.cancel();super().reject()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and self.confirmation.callback is not None:
            self.confirmation.cancel();event.accept();return
        super().keyPressEvent(event)
    def save(self):
        entered={key:w.text().strip() for key,w in self.fields.items()};timeout=self.timeout.value()
        if not self.current:
            self.add()
            for key,value in entered.items():self.fields[key].setText(value)
            self.timeout.setValue(timeout)
        candidate=copy.deepcopy(self.config)
        current=next(p for p in candidate['providers'] if p['id']==self.current['id'])
        current.update({key:value for key,value in entered.items() if key!='key'},timeout=timeout)
        try:
            if entered['key']:self.secrets.put(current['id'],entered['key'])
            candidate.update(active=current['id'],system_prompt=self.prompt.toPlainText(),history_messages=self.count.value(),history_chars=self.chars.value())
            atomic_json(self.path,candidate);self.config=candidate;self.drafts.pop(current['id'],None);self.reload();self.accept()
        except OSError:self.status.setText('服务配置保存失败；输入已保留，可检查用户目录权限后重试。')

class ChatInput(QPlainTextEdit):
    send=Signal()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not event.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            self.send.emit();event.accept()
        else:super().keyPressEvent(event)

class ChatWindow(QWidget):
    def __init__(self,pet,root,embedded=False):
        super().__init__(pet,Qt.WindowType.Widget if embedded else Qt.WindowType.Window);self.pet=pet;self.embedded=embedded;self.root=Path(root);self.character=str(pet.settings.get('character','builtin'))
        self.store=SessionStore(root,self.character);self.session=self.store.sessions[0] if self.store.sessions else self.store.new()
        self.stream=None;self.partial='';self.busy=False;self.provider_dialog=None
        self._stream_pending=[];self._rendered_text='';self._rendered_session=None
        self.stream_timer=QTimer(self);self.stream_timer.setSingleShot(True);self.stream_timer.setInterval(33);self.stream_timer.timeout.connect(self.flush_stream)
        self.setWindowTitle('和白龙聊天');self.resize(580,650)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);self.pages=QStackedWidget();outer.addWidget(self.pages)
        self.chat_body=QWidget();self.pages.addWidget(self.chat_body);layout=QVBoxLayout(self.chat_body)
        row=QHBoxLayout();self.sessions=QComboBox();row.addWidget(self.sessions,1)
        for title,slot in [('新建',self.new),('聊天服务',self.provider)]:
            b=QPushButton(title);b.clicked.connect(slot);row.addWidget(b)
        manage=QPushButton('管理');menu=QMenu(manage)
        for title,slot in [('清空当前会话…',self.clear),('删除当前会话…',self.delete)]:
            menu.addAction(title,lambda checked=False,s=slot:QTimer.singleShot(0,self,s))
        manage.setMenu(menu);row.addWidget(manage)
        layout.addLayout(row);self.sessions.currentIndexChanged.connect(self.switch)
        self.confirmation=InlineConfirmation();layout.addWidget(self.confirmation)
        self.transcript=QPlainTextEdit();self.transcript.setReadOnly(True);layout.addWidget(self.transcript,1)
        self.status=QLabel('这里是与白龙的对话；Codex 进度可切换到状态页查看。');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.input=ChatInput();self.input.setMaximumHeight(110);self.input.setPlaceholderText('Enter 发送，Shift+Enter 换行');self.input.send.connect(self.send);layout.addWidget(self.input)
        row=QHBoxLayout();self.send_button=QPushButton('发送');self.send_button.setProperty('role','primary');self.send_button.clicked.connect(self.send);row.addWidget(self.send_button)
        self.stop_button=QPushButton('停止');self.stop_button.clicked.connect(self.stop);row.addWidget(self.stop_button)
        self.retry_button=QPushButton('重试上条');self.retry_button.clicked.connect(self.retry);row.addWidget(self.retry_button)
        self.follow=QCheckBox('跟随桌宠');self.follow.setChecked(pet.settings.get('chat_follow',False));self.follow.toggled.connect(self.save_follow);row.addWidget(self.follow);layout.addLayout(row)
        if embedded:self.follow.hide()
        self.reload();self.follow_timer=QTimer(self);self.follow_timer.timeout.connect(self.follow_pet)
        if not embedded:self.follow_timer.start(250)
    def save_follow(self,value):self.pet.settings['chat_follow']=value;self.pet.save_settings()
    def follow_pet(self):
        if not self.isVisible() or self.isMinimized() or not self.follow.isChecked():return
        screen=__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.screenAt(self.pet.frameGeometry().center())
        if not screen:return
        a=screen.availableGeometry();x=self.pet.x()-self.width()-12
        if x<a.left():x=self.pet.x()+self.pet.width()+12
        self.move(max(a.left(),min(x,a.right()-self.width()+1)),max(a.top(),min(self.pet.y(),a.bottom()-self.height()+1)))
    def reload(self):
        self.sessions.blockSignals(True);self.sessions.clear()
        for s in self.store.sessions:self.sessions.addItem(s['title'],s['id'])
        self.sessions.setCurrentIndex(self.sessions.findData(self.session['id']));self.sessions.blockSignals(False);self.render()
    def _replace_text(self,text):
        from performance_metrics import METRICS
        with METRICS.span('chat_document_update'):
            bar=self.transcript.verticalScrollBar();at_end=bar.value()>=bar.maximum()-10;scroll=bar.value()
            # An independent end cursor leaves the user's selection untouched.
            if self._rendered_session==self.session['id'] and text.startswith(self._rendered_text):
                suffix=text[len(self._rendered_text):]
                if suffix:
                    cursor=QTextCursor(self.transcript.document());cursor.movePosition(QTextCursor.MoveOperation.End);cursor.insertText(suffix)
                    METRICS.add('chat_append',bytes_read=len(suffix.encode('utf-8')))
            elif text!=self._rendered_text or self._rendered_session!=self.session['id']:
                self.transcript.setPlainText(text);METRICS.add('chat_full_reset')
            self._rendered_text=text;self._rendered_session=self.session['id']
            bar.setValue(bar.maximum() if at_end else scroll)
    def render(self):
        self.stream_timer.stop();self._stream_pending.clear()
        text='\n\n'.join(('我' if m['role']=='user' else '白龙')+'：\n'+m['content'] for m in self.session['messages'])
        if self.busy:text+='\n\n白龙：\n'+self.partial
        self._replace_text(text)
        self.send_button.setEnabled(not self.busy);self.retry_button.setEnabled(not self.busy);self.stop_button.setEnabled(self.busy)
    def flush_stream(self):
        self.stream_timer.stop()
        if not self._stream_pending:return
        suffix=''.join(self._stream_pending);self._stream_pending.clear()
        if self.busy:self._replace_text(self._rendered_text+suffix)
    def switch(self):
        self.confirmation.cancel()
        if self.busy:self.stop()
        selected=next((s for s in self.store.sessions if s['id']==self.sessions.currentData()),None)
        if selected:self.session=selected;self.render()
    def new(self):self.confirmation.cancel();self.stop();self.session=self.store.new();self.reload()
    def clear(self):
        key=self.session['id'];name=self.session['title']
        self.confirmation.request(f'清空会话“{name}”的全部消息？会保留会话；正在生成的回复也将停止，此操作不可撤销。',lambda:self.clear_confirmed(key),'确认清空')
    def clear_confirmed(self,key):
        if self.session['id']!=key:return
        self.stop();messages=self.session['messages'];self.session['messages']=[]
        try:self.store.save();self.status.setText('当前会话消息已清空。')
        except OSError:self.session['messages']=messages;self.status.setText('清空失败，原消息已保留。')
        self.render()
    def delete(self):
        key=self.session['id'];name=self.session['title']
        self.confirmation.request(f'删除整个会话“{name}”及其消息？正在生成的回复也将停止，此操作不可撤销。',lambda:self.delete_confirmed(key))
    def delete_confirmed(self,key):
        if self.session['id']!=key:return
        self.stop();previous=self.store.sessions;remaining=[s for s in previous if s['id']!=key]
        if not remaining:remaining=[dict(id=uuid.uuid4().hex,title='新对话',messages=[],at=time.time())]
        self.store.sessions=remaining
        try:self.store.save()
        except OSError:self.store.sessions=previous;self.status.setText('删除失败，原会话已保留。');return
        self.session=remaining[0];self.reload();self.status.setText('会话已删除。')
    def provider(self):
        self.confirmation.cancel()
        if self.embedded:
            if not self.provider_dialog:
                self.provider_dialog=ProviderDialog(self.root,self,embedded=True)
                self.provider_page=QScrollArea();self.provider_page.setWidgetResizable(True);self.provider_page.setWidget(self.provider_dialog)
                self.pages.addWidget(self.provider_page)
                self.provider_dialog.finished.connect(lambda result:self.pages.setCurrentWidget(self.chat_body))
            self.pages.setCurrentWidget(self.provider_page);self.provider_dialog.show();return
        if self.provider_dialog and self.provider_dialog.isVisible():self.provider_dialog.raise_();return
        self.provider_dialog=ProviderDialog(self.root,self);self.provider_dialog.show()
    def send(self):
        self.confirmation.cancel()
        if self.busy:return
        text=self.input.toPlainText().strip()
        if not text:return
        if len(text)>50000:self.status.setText('单条消息请控制在50000字以内。');return
        self.start(text,False)
    def retry(self):
        if self.busy:return
        messages=copy.deepcopy(self.session['messages'])
        if messages and messages[-1]['role']=='assistant':messages.pop()
        if messages and messages[-1]['role']=='user':self.start(messages[-1]['content'],True)
    def start(self,text,retry):
        config=load_json(self.root/'chat.json',CHAT_DEFAULT)
        provider=next((p for p in config.get('providers',[]) if p['id']==config.get('active')),None)
        if not provider:self.status.setText('请先在“模型服务”中配置接口地址、模型和密钥。');self.provider();return
        try:key=SecretStore(self.root/'credentials.dpapi.json').get(provider['id'])
        except OSError:self.status.setText('无法解密密钥，请在模型服务中重新保存。');return
        messages=copy.deepcopy(self.session['messages'])
        if retry and messages and messages[-1]['role']=='assistant':messages.pop()
        if not retry:messages.append(dict(role='user',content=text))
        prompt=self.pet.manifest.get('systemPrompt') or config.get('system_prompt',CHAT_DEFAULT['system_prompt'])
        payload=[dict(role='system',content=prompt)]+trim_messages(messages,config.get('history_messages',40),config.get('history_chars',24000))
        stream=ChatStream(self);self.stream=stream;self.partial='';self.busy=True
        stream.delta.connect(lambda value:self.on_delta(stream,value));stream.done.connect(lambda value:self.on_done(stream,value))
        stream.failed.connect(lambda message:self.on_error(stream,message))
        try:stream.start(provider,key,payload)
        except (ValueError,OSError) as error:
            self.busy=False;stream.deleteLater();self.stream=None;self.status.setText(str(error));self.render();return
        self.session['messages']=messages;self.session['title']=text[:24];self.store.save();self.input.clear()
        self.status.setText('白龙正在回复…');self.reload()
    def on_delta(self,stream,value):
        if stream is self.stream and self.busy:
            self.partial+=value;self._stream_pending.append(value)
            if not self.stream_timer.isActive():self.stream_timer.start()
    def on_done(self,stream,value):
        if stream is not self.stream or not self.busy:return
        self.flush_stream()
        if value:self.session['messages'].append(dict(role='assistant',content=value))
        self.store.save();self.busy=False;self.stream=None;stream.deleteLater();self.status.setText('回复完成');self.render()
    def on_error(self,stream,message):
        if stream is not self.stream or not self.busy:return
        self.busy=False;self.stream=None;stream.deleteLater();self.status.setText(message+'；上条消息已保留，可重试。');self.render()
    def stop(self):
        self.stream_timer.stop();self._stream_pending.clear()
        if self.stream:
            stream=self.stream;self.stream=None;self.busy=False;stream.cancel();stream.deleteLater()
            self.status.setText('已停止；未完成回复没有加入历史。')
        self.partial='';self.render()
    def closeEvent(self,event):self.stop();self.hide();event.ignore()
    def keyPressEvent(self,event):
        if self.embedded and event.key()==Qt.Key.Key_Escape:
            if self.confirmation.callback is not None:self.confirmation.cancel()
            elif self.provider_dialog and self.pages.currentWidget() is self.provider_page:self.provider_dialog.reject()
            else:self.pet.bubble.return_to_status()
            event.accept();return
        super().keyPressEvent(event)
    def shutdown(self):self.stop();self.follow_timer.stop();self.hide()
