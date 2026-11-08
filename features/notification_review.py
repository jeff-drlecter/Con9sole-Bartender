"""Scoped, compare-and-swap administration of notification outcomes."""
import json
import time
import uuid
from core.sqlite_storage import connect_sqlite
from features import squad_interest as interests


def subscription_rows(guild):
    interests.initialize()
    with connect_sqlite(interests.STATS_DB) as db:
        return [dict(kind='subscription',session=session,scope=scope,batch=batch,
                     users=json.loads(users),state=state,revision=revision,label=label,context=json.loads(context))
                for session,scope,batch,users,state,revision,label,context in db.execute(
                    "SELECT d.session_id,d.scope,d.batch,d.users,d.state,d.revision,t.label,d.context FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope WHERE t.guild_id=? AND d.state IN ('pending','uncertain') ORDER BY d.session_id,d.batch",(guild,))]


def weekly_rows(ledger,guild):
    publications=ledger.settings(guild).get('weekly_publications',{})
    with connect_sqlite(ledger.path) as db:
        for period, in db.execute('SELECT period FROM weekly_notices WHERE guild=?',(guild,)):
            publications.setdefault(period,dict(state='uncertain',attempt='legacy'))
    return [dict(kind='weekly',period=period,label=period,state=entry['state'],revision=entry['attempt'])
            for period,entry in publications.items()
            if entry['state'] in ('pending','uncertain','failed')]


def resolve(ledger,guild,row,action,actor,reason,message_id=None):
    if action not in ('sent','retry','cancel') or type(actor) is not int or actor<=0 or not reason.strip() or len(reason)>200:
        raise ValueError('需要有效操作及核對原因（最多 200 字）。')
    if action=='sent' and (type(message_id) is not int or message_id<=0):
        raise ValueError('需要核對實際通知訊息。')
    audit=dict(actor=actor,reason=reason,action=action,message=message_id,stamp=time.time())
    if row['kind']=='subscription':
        if row['state'] not in ('pending','uncertain'):return False
        interests.initialize()
        with connect_sqlite(interests.STATS_DB) as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE squad_interest_delivery SET state=?,revision=?,retry_at=0,message_id=? WHERE session_id=? AND scope=? AND batch=? AND state=? AND revision=? AND EXISTS(SELECT 1 FROM squad_interest_topics WHERE scope=? AND guild_id=?)",
                ({'sent':'sent','retry':'pending','cancel':'cancelled'}[action],uuid.uuid4().hex,message_id,row['session'],row['scope'],row['batch'],row['state'],row['revision'],row['scope'],guild)).rowcount
            if not changed:return False
            db.execute('CREATE TABLE IF NOT EXISTS notification_reviews(id INTEGER PRIMARY KEY,guild INTEGER,identity TEXT,audit TEXT)')
            db.execute('INSERT INTO notification_reviews(guild,identity,audit) VALUES(?,?,?)',
                       (guild,json.dumps([row['session'],row['scope'],row['batch']]),json.dumps(audit)))
        return True
    if row['kind']!='weekly':raise ValueError('Unknown notification kind')
    if action=='cancel':raise ValueError('週榜只提供核對已送出或重試。')
    if row['state'] not in ('pending','uncertain','failed'):return False
    with connect_sqlite(ledger.path) as db:
        db.execute('BEGIN IMMEDIATE')
        raw=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
        if not raw:return False
        cfg=json.loads(raw[0]);entries=cfg.get('weekly_publications',{});current=entries.get(row['period'])
        if current is None and row['revision']=='legacy' and db.execute('SELECT 1 FROM weekly_notices WHERE guild=? AND period=?',(guild,row['period'])).fetchone():
            current=dict(state='uncertain',attempt='legacy')
        if not current or current['attempt']!=row['revision'] or current['state']!=row['state']:return False
        if current['state']=='sent':return False
        entries[row['period']]={**current,'state':'sent' if action=='sent' else 'failed',
                               'attempt':uuid.uuid4().hex,'message':message_id}
        cfg['weekly_publications']=entries
        cfg.setdefault('notification_reviews',[]).append({**audit,'period':row['period']})
        db.execute('UPDATE settings SET value=? WHERE guild=?',(json.dumps(cfg),guild))
    return True
