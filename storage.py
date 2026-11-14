# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

"""Local archive. Keeps the previous AyuGhost tables and adds account-scoped snapshots."""
import sqlite3
import threading
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS deleted_keys(did INTEGER NOT NULL,mid INTEGER NOT NULL,ts INTEGER NOT NULL,PRIMARY KEY(did,mid));
CREATE TABLE IF NOT EXISTS message_edits(did INTEGER NOT NULL,mid INTEGER NOT NULL,ver INTEGER NOT NULL,date INTEGER NOT NULL,data BLOB NOT NULL,PRIMARY KEY(did,mid,ver));
CREATE TABLE IF NOT EXISTS exception_users(did INTEGER NOT NULL,exception_reading INTEGER DEFAULT 0 NOT NULL,exception_typing INTEGER DEFAULT 0 NOT NULL,PRIMARY KEY(did));
CREATE TABLE IF NOT EXISTS regex_filters(regex TEXT NOT NULL PRIMARY KEY);
CREATE TABLE IF NOT EXISTS shadowban_users(user_id INTEGER PRIMARY KEY,hide_dialog INTEGER DEFAULT 1,hide_in_groups INTEGER DEFAULT 1,added_ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_snapshots(account INTEGER NOT NULL,did INTEGER NOT NULL,mid INTEGER NOT NULL,date INTEGER NOT NULL,text TEXT NOT NULL,data BLOB,deleted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(account,did,mid));
CREATE TABLE IF NOT EXISTS source_edits(account INTEGER NOT NULL,did INTEGER NOT NULL,mid INTEGER NOT NULL,ver INTEGER NOT NULL,date INTEGER NOT NULL,text TEXT NOT NULL,data BLOB,PRIMARY KEY(account,did,mid,ver));
CREATE INDEX IF NOT EXISTS source_deleted ON source_snapshots(account,deleted,did);
'''

class Archive:
    def __init__(self, path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(str(path),check_same_thread=False,timeout=5)
        with self.db:self.db.executescript(SCHEMA)
        self.deleted=set(self.db.execute('SELECT did,mid FROM deleted_keys'))
        self.exceptions={r[0]:(r[1],r[2]) for r in self.db.execute('SELECT * FROM exception_users')}
        self.hidden={r[0]:(bool(r[1]),bool(r[2])) for r in self.db.execute('SELECT user_id,hide_dialog,hide_in_groups FROM shadowban_users')}
        self.filters=[r[0] for r in self.db.execute('SELECT regex FROM regex_filters ORDER BY regex')]
    def close(self):
        with self.lock:self.db.close()
    def snapshot(self, account,did,mid,date,text,data=None,edited=False):
        key=(int(account),int(did),int(mid))
        with self.lock,self.db:
            old=self.db.execute('SELECT date,text,data,deleted FROM source_snapshots WHERE account=? AND did=? AND mid=?',key).fetchone()
            if edited and old and (old[1]!=text or old[2]!=data):
                seq=self.db.execute('SELECT COALESCE(MAX(ver),-1)+1 FROM source_edits WHERE account=? AND did=? AND mid=?',key).fetchone()[0]
                if seq==0:
                    self.db.execute('INSERT INTO source_edits VALUES(?,?,?,?,?,?,?)',key+(0,old[0],old[1],old[2]));seq=1
                self.db.execute('INSERT INTO source_edits VALUES(?,?,?,?,?,?,?)',key+(seq,int(date),str(text),data))
            self.db.execute('INSERT OR REPLACE INTO source_snapshots VALUES(?,?,?,?,?,?,?)',key+(int(date),str(text),data,old[3] if old else 0))
    def mark(self, account,did,mids):
        now=int(time.time())
        with self.lock,self.db:
            for mid in mids:
                self.deleted.add((int(did),int(mid)))
                self.db.execute('INSERT OR IGNORE INTO deleted_keys VALUES(?,?,?)',(int(did),int(mid),now))
                self.db.execute('UPDATE source_snapshots SET deleted=1 WHERE account=? AND did=? AND mid=?',(int(account),int(did),int(mid)))
    def is_deleted(self,did,mid):return (int(did),int(mid)) in self.deleted
    def exception(self,did):return self.exceptions.get(int(did),(0,0))
    def set_exception(self,did,reading,typing):
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO exception_users VALUES(?,?,?)',(int(did),int(reading),int(typing)))
            self.exceptions[int(did)]=(int(reading),int(typing))
    def set_hidden(self,uid,dialog=True,groups=True):
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO shadowban_users VALUES(?,?,?,?)',(int(uid),int(dialog),int(groups),int(time.time())))
            self.hidden[int(uid)]=(bool(dialog),bool(groups))
    def remove_hidden(self,uid):
        with self.lock,self.db:self.db.execute('DELETE FROM shadowban_users WHERE user_id=?',(int(uid),));self.hidden.pop(int(uid),None)
    def set_filters(self,patterns):
        with self.lock,self.db:
            self.db.execute('DELETE FROM regex_filters')
            self.db.executemany('INSERT OR IGNORE INTO regex_filters VALUES(?)',[(p,) for p in patterns])
            self.filters=list(dict.fromkeys(patterns))
    def list_deleted(self,account,did=None,limit=100):
        with self.lock:
            if did is None:return self.db.execute('SELECT did,mid,date,text FROM source_snapshots WHERE account=? AND deleted=1 ORDER BY date DESC LIMIT ?',(int(account),limit)).fetchall()
            return self.db.execute('SELECT did,mid,date,text FROM source_snapshots WHERE account=? AND deleted=1 AND did=? ORDER BY date DESC LIMIT ?',(int(account),int(did),limit)).fetchall()
    def history(self,account,did,mid):
        with self.lock:return self.db.execute('SELECT date,text,data FROM source_edits WHERE account=? AND did=? AND mid=? ORDER BY ver',(int(account),int(did),int(mid))).fetchall()
    def legacy_history(self,did,mid):
        with self.lock:return self.db.execute('SELECT date,data FROM message_edits WHERE did=? AND mid=? ORDER BY ver',(int(did),int(mid))).fetchall()
    def clear_archive(self):
        with self.lock,self.db:
            for table in ('deleted_keys','message_edits','source_snapshots','source_edits'):self.db.execute('DELETE FROM '+table)
            self.deleted.clear()
