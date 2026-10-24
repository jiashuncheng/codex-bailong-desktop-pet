"""Authenticated loopback API behind a TLS reverse proxy; Python 3.10+."""
import argparse
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from token_calendar import TokenUsageIndex


def digest(value):return hashlib.sha256(value.encode()).hexdigest()

class SyncStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db,db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,name TEXT,token_hash TEXT UNIQUE,last_seen REAL);
            CREATE TABLE IF NOT EXISTS invites(hash TEXT PRIMARY KEY,expires REAL,used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS raw(session TEXT,total INTEGER,stamp REAL,model TEXT,input INTEGER,output INTEGER,device TEXT,PRIMARY KEY(session,total));
            CREATE TABLE IF NOT EXISTS usage(fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER,session TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,known INTEGER);
            CREATE INDEX IF NOT EXISTS usage_stamp ON usage(stamp);
            CREATE INDEX IF NOT EXISTS usage_session ON usage(session);
            CREATE TABLE IF NOT EXISTS messages(fingerprint TEXT PRIMARY KEY,stamp REAL,session TEXT,role TEXT);
            ''')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15);db.execute('PRAGMA journal_mode=WAL');return db
    def add_device(self,name,db=None):
        identity=secrets.token_hex(16);token=secrets.token_urlsafe(32)
        def insert(conn):conn.execute('INSERT INTO devices VALUES(?,?,?,?)',(identity,str(name)[:80],digest(token),time.time()))
        if db is not None:insert(db)
        else:
            with closing(self.connect()) as conn,conn:insert(conn)
        return dict(device_id=identity,token=token)
    def authenticate(self,token):
        with closing(self.connect()) as db:
            row=db.execute('SELECT id FROM devices WHERE token_hash=?',(digest(token),)).fetchone()
        return row[0] if row else None
    def invite(self):
        code=secrets.token_urlsafe(32);expires=time.time()+7*86400
        with closing(self.connect()) as db,db:
            db.execute('DELETE FROM invites WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO invites VALUES(?,?,0)',(digest(code),expires))
        return dict(invite=code,expires=expires)
    def enroll(self,code,name):
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT expires,used FROM invites WHERE hash=?',(digest(code),)).fetchone()
            if not row or row[0]<time.time() or row[1]:raise ValueError('连接文件已使用或过期，请重新导出。')
            result=self.add_device(name,db);db.execute('UPDATE invites SET used=1 WHERE hash=?',(digest(code),));return result
    def ingest(self,device,records):
        if not isinstance(records,list) or len(records)>1000:raise ValueError('invalid batch')
        clean=[]
        for r in records:
            if not isinstance(r,dict) or set(r)-{'session','total','stamp','model','input','output'}:raise ValueError('unexpected fields')
            sid=r.get('session');total=r.get('total');stamp=r.get('stamp');model=r.get('model')
            if not isinstance(sid,str) or not re.fullmatch('[0-9a-f]{64}',sid):raise ValueError('invalid session')
            if type(total) is not int or not 0<total<2**60:raise ValueError('invalid counter')
            if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<stamp<4102444800:raise ValueError('invalid time')
            if not isinstance(model,str) or not 0<len(model)<=128:raise ValueError('invalid model')
            a,b=r.get('input'),r.get('output')
            if any(v is not None and (type(v) is not int or not 0<=v<2**60) for v in (a,b)):raise ValueError('invalid split')
            clean.append((sid,total,stamp,model,a,b,device))
        changed=set();inserted=0
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            for values in clean:
                sid,total,stamp,model,a,b,_=values
                old=db.execute('SELECT stamp,model,input,output FROM raw WHERE session=? AND total=?',(sid,total)).fetchone()
                if old is None:
                    db.execute('INSERT INTO raw VALUES(?,?,?,?,?,?,?)',values);inserted+=1;changed.add(sid)
                else:
                    known=a is not None and b is not None and a+b==total
                    old_known=old[2] is not None and old[3] is not None and old[2]+old[3]==total
                    new=(min(old[0],stamp),model if old[1]=='未识别模型' else old[1],a if known and not old_known else old[2],b if known and not old_known else old[3])
                    if tuple(old)!=new:
                        db.execute('UPDATE raw SET stamp=?,model=?,input=?,output=? WHERE session=? AND total=?',(*new,sid,total));changed.add(sid)
            for sid in changed:self.rebuild(db,sid)
            db.execute('UPDATE devices SET last_seen=? WHERE id=?',(time.time(),device))
        return dict(accepted=len(clean),inserted=inserted)
    @staticmethod
    def rebuild(db,sid):
        # Union of cumulative checkpoints. A late intermediate checkpoint only
        # redistributes an existing total; replay/partial copies cannot add it twice.
        db.execute('DELETE FROM usage WHERE session=?',(sid,));previous=0;pi=po=0
        for total,stamp,model,a,b in db.execute('SELECT total,stamp,model,input,output FROM raw WHERE session=? ORDER BY total',(sid,)).fetchall():
            delta=total-previous;di=a-pi if a is not None and pi is not None else None;do=b-po if b is not None and po is not None else None
            known=di is not None and do is not None and di>=0 and do>=0 and di+do==delta
            db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)',(sid+':'+str(total),stamp,delta,sid,model,di if known else None,do if known else None,int(known)))
            previous=total;pi=a;po=b
    def snapshot(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            value=TokenUsageIndex.snapshot(SimpleNamespace(),db)
            devices=[dict(device_id=i,name=n,last_seen=t) for i,n,t in db.execute('SELECT id,name,last_seen FROM devices ORDER BY name')]
        value.update(source='多端 Codex 日志（已去重）',scope='all',devices=devices,timezone='Asia/Shanghai',messages_available=False)
        value['report'].update(messages=None,messages_available=False,scope='all')
        return value


class Handler(BaseHTTPRequestHandler):
    server_version='BailongTokenSync/1'
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(15)
    def respond(self,status,value):
        data=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def body(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=1024*1024:raise ValueError('invalid request size')
        return json.loads(self.rfile.read(length))
    def device(self):
        header=self.headers.get('Authorization','')
        return self.server.store.authenticate(header[7:]) if header.startswith('Bearer ') and len(header)<512 else None
    def do_GET(self):
        try:
            if self.path=='/health':return self.respond(200,dict(status='ok',schema=1))
            if not self.device():return self.respond(401,dict(error='设备认证失败，请重新导入连接文件。'))
            if self.path=='/v1/snapshot':return self.respond(200,self.server.store.snapshot())
            self.respond(404,dict(error='not found'))
        except (OSError,sqlite3.Error):self.respond(503,dict(error='同步服务暂不可用'))
    def do_POST(self):
        try:
            if self.path=='/v1/enroll':
                body=self.body()
                return self.respond(200,self.server.store.enroll(str(body.get('invite','')),str(body.get('name','设备'))))
            device=self.device()
            if not device:return self.respond(401,dict(error='设备认证失败，请重新导入连接文件。'))
            if self.path=='/v1/records':return self.respond(200,self.server.store.ingest(device,self.body().get('records')))
            if self.path=='/v1/invites':return self.respond(200,self.server.store.invite())
            self.respond(404,dict(error='not found'))
        except (ValueError,TypeError,KeyError,AttributeError):self.respond(400,dict(error='请求无效或连接文件已使用/过期。'))
        except (OSError,sqlite3.Error):self.respond(503,dict(error='同步服务暂不可用'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=8769);parser.add_argument('--create-device')
    args=parser.parse_args();os.environ['TZ']='Asia/Shanghai'
    if hasattr(time,'tzset'):time.tzset()
    store=SyncStore(args.db)
    if args.create_device:print(json.dumps(store.add_device(args.create_device)));return
    server=ThreadingHTTPServer((args.bind,args.port),Handler);server.daemon_threads=True;server.store=store
    server.serve_forever(poll_interval=.5)

if __name__=='__main__':main()
