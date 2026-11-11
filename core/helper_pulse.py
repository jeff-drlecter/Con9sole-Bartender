"""Small append-only activity digests: identifiers/counts only, no chat text."""
import json
import sqlite3
from contextlib import contextmanager

WINDOW=120


class PulseStore:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pulse_events (
                    key TEXT PRIMARY KEY,at REAL,bucket INTEGER,category INTEGER,
                    channel INTEGER,kind TEXT,user INTEGER,message INTEGER,value TEXT,batch INTEGER);
                CREATE INDEX IF NOT EXISTS pulse_pending ON pulse_events(batch,bucket);
                CREATE TABLE IF NOT EXISTS pulse_batches (
                    bucket INTEGER PRIMARY KEY,state TEXT,message_id INTEGER,detail TEXT);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=3)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def record(self,key,at,category,channel,kind,user=0,message=0,value=None):
        if kind not in {'chat','help','lfg','newcomer','voice'}: raise ValueError('unknown pulse kind')
        bucket=int(at//WINDOW)
        with self.connect() as db:
            if db.execute('SELECT 1 FROM pulse_batches WHERE bucket=?',(bucket,)).fetchone(): return
            db.execute('INSERT OR IGNORE INTO pulse_events VALUES (?,?,?,?,?,?,?,?,?,NULL)',
                (key,at,bucket,category,channel,kind,user,message,json.dumps(value)))
            db.execute('DELETE FROM pulse_events WHERE key IN (SELECT key FROM pulse_events ORDER BY at DESC LIMIT -1 OFFSET 10000)')

    def withdraw(self,message_id):
        with self.connect() as db:
            db.execute('DELETE FROM pulse_events WHERE message=? AND batch IS NULL',(message_id,))

    def claim(self,now):
        current=int(now//WINDOW)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM pulse_events WHERE at<?',(now-86400,))
            # Do not flood old activity on recovery; keep only recent unsent windows.
            db.execute('DELETE FROM pulse_events WHERE batch IS NULL AND at<?',(now-900,))
            db.execute('DELETE FROM pulse_batches WHERE bucket<?',(int((now-7*86400)//WINDOW),))
            row=db.execute('SELECT MIN(bucket) FROM pulse_events WHERE batch IS NULL AND bucket<?',(current,)).fetchone()
            if row[0] is None: return None
            bucket=row[0]
            if db.execute('SELECT 1 FROM pulse_batches WHERE bucket=?',(bucket,)).fetchone():
                db.execute('UPDATE pulse_events SET batch=? WHERE bucket=? AND batch IS NULL',(bucket,bucket))
                return None
            db.execute("INSERT INTO pulse_batches VALUES (?,'sending',NULL,'')",(bucket,))
            db.execute('UPDATE pulse_events SET batch=? WHERE bucket=? AND batch IS NULL',(bucket,bucket))
            rows=[dict(r) for r in db.execute('SELECT * FROM pulse_events WHERE batch=? ORDER BY at,key',(bucket,))]
            for event in rows: event['value']=json.loads(event['value'])
            return {'bucket':bucket,'events':rows}

    def finish(self,bucket,state,message_id=0,detail=''):
        if state not in {'sent','uncertain','skipped'}: raise ValueError('invalid pulse state')
        with self.connect() as db:
            db.execute('UPDATE pulse_batches SET state=?,message_id=?,detail=? WHERE bucket=? AND state=\'sending\'',(state,message_id,detail[:200],bucket))


def summarize(events):
    groups={}
    for event in events:
        group=groups.setdefault(event['category'],{'chat':0,'people':set(),'help':set(),'lfg':set(),'newcomer':set(),'voice':None,'at':event['at']})
        group['at']=max(group['at'],event['at'])
        kind=event['kind']
        if kind=='chat':
            group['chat']+=1
            group['people'].add(event['user'])
        elif kind=='voice': group['voice']=event['value']
        else: group[kind].add(event['user'] if kind=='newcomer' else event['message'])
    return sorted(groups.items(),key=lambda pair:(-len(pair[1]['help']),-pair[1]['chat'],pair[0]))


def fragments(group):
    parts=[]
    if group['chat']: parts.append(f"💬 {len(group['people'])} 人、{group['chat']} 則")
    if group['help']: parts.append(f"🆘 {len(group['help'])} 則疑似求助")
    if group['lfg']: parts.append(f"🤝 {len(group['lfg'])} 則搵隊友")
    if group['newcomer']: parts.append(f"👋 {len(group['newcomer'])} 位近 7 日加入成員發言")
    if group['voice'] is not None:
        voice=group['voice']
        parts.append(f"🎙️ {voice['rooms']} 個 call、{voice['people']} 人" if voice['rooms'] else '🎙️ call 已散')
    return parts
