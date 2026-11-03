"""Owned decoder lifecycle and aggregate counters; no GUI-thread joins."""
import threading,time,weakref

def display_decode_size(scale,dpr):
    """Decode for the intended physical canvas, independent of transient HWND size."""
    import math
    try:scale=float(scale);dpr=float(dpr)
    except (TypeError,ValueError):scale=dpr=1.
    if not math.isfinite(scale) or scale<=0:scale=1.
    if not math.isfinite(dpr) or dpr<=0:dpr=1.
    return min(720,max(128,round(256*scale*dpr)))

class DecodeStats:
    def __init__(self):self.lock=threading.Lock();self.values={};self.workers=weakref.WeakSet()
    def add(self,key,n=1):
        with self.lock:self.values[key]=self.values.get(key,0)+n
    def snapshot(self):
        with self.lock:return dict(self.values,active_workers=sum(t.is_alive() for t in self.workers))
    def start(self,target,name):
        thread=threading.Thread(target=target,name=name,daemon=True)
        with self.lock:self.workers.add(thread)
        thread.start();return thread
    def drain(self,timeout=3):
        """Test/shutdown tooling only; playback never waits for worker termination."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            with self.lock:workers=[t for t in self.workers if t.is_alive()]
            if not workers:return True
            for t in workers:t.join(min(.02,max(0,deadline-time.monotonic())))
        return False
STATS=DecodeStats()

def opened(path):
    STATS.add('image_opens')
    try:STATS.add('encoded_bytes_opened',path.stat().st_size)
    except OSError:pass
