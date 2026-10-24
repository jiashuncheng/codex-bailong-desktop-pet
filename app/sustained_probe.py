"""Isolated real-clock acceptance; synthetic events, original production assets."""
import json,time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

def run(destination):
    from desktop import DesktopPet
    from desktop_core import VERSION
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    pet=DesktopPet(monitor=False);pet.apply_settings(dict(wandering=False,random_actions=False,self_talk=False,video_fullscreen_yield=False,update_checks=False))
    pet.notify=lambda *args:None;pet.refresh_quota=lambda *args:None
    pet.show();started=time.monotonic();records=[];checks={};stage=0;last=None;maximum_queue=0;maximum_cache=0;last_sample=started;maximum_gap=0.;transient_started=0.;cycles_before_transient=0
    def status(state,activity=''):
        pet.on_activity(dict(kind='status',session='probe-main',turn='probe-turn',state=state,activity=activity,text='验收状态',active=1))
    status('thinking')
    def finish(error=None):
        timer.stop();pet.sustained.cancel();pet.record_state()
        result=dict(version=VERSION,passed=error is None and all(checks.values()),error=error,checks=checks,seconds=round(time.monotonic()-started,3),records=records,
                    maximumQueue=maximum_queue,queueLimit=6,maximumCacheBytes=maximum_cache,cacheLimit=pet.player.loop_cache.limit,maximumEventLoopGap=round(maximum_gap,4),realClock=True,syntheticEvents=True,
                    physicalDisplayFrameRateMeasured=False)
        Path(destination).parent.mkdir(parents=True,exist_ok=True);Path(destination).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        pet.close();app.exit(0 if result['passed'] else 1)
    def sample():
        nonlocal stage,last,maximum_queue,maximum_cache,last_sample,maximum_gap,transient_started,cycles_before_transient
        try:
            now=time.monotonic();elapsed=now-started;s=pet.sustained
            maximum_gap=max(maximum_gap,now-last_sample);last_sample=now
            maximum_queue=max(maximum_queue,pet.player.frames.qsize());maximum_cache=max(maximum_cache,pet.player.loop_cache.stats()['bytes'])
            phase=(pet.current['id'],s.phase,s.cycles,pet.mode)
            if phase!=last:
                records.append(dict(at=round(elapsed,3),action=phase[0],phase=phase[1],cycles=phase[2],mode=phase[3],frame=pet.player.frame_index,variant=s.variant_index,rangeStart=s.variant['start'] if s.variant else None,cycleSpeed=round(s.cycle_speed,4)));last=phase
            if elapsed>62:finish('timeout');return
            if stage<3:pet.reactions.confirm('probe-main','probe-turn',True,now)
            if stage==0 and s.active and s.cycles>=3:
                checks['thinkingRepeatsWithoutIdle']=s.owner.action_id=='work04'
                # High frequency updates retain the same semantic target.
                for _ in range(50):status('thinking')
                checks['burstPreservesPhase']=s.active and s.cycles>=3
                stage=1;status('working','execute')
            elif stage==1 and s.active and s.owner.action_id=='work02' and s.cycles>=3:
                checks['workingEnteredAfterNaturalThinkingTail']=any(r['action']=='work04' and r['phase']=='exit' for r in records)
                checks['workingRepeatsWithoutIdle']=True;stage=2;transient_started=now;cycles_before_transient=s.cycles
                status('thinking')
            elif stage==2 and now-transient_started>=2.:
                checks['shortSemanticChangeKeepsLaptop']=bool(s.active and s.owner.action_id=='work02' and s.phase!='exit' and s.cycles>=cycles_before_transient)
                status('working','execute');stage=3
                pet.on_activity(dict(kind='complete',session='probe-main',turn='probe-turn',title='验收完成'))
                checks['completionIconImmediate']=bool(pet.bubble.status_indicator.unread)
                checks['completionDoesNotCutBody']=s.active and pet.mode=='reaction'
            elif stage==3 and pet.mode=='task':
                checks['workingOriginalTailBeforeCelebration']=any(r['action']=='work02' and r['phase']=='exit' for r in records)
                checks['celebrationAfterTail']=pet.current['id']=='18'
                checks['boundedQueue']=maximum_queue<=6;checks['boundedCache']=maximum_cache<=pet.player.loop_cache.limit
                checks['decoderHealthy']=pet.decode_error is None
                # All middle body repeats are forward ranges, never entrance.
                from sustained_assets import profile_paths
                profiles={i['id']:profile_paths(pet.asset_root,i) for i in pet.manifest['workAnimations'] if i.get('sustained')}
                checks['repeatRangesDoNotReplayEntrance']=all(r['rangeStart']<=r['frame']<=profiles[r['action']]['end'] for r in records if r['phase']=='body') and all(sum(r['action']==key and r['phase']=='enter' for r in records)==1 for key in profiles)
                checks['authoredSteadyRangesOnly']=all(
                    {r['rangeStart'] for r in records if r['action']==key and r['phase']=='body'}=={profile['start']}
                    and all(r['cycleSpeed']==1. for r in records if r['action']==key and r['phase']=='body')
                    for key,profile in profiles.items() if profile.get('steadyProp'))
                finish();return
        except Exception as error:finish(type(error).__name__+': '+str(error))
    timer=QTimer();timer.timeout.connect(sample);timer.start(16)
    return app.exec()
