"""Compact session identifiers for a fixed-width capsule text area."""
import re

def short_session_name(title,source=''):
    text=re.sub(r'\s+',' ',str(title or '')).strip()
    prefix='['+str(source)+']'
    if source and text.casefold().startswith(prefix.casefold()):text=text[len(prefix):].strip()
    marker=re.search(r'(?i)(?<![A-Za-z0-9_-])(jsc[-_]\d+)(?![A-Za-z0-9_-])',text)
    if marker:return marker.group(1)
    return text or '会话'

def capsule_columns(width,metrics,names,statuses,extra,count_metrics=None):
    """Reserve status/count first, then protect short names before source text."""
    count_metrics=count_metrics or metrics
    count_width=count_metrics.horizontalAdvance('+'+str(extra))+1 if extra else 0
    status_width=max((metrics.horizontalAdvance(s) for s in statuses),default=22)+1
    gap=2;count_gap=2 if extra else 0
    # QFontMetrics rounds advances; leave room for the elider's fractional width.
    name_wanted=max((min(metrics.horizontalAdvance(n)+2,52 if re.fullmatch(r'(?i)jsc[-_]\d+',n) else 30) for n in names),default=22)
    source_width=max(14,min(41,width-name_wanted-status_width-count_width-2*gap-count_gap))
    name_width=max(1,width-source_width-status_width-count_width-2*gap-count_gap)
    name_x=source_width+gap;status_x=name_x+name_width+gap
    return dict(source_width=source_width,name_x=name_x,name_width=name_width,status_x=status_x,status_width=status_width,count_x=status_x+status_width+count_gap,count_width=count_width)
