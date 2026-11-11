"""Invite attribution and rewards share the XP database for atomic, durable credits."""
from __future__ import annotations
import json
from datetime import datetime
from features.community_levels import calendar, TZ
from core.sqlite_storage import connect_sqlite

SOURCE_CHANNELS = {
    'threads-invitation': 'Threads', 'discord-invitation': 'Discord',
    'ttv-invitation': 'Twitch', 'psn-invitation': 'PSN', 'ig-invitation': 'Instagram',
    'wwm-invitation': 'WWM', 'yt-invitation': 'YouTube', 'lihkg-invitation': 'LIHKG',
    'rules': '其他：rules', '接待大堂（sorting-hat）': '其他：接待大堂',
    '🆔留game-tag（非聊天）': '其他：留 game tag',
}


# Explicit publication labels take precedence over landing-channel names.
# These are public invitation codes, never personal referral links.
SOURCE_INVITE_LABELS = {'rg7xz8gnJp': 'LIHKG'}


def source_invites(invites, personal_codes):
    entries = []
    for invite in invites:
        if invite.code in personal_codes:
            continue
        label = SOURCE_INVITE_LABELS.get(invite.code)
        if label is None and invite.channel:
            label = SOURCE_CHANNELS.get(invite.channel.name)
        if label is not None:
            entries.append((label, invite))
    return entries


INVITE_XP = 25


def match_batch(before, after, count):
    """Only attribute when a single code explains the entire observed join batch."""
    changes = [(code, uses-before.get(code, 0)) for code, uses in after.items()
               if uses > before.get(code, 0)]
    if len(changes) == 1 and changes[0][1] == count:
        return changes[0][0]
    return None


class Referrals:
    def __init__(self, ledger):
        self.path = ledger.path
        with connect_sqlite(self.path) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS referral_links(guild INTEGER,user INTEGER,code TEXT NOT NULL,
              PRIMARY KEY(guild,user),UNIQUE(guild,code));
            CREATE TABLE IF NOT EXISTS referral_seen(guild INTEGER,user INTEGER,PRIMARY KEY(guild,user));
            CREATE TABLE IF NOT EXISTS referral_joins(guild INTEGER,user INTEGER,joined REAL,
              code TEXT,inviter INTEGER,fresh INTEGER NOT NULL,left_at REAL,
              PRIMARY KEY(guild,user,joined));
            CREATE TABLE IF NOT EXISTS referral_rewards(guild INTEGER,user INTEGER,inviter INTEGER,
              amount INTEGER,stamp REAL,PRIMARY KEY(guild,user));
            ''')

    def seed(self, guild, users):
        with connect_sqlite(self.path) as db:
            db.executemany('INSERT OR IGNORE INTO referral_seen VALUES(?,?)', ((guild,u) for u in users))
            db.execute('INSERT OR IGNORE INTO referral_seen SELECT guild,user FROM departed_users WHERE guild=?',(guild,))
            db.execute('INSERT OR IGNORE INTO referral_seen SELECT guild,user FROM xp WHERE guild=?',(guild,))
            row=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
            known=json.loads(row[0]).get('member_lifecycles',{}) if row else {}
            db.executemany('INSERT OR IGNORE INTO referral_seen VALUES(?,?)',((guild,int(u)) for u in known))

    def link(self, guild, user):
        with connect_sqlite(self.path) as db:
            row=db.execute('SELECT code FROM referral_links WHERE guild=? AND user=?',(guild,user)).fetchone()
            return row[0] if row else None

    def personal_codes(self, guild):
        with connect_sqlite(self.path) as db:
            return {r[0] for r in db.execute('SELECT code FROM referral_links WHERE guild=?',(guild,))}

    def save_link(self, guild, user, code):
        with connect_sqlite(self.path) as db:
            db.execute('INSERT INTO referral_links VALUES(?,?,?) ON CONFLICT(guild,user) DO UPDATE SET code=excluded.code',(guild,user,code))

    def joined(self, guild, user, joined, code):
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            fresh=db.execute('INSERT OR IGNORE INTO referral_seen VALUES(?,?)',(guild,user)).rowcount
            row=db.execute('SELECT user FROM referral_links WHERE guild=? AND code=?',(guild,code)).fetchone()
            inviter=row[0] if row and row[0]!=user else None
            db.execute('INSERT OR IGNORE INTO referral_joins VALUES(?,?,?,?,?,?,NULL)',(guild,user,joined,code,inviter,fresh))

    def departed(self, guild, user, joined, now):
        with connect_sqlite(self.path) as db:
            db.execute('UPDATE referral_joins SET left_at=? WHERE guild=? AND user=? AND joined=?',(now,guild,user,joined))

    def reward(self, guild, user, joined, now):
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT inviter FROM referral_joins WHERE guild=? AND user=? AND joined=? AND fresh=1 AND left_at IS NULL',(guild,user,joined)).fetchone()
            if not row or not row[0]:return None
            inviter=row[0]
            raw=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
            cfg=json.loads(raw[0]) if raw else {}
            if cfg.get('mode')!='active' or now<cfg.get('cutover_at',0):return None
            if not db.execute('INSERT OR IGNORE INTO referral_rewards VALUES(?,?,?,?,?)',(guild,user,inviter,INVITE_XP,now)).rowcount:return None
            event=f'referral:{user}'
            db.execute('INSERT INTO xp_events VALUES(?,?,?,?,?,?)',(guild,event,inviter,'invite',INVITE_XP,now))
            db.execute('INSERT OR IGNORE INTO xp(guild,user) VALUES(?,?)',(guild,inviter))
            old=db.execute('SELECT total FROM xp WHERE guild=? AND user=?',(guild,inviter)).fetchone()[0]
            db.execute('UPDATE xp SET total=total+?,activity=activity+? WHERE guild=? AND user=?',(INVITE_XP,INVITE_XP,guild,inviter))
            db.execute('INSERT INTO periods VALUES(?,?,?,?) ON CONFLICT(guild,user,week) DO UPDATE SET points=points+excluded.points',(guild,inviter,calendar(now)[1],INVITE_XP))
            db.execute('INSERT INTO role_jobs VALUES(?,?,?,?) ON CONFLICT(guild,user) DO UPDATE SET total=excluded.total',(guild,inviter,old+INVITE_XP,old))
            return inviter,(old,old+INVITE_XP)

    def pending(self, guild):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT j.user,j.joined,j.inviter FROM referral_joins j LEFT JOIN referral_rewards r ON r.guild=j.guild AND r.user=j.user WHERE j.guild=? AND j.fresh=1 AND j.inviter IS NOT NULL AND j.left_at IS NULL AND r.user IS NULL',(guild,)).fetchall()

    def board(self, guild, start=0):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT inviter,COUNT(*),SUM(amount) FROM referral_rewards WHERE guild=? AND stamp>=? GROUP BY inviter ORDER BY COUNT(*) DESC,inviter',(guild,start)).fetchall()

    def history(self, guild, user):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT joined,code,inviter,fresh,left_at FROM referral_joins WHERE guild=? AND user=? ORDER BY joined DESC LIMIT 10',(guild,user)).fetchall()

    def sources(self, guild, start=0):
        with connect_sqlite(self.path) as db:
            return db.execute('SELECT code,COUNT(*),COUNT(DISTINCT user),SUM(left_at IS NULL) FROM referral_joins WHERE guild=? AND joined>=? GROUP BY code ORDER BY COUNT(*) DESC',(guild,start)).fetchall()


def month_start(now):
    return datetime.fromtimestamp(now,TZ).replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
