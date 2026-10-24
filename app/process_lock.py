"""Small per-user file locks for source launchers and the SSH worker."""
from contextlib import contextmanager
import os
import time

@contextmanager
def process_lock(path,blocking=True):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            handle.seek(0,2)
            if not handle.tell():handle.write(b'0');handle.flush()
            deadline=time.monotonic()+45
            while True:
                try:
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if not blocking:raise BlockingIOError('进程已在运行') from None
                    if time.monotonic()>deadline:raise RuntimeError('另一个启动操作仍在进行，请稍后重试。')
                    time.sleep(.1)
            try:yield
            finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
            try:yield
            finally:fcntl.flock(handle,fcntl.LOCK_UN)
