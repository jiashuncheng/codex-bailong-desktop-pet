"""Desktop configuration, action arbitration and bounded physics (no Qt)."""
import copy
import json
import math
import os
import time
from pathlib import Path

from version import VERSION
DEFAULTS=dict(schema=2,scale=1.0,playback_speed=1.0,action_gap=2.0,
    random_interval=25.0,move_speed=55.0,move_range=0.75,drag_physics=True,
    on_top=True,video_fullscreen_yield=True,no_move=False,mouse_through=False,wandering=True,random_actions=True,
    commentary=True,sound=True,bubble=True,quota_visible=True,self_talk=False,character_visible=True,card_anchor=None,
    conversation_auto_scroll=True,conversation_scroll_seconds=6.,status_actions=True,status_action_interval=12.,status_response_revision=2,update_checks=True,token_chart_range='all',bubble_mode='auto',
    capsule_action='chatgpt',capsule_website='',talk_min=30.0,talk_max=90.0,talk_quiet=True,
    talk_lines=['忙完记得休息一下。','我在这里陪着你。','今天也一起把小事做好吧。'],
    facing=1,character='builtin',character_preferences={},chat_follow=False)

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)

def normalized(raw):
    out=copy.deepcopy(DEFAULTS);out.update(raw if isinstance(raw,dict) else {})
    # Upgrade only the previous default; retain deliberate nondefault tuning.
    if isinstance(raw,dict) and raw.get('status_response_revision',0)!=2 and raw.get('status_action_interval')==18:
        out['status_action_interval']=12.
    out['status_response_revision']=2
    for k,lo,hi in [('scale',.4,2.5),('playback_speed',.25,3),('action_gap',0,60),
        ('random_interval',3,600),('move_speed',10,300),('move_range',.1,1),
        ('talk_min',5,3600),('talk_max',5,7200),('status_action_interval',8,120),('conversation_scroll_seconds',2,120)]:
        try:v=float(out[k]);out[k]=min(hi,max(lo,v)) if math.isfinite(v) else DEFAULTS[k]
        except (TypeError,ValueError):out[k]=DEFAULTS[k]
    for k,v in DEFAULTS.items():
        if isinstance(v,bool):out[k]=out[k] if isinstance(out[k],bool) else v
    out['talk_max']=max(out['talk_min'],out['talk_max'])
    out['talk_lines']=[str(s)[:500] for s in out['talk_lines'][:200]] if isinstance(out['talk_lines'],list) else DEFAULTS['talk_lines'][:]
    out['facing']=-1 if out['facing']==-1 else 1
    if out['token_chart_range'] not in ('all','30d','7d','day'):out['token_chart_range']='all'
    if out['bubble_mode'] not in ('auto','mini','minimal'):out['bubble_mode']='auto'
    from quick_actions import action_info
    out['capsule_action']=action_info(out['capsule_action'])[0]
    out['capsule_website']=str(out['capsule_website'] or '')[:2048]
    if out['capsule_action']=='website':
        from quick_actions import website_url
        try:out['capsule_website']=website_url(out['capsule_website'])
        except ValueError:out['capsule_action']='chatgpt'
    if not isinstance(out['character_preferences'],dict):out['character_preferences']={}
    out['schema']=2
    return out

PRIORITY={'idle':0,'turn':1,'walk':1,'variant':2,'reaction':2,'click':5,'quota':5,'task':7,'landing':8,'throw':9,'drag':10}
class ActionGate:
    def __init__(self):self.state='idle';self.pending=None
    def request(self,state,item=None,force=False):
        if force or PRIORITY.get(state,2)>=PRIORITY.get(self.state,2):
            self.state=state;return True
        if state=='task':self.pending=(state,item)
        return False
    def finish(self):
        pending=self.pending;self.pending=None;self.state='idle';return pending

def physics_step(x,y,vx,vy,dt,bounds):
    dt=min(.05,max(0,dt));left,top,right,bottom=bounds
    x+=vx*dt;y+=vy*dt
    if x<left:x=left;vx=abs(vx)*.45
    if x>right:x=right;vx=-abs(vx)*.45
    if y<top:y=top;vy=abs(vy)*.45
    if y>bottom:y=bottom;vy=-abs(vy)*.45
    drag=math.exp(-3.8*dt);vx*=drag;vy*=drag
    return x,y,vx,vy,math.hypot(vx,vy)<15

def relative_position(x,y,w,h,area,name):
    left,top,aw,ah=area
    return dict(screen=name,rx=max(0,min(1,(x-left)/max(1,aw-w))),ry=max(0,min(1,(y-top)/max(1,ah-h))))

def restore_position(saved,w,h,area):
    left,top,aw,ah=area
    return round(left+max(0,aw-w)*max(0,min(1,float(saved.get('rx',.85))))),round(top+max(0,ah-h)*max(0,min(1,float(saved.get('ry',.85)))))
