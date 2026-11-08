"""Durable title-role mappings and a queue committed with title selection."""
import json
import time
import uuid
from features import drink_storage as storage


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS title_role_settings(guild INTEGER PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS title_role_jobs(guild INTEGER,user INTEGER,revision TEXT,attempts INTEGER DEFAULT 0,
      retry_at REAL DEFAULT 0,error TEXT DEFAULT '',PRIMARY KEY(guild,user));
    CREATE TABLE IF NOT EXISTS title_role_audit(id INTEGER PRIMARY KEY,guild INTEGER,actor INTEGER,action TEXT,value TEXT,stamp REAL);
    ''')


def initialize():
    storage.init_drink_events_db()
    with storage.connect_sqlite(storage.STATS_DB) as db:schema(db)


def enqueue_in(db,guild,user):
    if guild is None:return
    # No DDL here: preserve the caller's title-selection transaction.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='title_role_jobs'").fetchone():return
    db.execute('INSERT INTO title_role_jobs(guild,user,revision) VALUES(?,?,?) ON CONFLICT(guild,user) DO UPDATE SET revision=excluded.revision,attempts=0,retry_at=0,error=\'\'',
               (guild,user,uuid.uuid4().hex))


def settings(guild):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        row=db.execute('SELECT value FROM title_role_settings WHERE guild=?',(guild,)).fetchone()
    return json.loads(row[0]) if row else dict(mapping={},managed=[],version='initial')


def managed_roles(guild):
    with storage.connect_sqlite(storage.STATS_DB) as db:
        row=db.execute('SELECT value FROM title_role_settings WHERE guild=?',(guild,)).fetchone()
    return set(json.loads(row[0])['managed']) if row else set()


def bind(guild,key,role,actor):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM title_role_settings WHERE guild=?',(guild,)).fetchone()
        cfg=json.loads(row[0]) if row else dict(mapping={},managed=[])
        if role and any(k!=key and rid==role for k,rid in cfg['mapping'].items()):raise ValueError('呢個 Role 已綁定另一個稱號。')
        if role:
            cfg['mapping'][key]=role;cfg['managed']=sorted(set(cfg['managed'])|{role})
        else:cfg['mapping'].pop(key,None)
        cfg['version']=uuid.uuid4().hex
        cfg.get('provisioning',{}).pop(key,None)
        db.execute('INSERT OR REPLACE INTO title_role_settings VALUES(?,?)',(guild,json.dumps(cfg)))
        db.execute('INSERT INTO title_role_audit(guild,actor,action,value,stamp) VALUES(?,?,?,?,?)',
                   (guild,actor,'bind',json.dumps(dict(title=key,role=role)),time.time()))
    return cfg


def begin_provision(guild,key,actor):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM title_role_settings WHERE guild=?',(guild,)).fetchone()
        cfg=json.loads(row[0]) if row else dict(mapping={},managed=[],version='initial')
        pending=cfg.setdefault('provisioning',{})
        if key in pending:raise ValueError('上次建立 Role 結果未確認；請先核對伺服器角色，再選擇綁定，避免重複建立。')
        pending[key]=dict(actor=actor,stamp=time.time())
        db.execute('INSERT OR REPLACE INTO title_role_settings VALUES(?,?)',(guild,json.dumps(cfg)))


def enqueue(guild,user):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:enqueue_in(db,guild,user)


def pending(guild,limit=5):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        return db.execute('SELECT user,revision FROM title_role_jobs WHERE guild=? AND retry_at<=? ORDER BY retry_at,user LIMIT ?',
                          (guild,time.time(),limit)).fetchall()


def finish(guild,user,revision,error=None):
    with storage.connect_sqlite(storage.STATS_DB) as db:
        if error:
            db.execute('UPDATE title_role_jobs SET attempts=attempts+1,retry_at=?,error=? WHERE guild=? AND user=? AND revision=?',
                       (time.time()+60,error[:200],guild,user,revision))
        else:db.execute('DELETE FROM title_role_jobs WHERE guild=? AND user=? AND revision=?',(guild,user,revision))


def selected(guild,user):
    with storage.connect_sqlite(storage.STATS_DB) as db:
        row=db.execute('SELECT milestone_id FROM drink_collection_titles WHERE guild_key=? AND user_id=?',(str(guild),user)).fetchone()
    return row[0] if row else None


def selections(guild):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        return dict(db.execute('SELECT user_id,milestone_id FROM drink_collection_titles WHERE guild_key=?',(str(guild),)))


def queue_status(guild,user=None):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        if user is not None:return db.execute('SELECT error FROM title_role_jobs WHERE guild=? AND user=?',(guild,user)).fetchone()
        return db.execute('SELECT user,error FROM title_role_jobs WHERE guild=? ORDER BY user',(guild,)).fetchall()


def enqueue_batch(guild,users,actor,plan):
    initialize()
    with storage.connect_sqlite(storage.STATS_DB) as db:
        db.execute('BEGIN IMMEDIATE')
        for user in users:enqueue_in(db,guild,user)
        db.execute('INSERT INTO title_role_audit(guild,actor,action,value,stamp) VALUES(?,?,?,?,?)',
                   (guild,actor,'bulk_sync',json.dumps(plan),time.time()))


def safe_role(guild,role,levels=()):
    me=guild.me
    return bool(role and me and me.guild_permissions.manage_roles and role.id not in levels
                and not role.is_default() and not role.managed and role<me.top_role
                and role.permissions.value==0 and role.colour.value==0 and not role.hoist and not role.mentionable)
