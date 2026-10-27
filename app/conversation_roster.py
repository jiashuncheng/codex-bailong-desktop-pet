"""Two stable conversation slots; unread completion plus active work first."""
from session_read_state import session_id
import re
LABELS={'thinking':'思考中','working':'执行中','responding':'回复中','waiting':'待操作','complete':'已完成','interrupted':'已中断'}
ACTIVE={'thinking','working','responding','waiting'}

def title_keywords(title):
    text=re.sub(r'\s+',' ',str(title)).strip()
    text=re.sub(r'^(?:(?:请问|请|帮我|麻烦|我们现在|我们|我想要|我想|能不能|可以|继续|关于|给我|帮忙)\s*)+','',text)
    text=re.sub(r'^(?:做一个|制作一个|实现一个|修改一下|优化一下|看看|看一下)\s*','',text)
    return re.split(r'[，。！？\n]',text,maxsplit=1)[0].strip(' ：:') or str(title)

class ConversationRoster:
    def __init__(self):self.items={};self.serial=0;self.page=0;self.pinned=[];self.names={};self.sources={};self.pending=set();self.rotating=None;self.next_slot=0;self.cursor=None;self.candidates=[]
    def update_names(self,names):
        changed=False
        for sid,title in names.items():
            sid=session_id(sid)
            if not title:continue
            if self.names.get(sid)!=title:changed=True
            self.names[sid]=title
            if sid in self.items and self.items[sid]['title']!=title:self.items[sid]['title']=title;changed=True
        # Only tracked sessions are supplied; bound retained metadata as well.
        disposable=[sid for sid in self.names if sid not in self.items and sid not in self.pending]
        for sid in disposable[:-256]:self.names.pop(sid,None)
        return changed
    def update_sources(self,sources):
        changed=False
        for sid,info in sources.items():
            sid=session_id(sid)
            if not sid or not isinstance(info,dict) or info.get('source_kind') not in ('local','terminal','wsl','ssh'):continue
            value=dict(source_kind=info['source_kind'],source_label=str(info.get('source_label') or '未知')[:64])
            if self.sources.get(sid)!=value:changed=True
            self.sources[sid]=value
            if sid in self.items:self.items[sid].update(value)
        disposable=[sid for sid in self.sources if sid not in self.items and sid not in self.pending]
        for sid in disposable[:-256]:self.sources.pop(sid,None)
        return changed
    def observe(self,event):
        sid=session_id(event.get('session',''))
        if not sid:return
        self.serial+=1;old=self.items.get(sid,{})
        state='complete' if event.get('kind')=='complete' else event.get('state','idle')
        start=old.get('start',self.serial) if old.get('state') in ACTIVE else self.serial
        detail=event.get('display') or {'thinking':'正在思考','working':'正在处理任务','responding':'正在整理回复','waiting':'等待你的操作','complete':'任务已完成','interrupted':'任务已中断'}.get(state,'等待新任务')
        self.items[sid]=dict(session=sid,state=state,source_kind=event.get('source_kind') or self.sources.get(sid,{}).get('source_kind') or old.get('source_kind','unknown'),source_label=event.get('source_label') or self.sources.get(sid,{}).get('source_label') or old.get('source_label','未知'),compacting=bool(event.get('compacting')),waiting_reason=event.get('waiting_reason','') if state=='waiting' else '',title=self.names.get(sid) or event.get('conversation_name') or event.get('title') or old.get('title') or '会话 '+sid[-4:],text=detail,turn=event.get('turn',''),start=start,updated=self.serial)
        if state in ('complete','waiting') and (old.get('state')!=state or old.get('turn')!=event.get('turn','')):
            self.page=0;self.rotating=None;self.next_slot=0;self.cursor=None
        # Bound old in-memory details; pending IDs remain available separately.
        disposable=sorted((s for s,v in self.items.items() if v['state'] not in ACTIVE and s not in self.pending),key=lambda s:self.items[s]['updated'],reverse=True)
        for sid in disposable[64:]:self.items.pop(sid,None)
    def selection(self,unread):
        pending=list(dict.fromkeys(session_id(s) for s,t in reversed(unread)))
        # An older completion must not replace this session's new running turn.
        pending=[sid for sid in pending if not (self.items.get(sid,{}).get('state') in ACTIVE and self.items[sid].get('turn') and all(t!=self.items[sid]['turn'] for s,t in unread if session_id(s)==sid))]
        if set(pending)-self.pending:
            self.page=0;self.rotating=None;self.next_slot=0;self.cursor=None
        self.pending=set(pending)
        done=[dict(self.items.get(sid,dict(session=sid,title=self.names.get(sid) or '会话 '+sid[-4:],text='',**self.sources.get(sid,{}))),state='complete') for sid in pending]
        active=sorted([v for v in self.items.values() if v['state'] in ACTIVE and v['session'] not in pending],key=lambda v:(v['state']!='waiting',v['start'],v['session']))
        waiting=[v for v in active if v['state']=='waiting']
        pool=done+active
        self.candidates=[v['session'] for v in pool]
        if self.rotating is not None:
            lookup={v['session']:v for v in pool}
            slots=[sid if sid in lookup else None for sid in self.rotating]
            available=iter(sid for sid in self.candidates if sid not in slots)
            slots=[sid if sid is not None else next(available,None) for sid in slots]
            slots=[sid for sid in slots if sid is not None]
            for sid in available:
                if len(slots)>=2:break
                slots.append(sid)
            self.rotating=slots;chosen=[lookup[sid] for sid in slots]
        elif self.page and pool:
            start=(self.page*2)%len(pool);chosen=(pool+pool)[start:start+min(2,len(pool))]
        elif done and active:
            keep=waiting[0] if waiting else next((v for sid in self.pinned for v in active if v['session']==sid),active[0]);chosen=[done[0],keep]
        elif active:
            kept=[v for sid in self.pinned for v in active if v['session']==sid and v not in waiting]
            chosen=(waiting+kept+[v for v in active if v not in kept and v not in waiting])[:2]
        else:chosen=done[:2]
        if not self.page or self.rotating is not None:self.pinned=[v['session'] for v in chosen]
        return chosen,max(0,len(pool)-len(chosen))
    def rotate_one(self,unread):
        chosen,_=self.selection(unread)
        slots=[v['session'] for v in chosen]
        if len(self.candidates)<=len(slots):return False
        if self.rotating is None:
            self.next_slot=0;self.cursor=slots[-1] if slots else None
        start=self.candidates.index(self.cursor)+1 if self.cursor in self.candidates else 0
        incoming=next(self.candidates[(start+offset)%len(self.candidates)]
                      for offset in range(len(self.candidates))
                      if self.candidates[(start+offset)%len(self.candidates)] not in slots)
        slot=self.next_slot%len(slots)
        slots[slot]=incoming
        self.rotating=slots;self.next_slot=(slot+1)%len(slots);self.cursor=incoming;self.page+=1
        return True
    def cycle(self,direction=1):
        self.rotating=None;self.next_slot=0;self.cursor=None;self.page+=direction
