"""Read-only historical game audit. This database never credits the live XP ledger."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from core.sqlite_storage import connect_sqlite, enable_wal
from core.storage_paths import DATA_DIR


class HistoryAudit:
    def __init__(self,path=None):
        self.path=Path(path or DATA_DIR/'level_history.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with connect_sqlite(self.path) as db:
            enable_wal(db)
            db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,guild INTEGER,start REAL,cutoff REAL,state TEXT,sources TEXT);
            CREATE TABLE IF NOT EXISTS cursors(job TEXT,channel INTEGER,message INTEGER,done INTEGER DEFAULT 0,PRIMARY KEY(job,channel));
            CREATE TABLE IF NOT EXISTS cards(job TEXT,message INTEGER,channel INTEGER,bot INTEGER,stamp REAL,edited REAL,
                user INTEGER,ownerhash TEXT,kind TEXT,reason TEXT,digest TEXT,preview_xp INTEGER,PRIMARY KEY(job,message));
            CREATE TABLE IF NOT EXISTS owners(job TEXT,bot INTEGER,namehash TEXT,user INTEGER,PRIMARY KEY(job,bot,namehash,user));
            CREATE TABLE IF NOT EXISTS preview(job TEXT,event TEXT,user INTEGER,stamp REAL,PRIMARY KEY(job,event));
            ''')

    def start(self,guild,start,cutoff,sources):
        if not 0<start<cutoff or not sources:raise ValueError('Invalid audit scope')
        source_json=json.dumps(sources,sort_keys=True)
        with connect_sqlite(self.path) as db:
            row=db.execute("SELECT id FROM jobs WHERE guild=? AND state IN ('running','paused') ORDER BY cutoff DESC LIMIT 1",(guild,)).fetchone()
            if row:return row[0]
            job=uuid.uuid4().hex[:16]
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(job,guild,start,cutoff,'running',source_json))
            for channel in sorted({s['channel'] for s in sources}):
                db.execute('INSERT INTO cursors(job,channel,message) VALUES(?,?,0)',(job,channel))
        return job

    def latest(self,guild):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT id FROM jobs WHERE guild=? ORDER BY cutoff DESC LIMIT 1',(guild,)).fetchone()

    def job(self,job,guild):
        with connect_sqlite(self.path) as db:
            row=db.execute('SELECT start,cutoff,state,sources FROM jobs WHERE id=? AND guild=?',(job,guild)).fetchone()
            if not row:raise ValueError('Unknown audit')
            cursors=db.execute('SELECT channel,message,done FROM cursors WHERE job=? ORDER BY channel',(job,)).fetchall()
        return dict(start=row[0],cutoff=row[1],state=row[2],sources=json.loads(row[3]),cursors=cursors)

    @staticmethod
    def owner_hash(name):return hashlib.sha256(name.encode()).hexdigest()

    def remember_owner(self,job,bot,name,user):
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO owners VALUES(?,?,?,?)',(job,bot,self.owner_hash(name),user))

    def resolve_owner(self,job,bot,name):
        with connect_sqlite(self.path) as db:
            rows=db.execute('SELECT user FROM owners WHERE job=? AND bot=? AND namehash=?',(job,bot,self.owner_hash(name))).fetchall()
        return rows[0][0] if len(rows)==1 else None

    def finalize_pets(self,job,current_names):
        """Resolve only after all sources; current_names maps member IDs to name hashes."""
        with connect_sqlite(self.path) as db:
            rows=db.execute("SELECT message,bot,ownerhash FROM cards WHERE job=? AND kind='pet' AND reason!='edited_card_history_unavailable'",(job,)).fetchall()
            for message,bot,namehash in rows:
                owners=db.execute('SELECT user FROM owners WHERE job=? AND bot=? AND namehash=?',(job,bot,namehash)).fetchall()
                uid=owners[0][0] if len(owners)==1 else None
                reason='owner_ambiguous' if len(owners)>1 else 'identity_unresolved'
                if uid:reason='candidate' if current_names.get(uid)==namehash else 'departed_or_name_changed'
                db.execute('UPDATE cards SET user=?,reason=? WHERE job=? AND message=?',(uid,reason,job,message))

    def preview_events(self,job,events):
        with connect_sqlite(self.path) as db:
            db.executemany('INSERT OR IGNORE INTO preview VALUES(?,?,?,?)',[(job,event,user,stamp) for event,user,stamp in events])

    def record(self,job,*,message,channel,bot,stamp,edited,user,name,kind,reason,payload,preview_xp=0):
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (job,message,channel,bot,stamp,edited,user,self.owner_hash(name) if name else None,kind,reason,digest,preview_xp))

    def checkpoint(self,job,channel,message,*,done=False):
        with connect_sqlite(self.path) as db:
            db.execute('UPDATE cursors SET message=max(message,?),done=? WHERE job=? AND channel=?',(message,int(done),job,channel))

    def state(self,job,state):
        if state not in ('running','paused','complete'):raise ValueError('Invalid state')
        with connect_sqlite(self.path) as db:db.execute('UPDATE jobs SET state=? WHERE id=?',(state,job))

    def summary(self,job,guild,inventory=None):
        scope=self.job(job,guild)
        with connect_sqlite(self.path) as db:
            reasons=dict(db.execute('SELECT reason,count(*) FROM cards WHERE job=? GROUP BY reason',(job,)))
            rows=db.execute("SELECT message,user,stamp,preview_xp FROM cards WHERE job=? AND reason='candidate' ORDER BY stamp,message",(job,)).fetchall()
            prior=db.execute('SELECT user,stamp FROM preview WHERE job=?',(job,)).fetchall()
        archived_candidates=0
        if inventory is not None:
            live=inventory['retained'];shadow=inventory['archived']
            archived_candidates=sum(f'm:{message}' in shadow for message,_,_,_ in rows)
            # Old immutable observations say an event WAS awarded, not whether it survived baseline replacement.
            rows=[(message,user,stamp,int(f'm:{message}' in live)) for message,user,stamp,_ in rows]
            prior=[(row['user'],row['stamp']) for row in live.values()]
        # Potential game-only claims, not additional awards: historical text CD evidence is still required.
        clocks={};users={};preview=0;cooldown=0
        preview_times={}
        for user,stamp in prior:preview_times.setdefault(user,[]).append(stamp)
        for _,user,stamp,already in rows:
            if already:preview_times.setdefault(user,[]).append(stamp)
        for message,user,stamp,already in rows:
            if already:preview+=1;continue
            if any(abs(stamp-t)<60 for t in preview_times.get(user,[])):
                cooldown+=1;continue
            if user in clocks and stamp-clocks[user]<60:
                cooldown+=1;continue
            clocks[user]=stamp
            users[user]=users.get(user,0)+1
        return dict(state=scope['state'],start=scope['start'],cutoff=scope['cutoff'],reasons=reasons,
                    potential=users,preview=preview,cooldown=cooldown,archived_candidates=archived_candidates,
                    complete_channels=sum(bool(c[2]) for c in scope['cursors']),channels=len(scope['cursors']))

    def start_text(self,job,guild,channels,policy):
        self.job(job,guild)
        with connect_sqlite(self.path) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS text_scopes(job TEXT PRIMARY KEY,policy TEXT,state TEXT);
            CREATE TABLE IF NOT EXISTS text_cursors(job TEXT,channel INTEGER,message INTEGER,done INTEGER,PRIMARY KEY(job,channel));
            CREATE TABLE IF NOT EXISTS text_events(job TEXT,message INTEGER,user INTEGER,stamp REAL,PRIMARY KEY(job,message));
            ''')
            body=json.dumps(policy,sort_keys=True)
            old=db.execute('SELECT policy FROM text_scopes WHERE job=?',(job,)).fetchone()
            if old and old[0]!=body:raise ValueError('Historical text policy changed; use a new history batch')
            if not old:
                db.execute('INSERT INTO text_scopes VALUES(?,?,?)',(job,body,'paused'))
                db.executemany('INSERT INTO text_cursors VALUES(?,?,0,0)',[(job,cid) for cid in sorted(set(channels))])
            actual={r[0] for r in db.execute('SELECT channel FROM text_cursors WHERE job=?',(job,))}
            if actual!=set(channels):raise ValueError('Text channel scope changed; use a new history batch')

    def text_scope(self,job):
        with connect_sqlite(self.path) as db:
            row=db.execute('SELECT policy,state FROM text_scopes WHERE job=?',(job,)).fetchone()
            if not row:raise ValueError('Text audit not started')
            cursors=db.execute('SELECT channel,message,done FROM text_cursors WHERE job=? ORDER BY channel',(job,)).fetchall()
        return dict(policy=json.loads(row[0]),state=row[1],cursors=cursors)

    def text_checkpoint(self,job,channel,message,events,done=False):
        with connect_sqlite(self.path) as db:
            db.executemany('INSERT OR IGNORE INTO text_events VALUES(?,?,?,?)',[(job,*row) for row in events])
            db.execute('UPDATE text_cursors SET message=max(message,?),done=? WHERE job=? AND channel=?',(message,int(done),job,channel))

    def text_state(self,job,state):
        if state not in ('running','paused','complete'):raise ValueError('Invalid text audit state')
        with connect_sqlite(self.path) as db:db.execute('UPDATE text_scopes SET state=? WHERE job=?',(state,job))

    def text_replay(self,job,guild):
        """Net base XP after replaying text plus games, relative to text alone.

        Replay only before the applied baseline cutoff. This is an evidence preview,
        not permission to infer deleted messages or historical Booster membership.
        """
        scope=self.job(job,guild);text=self.text_scope(job);policy=text['policy']
        if scope['state']!='complete' or text['state']!='complete' or not all(c[2] for c in text['cursors']):
            raise ValueError('Both game and text scans must be complete')
        start=scope['start'];cutoff=policy['cutoff'];cd=policy['cooldown']
        with connect_sqlite(self.path) as db:
            games=db.execute("SELECT message,user,stamp FROM cards WHERE job=? AND reason='candidate' AND stamp>=? AND stamp<? ORDER BY stamp,message",(job,start,cutoff)).fetchall()
            texts=db.execute('SELECT message,user,stamp FROM text_events WHERE job=? AND stamp<? ORDER BY stamp,message',(job,cutoff)).fetchall()
        games=[row for row in games if row[1] in set(policy['users'])]
        users={uid for _,uid,_ in games};result={}
        for uid in sorted(users):
            human=[(stamp,mid,'text') for mid,user,stamp in texts if user==uid]
            activity=[(stamp,mid,'activity') for mid,user,stamp in games if user==uid]
            prefix=sorted(human+[min(activity)])
            first_game=min(stamp for stamp,_,_ in activity)
            before=[stamp for stamp,_,_ in prefix if stamp<=first_game]
            if before and before[0]<start and not any(b-a>=cd for a,b in zip(before,before[1:])):
                raise ValueError('Initial text cooldown cannot be reconstructed before first game')
            def replay(events):
                clock=None;accepted=[]
                for stamp,mid,kind in sorted(events):
                    if clock is None or stamp-clock>=cd:
                        clock=stamp
                        if stamp>=start:accepted.append((mid,kind,stamp))
                return accepted
            old=replay(human);combined=replay(human+activity)
            delta=len(combined)-len(old)
            if delta<0:raise ValueError('Negative replay delta requires manual reconciliation')
            result[uid]=dict(base_xp=delta,text_only=len(old),combined=len(combined),game_candidates=len(activity),
                game_accepted=sum(kind=='activity' for _,kind,_ in combined))
        evidence=hashlib.sha256(json.dumps([policy,games,texts],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return dict(algorithm='net-shared-cooldown-v1',evidence_digest=evidence,policy=policy,users=result,
            text_channels=len(text['cursors']),text_observations=len(texts),
            limitations=['retained Discord history only; deleted history unavailable','historical Booster multipliers not inferred'])
