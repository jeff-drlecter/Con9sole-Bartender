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
LEVEL_TEMPLATES = {'5': '👋 {user} 升至 Lv.{level}，成為【註冊會員】！正式開展你嘅會員旅程啦～', '15': '✨ {user} 達到 Lv.{level}，升為【活躍會員】！繼續保持好表現！', '30': '💬 {user} 升到 Lv.{level}，晉升【常駐會員】，你已成為群內熟悉的存在～', '50': '📈 {user} 成功達成 Lv.{level}，晉身【高級會員】行列，邁向社群中層！', '75': '🛡️ {user} 獲得 Lv.{level} 成就，晉升為【資深會員】！長期守候有目共睹！', '100': '🎯 {user} 升至 Lv.{level}，正式踏入【核心會員】階層，歡迎加入主力陣線！', '150': '💎 {user} 現已晉升 Lv.{level}，榮獲【白金會員】稱號！高活躍代表！', '200': '🔥 {user} 升至 Lv.{level}，解鎖尊貴角色【黑金會員】！實至名歸！', '300': '🏅 {user} 成為 Lv.{level} 的《榮譽會員》！你嘅持續參與係社群中不可多得！', '400': '🎉 {user} 達成 Lv.{level}！正式晉升為【傳奇會員】👑 無人能及，傳奇由你創！'}
DEFAULTS = dict(mode='off', text_cooldown=60, activity_cooldown=60,
                activity_daily_cap=0, voice_interval=300, voice_xp=25,
                booster_multiplier=2, announcement_channel=0, announcement_ping=True,
                excluded_channels=[], excluded_roles=[], sources=[], rewards={},
                announcement_mode='all', announcement_template='恭喜 {user.ping} 升級! 依家你係 等級{level}',
                level_templates=LEVEL_TEMPLATES,clear_on_leave=True)
REWARD_NAMES = {5:'註冊會員',15:'活躍會員',30:'常駐會員',50:'高級會員',75:'資深會員',
                100:'核心會員',150:'白金會員',200:'黑金會員',300:'榮譽會員',400:'傳奇會員'}


def threshold(level: int) -> int:
    """Matches Amari current xp-info table; live runtime parity still requires validation."""
    if level < 0:
        raise ValueError("Level cannot be negative")
    return 0 if level == 0 else 20 * (level - 1) ** 2 + 35


def level_for(xp: int) -> int:
    from math import isqrt
    return 0 if xp < 35 else 1 + isqrt((xp - 35) // 20)


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
            CREATE TABLE IF NOT EXISTS xp_events(guild INTEGER,event TEXT,user INTEGER,source TEXT,amount INTEGER,stamp REAL,
              PRIMARY KEY(guild,event));
            CREATE TABLE IF NOT EXISTS role_jobs(guild INTEGER,user INTEGER,total INTEGER,old_total INTEGER,
              PRIMARY KEY(guild,user));
            CREATE TABLE IF NOT EXISTS departed_users(id INTEGER PRIMARY KEY,guild INTEGER,user INTEGER,stamp REAL,snapshot TEXT);
            CREATE TABLE IF NOT EXISTS weekly_notices(guild INTEGER,period TEXT,PRIMARY KEY(guild,period));
            CREATE TABLE IF NOT EXISTS repair_attempts(guild INTEGER,user INTEGER,attempts INTEGER,not_before REAL,PRIMARY KEY(guild,user));
            CREATE TABLE IF NOT EXISTS migration_manifests(guild INTEGER PRIMARY KEY,digest TEXT,cutover REAL,count INTEGER,
              period TEXT,backup_path TEXT,backup_sha TEXT);
            CREATE TABLE IF NOT EXISTS notice_state(guild INTEGER,user INTEGER,level INTEGER,
              PRIMARY KEY(guild,user));
            CREATE TABLE IF NOT EXISTS imports(guild INTEGER PRIMARY KEY,digest TEXT,stamp REAL);
            CREATE TABLE IF NOT EXISTS hybrid_public(guild INTEGER,batch TEXT,part INTEGER,parts INTEGER,stamp REAL,rows TEXT,PRIMARY KEY(guild,batch,part));
            CREATE TABLE IF NOT EXISTS hybrid_plans(guild INTEGER,plan TEXT PRIMARY KEY,actor INTEGER,stamp REAL,manifest TEXT,digest TEXT,state TEXT,backup_path TEXT,backup_sha TEXT);
            CREATE TABLE IF NOT EXISTS hybrid_shadow(guild INTEGER,plan TEXT,user INTEGER,profile TEXT,events TEXT,periods TEXT,PRIMARY KEY(guild,plan,user));
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
        if cfg['mode'] == 'off' or now < cfg.get('cutover_at',0):
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
            if source == 'activity' and cfg['activity_daily_cap']>0 and count >= cfg['activity_daily_cap']:
                return None
            if source == 'activity':
                db.execute('INSERT OR REPLACE INTO cooldowns VALUES(?,?,?,?,?,?)',
                           (guild,user,'activity_cap',now,day,count+1))
            db.execute('INSERT OR REPLACE INTO cooldowns VALUES(?,?,?,?,?,?)',(guild,user,bucket,now,day,0))
            db.execute('INSERT OR IGNORE INTO xp(guild,user) VALUES(?,?)',(guild,user))
            old = db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,user)).fetchone()[0]
            if db.execute('INSERT OR IGNORE INTO xp_events VALUES(?,?,?,?,?,?)',(guild,event,user,source,amount,now)).rowcount==0:
                return None
            if cfg['mode']=='active':
                db.execute('INSERT INTO role_jobs VALUES(?,?,?,?) ON CONFLICT(guild,user) DO UPDATE SET total=excluded.total',(guild,user,old+amount,old))
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

    def event_proof(self,guild,event):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT user,amount,stamp FROM xp_events WHERE guild=? AND event=?',
                              (guild,event)).fetchone()

    def engagement_events(self,guild,start,cutoff):
        with connect_sqlite(self.path) as db:
            return db.execute("SELECT event,user,stamp FROM xp_events WHERE guild=? AND source IN ('text','activity') AND stamp>=? AND stamp<=?",(guild,start,cutoff)).fetchall()

    def leaderboard(self,guild,week=None,page=1):
        if type(page) is not int or not 1<=page<=10000: raise ValueError("Invalid page")
        offset=(page-1)*10
        with connect_sqlite(self.path) as db:
            if week:
                return db.execute('SELECT user,points FROM periods WHERE guild=? AND week=? ORDER BY points DESC,user LIMIT 10 OFFSET ?',
                                  (guild,week,offset)).fetchall()
            return db.execute('SELECT user,total FROM xp WHERE guild=? ORDER BY total DESC,user LIMIT 10 OFFSET ?',(guild,offset)).fetchall()

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
            cfgrow=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
            if cfgrow and json.loads(cfgrow[0]).get('mode')=='active':
                db.execute('INSERT INTO role_jobs VALUES(?,?,?,?) ON CONFLICT(guild,user) DO UPDATE SET total=excluded.total',(guild,user,new,old))
            db.execute('INSERT INTO adjustments(guild,user,actor,delta,reason,stamp) VALUES(?,?,?,?,?,?)',
                       (guild,user,actor,new-old,reason,now))
        return old,new

    def rank_position(self,guild,user):
        with connect_sqlite(self.path) as db:
            row=db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,user)).fetchone()
            if row is None: return None
            return 1+db.execute('SELECT count(*) FROM xp WHERE guild=? AND (total>? OR (total=? AND user<?))',(guild,row[0],row[0],user)).fetchone()[0]

    def member_left(self,guild,user,now):
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM xp WHERE guild=? AND user=?',(guild,user)).fetchone()
            periods=db.execute('SELECT * FROM periods WHERE guild=? AND user=?',(guild,user)).fetchall()
            if row:
                db.execute('INSERT INTO departed_users(guild,user,stamp,snapshot) VALUES(?,?,?,?)',(guild,user,now,json.dumps(dict(xp=row,periods=periods))))
            for table in ('xp','periods','cooldowns','bindings','notice_state','role_jobs','repair_attempts'):
                db.execute(f'DELETE FROM {table} WHERE guild=? AND user=?',(guild,user))

    def claim_weekly_notice(self,guild,period):
        with connect_sqlite(self.path) as db:
            return bool(db.execute('INSERT OR IGNORE INTO weekly_notices VALUES(?,?)',(guild,period)).rowcount)

    def release_weekly_notice(self,guild,period):
        with connect_sqlite(self.path) as db:db.execute('DELETE FROM weekly_notices WHERE guild=? AND period=?',(guild,period))

    def pending_roles(self,guild,limit=5,now=None):
        import time
        now=time.time() if now is None else now
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT j.user,j.total,j.old_total FROM role_jobs j LEFT JOIN repair_attempts a ON j.guild=a.guild AND j.user=a.user WHERE j.guild=? AND coalesce(a.not_before,0)<=? ORDER BY coalesce(a.not_before,0),j.user LIMIT ?',(guild,now,limit)).fetchall()

    def mark_repaired(self,guild,user,total):
        with connect_sqlite(self.path) as db:
            removed=db.execute('DELETE FROM role_jobs WHERE guild=? AND user=? AND total=?',(guild,user,total)).rowcount
            if removed: db.execute('DELETE FROM repair_attempts WHERE guild=? AND user=?',(guild,user))

    def defer_repair(self,guild,user,now):
        with connect_sqlite(self.path) as db:
            row=db.execute('SELECT attempts FROM repair_attempts WHERE guild=? AND user=?',(guild,user)).fetchone()
            attempts=(row[0] if row else 0)+1
            delay=min(3600,30*2**min(attempts,7))
            db.execute('INSERT OR REPLACE INTO repair_attempts VALUES(?,?,?,?)',(guild,user,attempts,now+delay))

    def notice_level(self,guild,user,initial):
        with connect_sqlite(self.path) as db:
            db.execute('INSERT OR IGNORE INTO notice_state VALUES(?,?,?)',(guild,user,initial))
            return db.execute('SELECT level FROM notice_state WHERE guild=? AND user=?',(guild,user)).fetchone()[0]

    def mark_notice(self,guild,user,level):
        with connect_sqlite(self.path) as db:
            db.execute('INSERT INTO notice_state VALUES(?,?,?) ON CONFLICT(guild,user) DO UPDATE SET level=max(level,excluded.level)',(guild,user,level))

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
    # Real pet cards append level and species details after the owner line.
    pet=re.fullmatch(r"\*?([a-zA-Z0-9_.]+)'s pet attacking\*?",desc.strip().split('\n',1)[0])
    if pet and not mentions:
        return None,pet[1]
    return None


def render_notice(cfg,member,level,milestone):
    import discord
    template=cfg['level_templates'].get(str(milestone),cfg['announcement_template'])
    return template.replace('{user.ping}',member.mention).replace('{user}',discord.utils.escape_mentions(discord.utils.escape_markdown(member.display_name))).replace('{level}',str(level))[:1900]
