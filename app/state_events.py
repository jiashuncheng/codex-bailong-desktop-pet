"""Authenticated server-sent snapshots; one revision per committed state change."""
import threading,time,uuid
from contextlib import closing

class StateEvents:
    def __init__(self,shared):
        self.shared=shared;self.condition=threading.Condition();self.epoch=uuid.uuid4().hex
        with closing(shared.store.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS shared_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO shared_revision VALUES(1,0)')
            db.execute('CREATE TABLE IF NOT EXISTS usage_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO usage_revision VALUES(1,0)')
            from shared_rates import migrate
            migrate(db)
            db.execute('CREATE TABLE IF NOT EXISTS shared_presence(device TEXT PRIMARY KEY,online INTEGER NOT NULL)')
    def revision(self,db):return db.execute('SELECT revision FROM shared_revision WHERE id=1').fetchone()[0]
    def bump(self,db):db.execute('UPDATE shared_revision SET revision=revision+1 WHERE id=1')
    def usage_revision(self,db):return db.execute('SELECT revision FROM usage_revision WHERE id=1').fetchone()[0]
    def usage_bump(self,db):
        db.execute('UPDATE usage_revision SET revision=revision+1 WHERE id=1');self.bump(db)
    def notify(self):
        with self.condition:self.condition.notify_all()
    def expire(self,now=None):
        now=time.time() if now is None else now
        with closing(self.shared.store.connect()) as db,db:
            expired=db.execute('SELECT p.device FROM shared_presence p JOIN shared_devices d ON p.device=d.device WHERE p.online=1 AND (d.seen<? OR d.ready=0)',(now-90,)).fetchall()
            stale=db.execute('DELETE FROM shared_rates WHERE expires<=?',(now,)).rowcount
            if stale:self.bump(db)
            if expired:
                db.executemany('UPDATE shared_presence SET online=0 WHERE device=?',expired);self.bump(db)
        if expired or stale:self.notify()
    def wait(self,revision,timeout=10):
        # Lock ordering is condition then SQLite only for this short read. Writers
        # commit and close SQLite before acquiring the condition to notify.
        with self.condition:
            with closing(self.shared.store.connect()) as db:current=self.revision(db)
            if current==revision:self.condition.wait(timeout)
        self.expire()
