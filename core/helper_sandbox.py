"""Isolated demo workflow and bounded metadata-only activity tracking."""
import sqlite3
from contextlib import contextmanager
from collections import deque


class HelperStore:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,creator INTEGER,title TEXT,
                    state TEXT,owner INTEGER,created REAL,updated REAL);
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER,actor INTEGER,action TEXT,at REAL);
                CREATE TABLE IF NOT EXISTS duty (user_id INTEGER PRIMARY KEY,enabled INTEGER);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=3)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def get(self,key):
        with self.connect() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    def set(self,key,value):
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,str(value)))

    def reserve(self,key):
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO settings VALUES (?,'reserved')",(key,)).rowcount==1

    def create(self,user,now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute("SELECT id FROM requests WHERE creator=? AND state!='done'",(user,)).fetchone()
            if existing: return existing[0],False
            if db.execute("SELECT COUNT(*) FROM requests WHERE state!='done'").fetchone()[0]>=20:
                raise ValueError('已有 20 個未完成測試，請先完成舊測試。')
            cur=db.execute("INSERT INTO requests(creator,title,state,owner,created,updated) VALUES (?,?,'open',NULL,?,?)",(user,'【虛構】MH 連線失敗，想搵人幫手',now,now))
            db.execute('INSERT INTO history(request_id,actor,action,at) VALUES (?,?,?,?)',(cur.lastrowid,user,'建立測試求助',now))
            return cur.lastrowid,True

    def active(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE state!='done' ORDER BY created LIMIT 20")]

    def history(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM history ORDER BY id DESC LIMIT 20')]

    def transition(self,request,user,action,now,admin=False):
        if action not in {'claim','done','handoff'}: raise ValueError('無效操作。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM requests WHERE id=?',(request,)).fetchone()
            if not row or row['state']=='done': raise ValueError('呢個測試已完成或不存在。')
            if action=='claim':
                if row['owner'] is not None: raise ValueError('已有人接手；唔使重複處理。')
                state,owner,label='claimed',user,'接手'
            else:
                if row['owner']!=user and not admin: raise ValueError('只限負責人或管理員處理。')
                state,owner,label=('done',user,'完成') if action=='done' else ('handoff',None,'需要其他 Helper')
            db.execute('UPDATE requests SET state=?,owner=?,updated=? WHERE id=?',(state,owner,now,request))
            db.execute('INSERT INTO history(request_id,actor,action,at) VALUES (?,?,?,?)',(request,user,label,now))
            return label

    def toggle_duty(self,user):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT enabled FROM duty WHERE user_id=?',(user,)).fetchone()
            enabled=not bool(row[0]) if row else True
            db.execute('INSERT OR REPLACE INTO duty VALUES (?,?)',(user,int(enabled)))
            return enabled


class ActivityWindow:
    def __init__(self,started,limit=10000):
        self.started=started
        self.events=deque(maxlen=limit)
        self.truncated_until=0
        self.voice_started={}
        self.attention=deque(maxlen=200)

    def add(self,channel,user,now):
        self.prune(now)
        if len(self.events)==self.events.maxlen: self.truncated_until=now+1800
        self.events.append((now,channel,user))

    def prune(self,now):
        while self.events and self.events[0][0]<now-1800: self.events.popleft()

    def counts(self,now):
        self.prune(now)
        result={}
        for _,channel,user in self.events:
            item=result.setdefault(channel,{'messages':0,'users':set()})
            item['messages']+=1
            item['users'].add(user)
        return result


    def note_attention(self,message_id,channel_id,user,at,*,newcomer=False,lfg=False):
        self.attention=deque((r for r in self.attention if r['at']>=at-1800),maxlen=200)
        if newcomer and not any(r['kind']=='newcomer' and r['user']==user for r in self.attention):
            self.attention.append(dict(message=message_id,channel=channel_id,user=user,at=at,kind='newcomer',replied=False))
        existing=next((r for r in self.attention if r['kind']=='lfg' and r['message']==message_id),None)
        if existing and not lfg: self.attention.remove(existing)
        elif lfg and not existing:
            self.attention.append(dict(message=message_id,channel=channel_id,user=user,at=at,kind='lfg',replied=False))

    def attention_reply(self,message_id,user):
        for row in self.attention:
            if row['message']==message_id and row['user']!=user: row['replied']=True

    def attention_delete(self,message_id):
        self.attention=deque((r for r in self.attention if r['message']!=message_id),maxlen=200)
