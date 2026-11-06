"""Con9sole XP ledger. No message bodies, tokens or usernames are persisted."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.sqlite_storage import connect_sqlite, enable_wal
from core.storage_paths import DATA_DIR

TZ = ZoneInfo('Asia/Hong_Kong')
DEFAULTS = dict(mode='off', text_cooldown=60, activity_cooldown=60,
                activity_daily_cap=60, voice_interval=300, voice_xp=25,
                booster_multiplier=2, announcement_channel=0, announcement_ping=False,
                excluded_channels=[], excluded_roles=[], sources=[], rewards={})
REWARD_NAMES = {5:'註冊會員',15:'活躍會員',30:'常駐會員',50:'高級會員',75:'資深會員',
                100:'核心會員',150:'白金會員',200:'黑金會員',300:'榮譽會員',400:'傳奇會員'}


def threshold(level: int) -> int:
    """Own transparent curve: 50 * level * (level+1), NOT Amari's curve."""
    return 50 * level * (level + 1)


def level_for(xp: int) -> int:
    from math import isqrt
    return max(0, (isqrt(1 + 4 * max(0, xp) // 50) - 1) // 2)


def calendar(now: float) -> tuple[str, str]:
    dt = datetime.fromtimestamp(now, TZ)
    iso = dt.isocalendar()
    return dt.date().isoformat(), f'{iso.year}-W{iso.week:02}'


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / 'community_levels.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.path) as db:
            enable_wal(db)
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settings(guild INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS xp(guild INTEGER, user INTEGER, total INTEGER NOT NULL DEFAULT 0,
              text INTEGER NOT NULL DEFAULT 0, activity INTEGER NOT NULL DEFAULT 0,
              voice INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(guild,user));
            CREATE TABLE IF NOT EXISTS periods(guild INTEGER,user INTEGER,week TEXT,points INTEGER NOT NULL,
              PRIMARY KEY(guild,user,week));
            CREATE TABLE IF NOT EXISTS cooldowns(guild INTEGER,user INTEGER,bucket TEXT,stamp REAL,
              day TEXT,count INTEGER,PRIMARY KEY(guild,user,bucket));
            CREATE TABLE IF NOT EXISTS receipts(guild INTEGER,event TEXT,stamp REAL,
              PRIMARY KEY(guild,event));
            CREATE INDEX IF NOT EXISTS receipts_stamp ON receipts(guild,stamp);
            CREATE TABLE IF NOT EXISTS adjustments(id INTEGER PRIMARY KEY,guild INTEGER,user INTEGER,
              actor INTEGER,delta INTEGER,reason TEXT,stamp REAL);
            CREATE TABLE IF NOT EXISTS bindings(guild INTEGER,bot INTEGER,namehash TEXT,user INTEGER,
              PRIMARY KEY(guild,bot,namehash));
            CREATE TABLE IF NOT EXISTS imports(guild INTEGER PRIMARY KEY,digest TEXT,stamp REAL);
            ''')

    def settings(self, guild):
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
        return dict(DEFAULTS, **(json.loads(row[0]) if row else {}))

    def configure(self, guild, **changes):
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
            value = {**DEFAULTS, **(json.loads(row[0]) if row else {}), **changes}
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(guild,json.dumps(value)))
        return value

    def award(self, guild, user, source, event, now, *, multiplier=1):
        if source not in ('text','activity','voice'):
            raise ValueError('Unknown XP source')
        cfg = self.settings(guild)
        if cfg['mode'] == 'off':
            return None
        day, week = calendar(now)
        bucket = 'voice' if source == 'voice' else 'engagement'
        cooldown = cfg['voice_interval'] if source == 'voice' else max(cfg['text_cooldown'], cfg['activity_cooldown'])
        amount = cfg['voice_xp'] if source == 'voice' else max(1, int(multiplier))
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            # A message ID is consumed even during cooldown. Later embed edits cannot farm XP.
            db.execute('DELETE FROM receipts WHERE guild=? AND stamp<?',(guild,now-7*86400))
            if db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?)',(guild,event,now)).rowcount == 0:
                return None
            row = db.execute('SELECT stamp,day,count FROM cooldowns WHERE guild=? AND user=? AND bucket=?',
                             (guild,user,bucket)).fetchone()
            if row and now-row[0] < cooldown:
                return None
            countrow = db.execute('SELECT day,count FROM cooldowns WHERE guild=? AND user=? AND bucket=?',
                                 (guild,user,'activity_cap')).fetchone()
            count = countrow[1] if countrow and countrow[0] == day else 0
            if source == 'activity' and count >= cfg['activity_daily_cap']:
                return None
            if source == 'activity':
                db.execute('INSERT OR REPLACE INTO cooldowns VALUES(?,?,?,?,?,?)',
                           (guild,user,'activity_cap',now,day,count+1))
            db.execute('INSERT OR REPLACE INTO cooldowns VALUES(?,?,?,?,?,?)',(guild,user,bucket,now,day,0))
            db.execute('INSERT OR IGNORE INTO xp(guild,user) VALUES(?,?)',(guild,user))
            old = db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,user)).fetchone()[0]
            db.execute(f'UPDATE xp SET total=total+?,{source}={source}+? WHERE guild=? AND user=?',
                       (amount,amount,guild,user))
            db.execute('INSERT INTO periods VALUES(?,?,?,?) ON CONFLICT(guild,user,week) DO UPDATE SET points=points+excluded.points',
                       (guild,user,week,amount))
        return old, old+amount

    def profile(self, guild, user):
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT total,text,activity,voice,imported FROM xp WHERE guild=? AND user=?',
                             (guild,user)).fetchone() or (0,0,0,0,0)
        return dict(zip(('total','text','activity','voice','imported'),row))

    def leaderboard(self,guild,week=None):
        with connect_sqlite(self.path) as db:
            if week:
                return db.execute('SELECT user,points FROM periods WHERE guild=? AND week=? ORDER BY points DESC,user LIMIT 10',
                                  (guild,week)).fetchall()
            return db.execute('SELECT user,total FROM xp WHERE guild=? ORDER BY total DESC,user LIMIT 10',(guild,)).fetchall()

    def bind(self,guild,bot,name,user):
        digest = hashlib.sha256(name.encode()).hexdigest()
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR REPLACE INTO bindings VALUES(?,?,?,?)',(guild,bot,digest,user))

    def resolve(self,guild,bot,name):
        digest = hashlib.sha256(name.encode()).hexdigest()
        with connect_sqlite(self.path) as db:
            row = db.execute('SELECT user FROM bindings WHERE guild=? AND bot=? AND namehash=?',(guild,bot,digest)).fetchone()
        return row[0] if row else None

    def adjust(self,guild,user,actor,delta,reason,now):
        if not reason.strip() or len(reason)>200 or abs(delta)>1_000_000:
            raise ValueError('需要原因（最多 200 字），每次最多調整 1,000,000 XP。')
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO xp(guild,user) VALUES(?,?)',(guild,user))
            old = db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,user)).fetchone()[0]
            new = max(0,old+delta)
            db.execute('UPDATE xp SET total=? WHERE guild=? AND user=?',(new,guild,user))
            db.execute('INSERT INTO adjustments(guild,user,actor,delta,reason,stamp) VALUES(?,?,?,?,?,?)',
                       (guild,user,actor,new-old,reason,now))
        return old,new

    def import_levels(self,guild,rows,now,*,commit=False):
        """One-time verified level baseline. Preserves earned XP; never guesses Amari raw-XP curve."""
        ids=set()
        for uid,level in rows:
            if uid<=0 or uid>=2**63 or uid in ids or not 0<=level<=10000:
                raise ValueError('ID／等級無效，或有重複玩家。')
            ids.add(uid)
        if not rows or len(rows)>10000:
            raise ValueError('匯入需有 1–10,000 位玩家。')
        digest=hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM imports WHERE guild=?',(guild,)).fetchone():
                raise ValueError('已匯入過；禁止重複或覆蓋，請使用管理調整。')
            if not commit:
                return len(rows)
            for uid,level in rows:
                amount=threshold(level)
                db.execute('INSERT OR IGNORE INTO xp(guild,user) VALUES(?,?)',(guild,uid))
                db.execute('UPDATE xp SET total=total+?,imported=? WHERE guild=? AND user=?',(amount,amount,guild,uid))
            db.execute('INSERT INTO imports VALUES(?,?,?)',(guild,digest,now))
        return len(rows)


def battle_identity(embeds):
    """Return (mention ID, author username) or (None, pet owner's username).

    Only call after exact bot ID + thread allowlist verification. No generic mention guessing.
    """
    import re
    if len(embeds)<2:
        return None
    header, result = embeds[0], embeds[1]
    title = result.get('title','')
    if not title.endswith(' attack!'):
        return None
    text = result.get('description','')+' '+ ' '.join(str(f.get('name',''))+' '+str(f.get('value','')) for f in result.get('fields',[]))
    if not any(marker in text for marker in ('Damage Taken','You tried attacking','saved you from death','You defeated','You casted')):
        return None
    desc=header.get('description','')
    mentions=re.findall(r'<@!?(\d+)>',desc)
    name=header.get('author',{}).get('name','') or header.get('title','')
    if len(set(mentions))==1 and name:
        return int(mentions[0]),name
    pet=re.fullmatch(r"\*?([a-zA-Z0-9_.]+)'s pet attacking\*?",desc.strip())
    if pet:
        return None,pet[1]
    return None
