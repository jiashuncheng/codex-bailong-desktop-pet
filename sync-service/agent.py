#!/usr/bin/env python3
"""Headless Linux/macOS/Windows collector; only Python's standard library."""
import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from token_sync import sync_once,atomic


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',type=Path,required=True);parser.add_argument('--home',type=Path,default=Path.home()/'.codex');parser.add_argument('--interval',type=int,default=30);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();stop=threading.Event()
    for kind in (signal.SIGINT,signal.SIGTERM):signal.signal(kind,lambda *_:stop.set())
    while not stop.is_set():
        snapshot=None
        try:
            snapshot=sync_once(args.state,args.home,stop.is_set)
            if snapshot:print(json.dumps(dict(connected=True,total=snapshot['all_total'],more=snapshot['sync_more'])),flush=True)
        except Exception:
            atomic(args.state/'token-sync-status.json',dict(connected=False,checked=time.time(),error='同步暂不可用，稍后重试。'))
            print('Token synchronization temporarily unavailable; retrying.',flush=True)
            if args.once:return 1
        if args.once:return 0
        stop.wait(2 if snapshot and snapshot.get('sync_more') else max(15,args.interval))
    return 0

if __name__=='__main__':raise SystemExit(main())
