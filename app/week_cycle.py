"""Align local Token totals with the currently observed weekly quota cycle."""
import math
import time
from datetime import datetime

WEEK=7*24*3600


def context(windows,evidence,observed,source):
    """Prefer an observed refill; otherwise infer the start from the weekly deadline."""
    if source!='live' or not isinstance(observed,(int,float)) or not math.isfinite(observed):return None
    week=next((w for w in windows if isinstance(w,dict) and w.get('name')=='一周'),None)
    if not week:return None
    from reset_watch import epoch
    deadline=epoch(week.get('resetsAt'))
    remaining=week.get('remaining')
    if (deadline is None or not observed<deadline<=observed+WEEK+300 or
            isinstance(remaining,bool) or not isinstance(remaining,(int,float)) or
            not math.isfinite(remaining) or not 0<=remaining<=100):return None
    inferred=deadline-WEEK
    event=(evidence or {}).get('reset')
    detected=(isinstance(event,dict) and event.get('window')=='一周' and
        isinstance(event.get('observed'),(int,float)) and not isinstance(event.get('observed'),bool) and
        inferred-300<=event['observed']<=observed and event['observed']<deadline)
    start=max(inferred,float(event['observed'])) if detected else inferred
    if not start<=observed:return None
    return dict(start=start,through=observed,remaining=float(remaining),
        reset_at=deadline,start_source='detected' if detected else 'inferred',
        reset_kind=event.get('kind','') if detected else 'natural',plan=week.get('plan',''))


def usage(db,cycle):
    """Bounded indexed read; exclude usage after the quota observation."""
    return db.execute(
        'SELECT COALESCE(SUM(tokens),0),COUNT(*) FROM usage WHERE stamp>=? AND stamp<=?',
        (cycle['start'],cycle['through'])).fetchone()


def summarize(cycle,used,records,complete,now=None):
    """The denominator is account quota, while the numerator is local logs."""
    if not cycle:return None
    now=time.time() if now is None else now
    used=max(0,int(used or 0));spent=100-cycle['remaining']
    fresh=0<=now-cycle['through']<=900
    can_estimate=bool(complete and fresh and records and used>0 and spent>=5)
    estimate=round(used*100/spent) if can_estimate else None
    return dict(start=cycle['start'],through=cycle['through'],reset_at=cycle['reset_at'],
        start_source=cycle['start_source'],remaining=cycle['remaining'],used=used,
        estimated_total=estimate,complete=bool(complete),fresh=fresh,records=records)


def interval_text(stamp):
    try:return datetime.fromtimestamp(stamp).strftime('%m/%d %H:%M')
    except (ValueError,OSError,OverflowError,TypeError):return '--'
