"""Read-only subsystem health; never opens a missing database for writing."""
import sqlite3
import json
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from core.storage_paths import STATS_DB


def database_health(path, queries):
    path=Path(path)
    if not path.is_file():return {'status':'未建立／未找到'}
    try:
        with closing(sqlite3.connect('file:'+quote(str(path))+'?mode=ro',uri=True,timeout=2)) as db:
            result={'status':db.execute('PRAGMA quick_check(1)').fetchone()[0]}
            for name,sql,args in queries:
                try:result[name]=db.execute(sql,args).fetchone()[0]
                except sqlite3.OperationalError:result[name]='未有資料表'
            return result
    except sqlite3.Error:return {'status':'讀取失敗，請查看管理日誌'}


def storage_health(level_path,guild,stats_path=None):
    return {
        '等級帳本':database_health(level_path,[
            ('待同步角色','SELECT count(*) FROM role_jobs WHERE guild=?',(guild,)),
            ('待查週榜',"SELECT count(*) FROM (SELECT p.key FROM settings s,json_each(s.value,'$.weekly_publications') p WHERE s.guild=?1 AND json_extract(p.value,'$.state') IN ('pending','uncertain','failed') UNION SELECT w.period FROM weekly_notices w WHERE w.guild=?1 AND NOT EXISTS(SELECT 1 FROM settings s,json_each(s.value,'$.weekly_publications') p WHERE s.guild=w.guild AND p.key=w.period))",(guild,))]),
        '社群紀錄':database_health(stats_path or STATS_DB,[
            ('待發通知',"SELECT count(*) FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope WHERE t.guild_id=? AND d.state='pending'",(guild,)),
            ('待查召人卡',"SELECT count(*) FROM squad_card_posts WHERE state='uncertain'",()),
            ('待收尾通知',"SELECT count(*) FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope JOIN squad_ended_sessions e ON e.session_id=d.session_id WHERE t.guild_id=? AND d.state='sent' AND d.message_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM squad_closed_notices n WHERE n.session_id=d.session_id AND n.scope=d.scope AND n.batch=d.batch AND n.message_id=d.message_id AND n.compact=1)",(guild,)),
            ('待查通知',"SELECT count(*) FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope WHERE t.guild_id=? AND d.state='uncertain'",(guild,))]),
    }


def review_history(level_path, guild, stats_path=None, warnings=None):
    """Bounded, read-only audit summary; no reasons or recipient lists exposed."""
    rows=[]
    warnings = warnings if warnings is not None else []
    path=Path(stats_path or STATS_DB)
    if path.is_file():
        try:
            with closing(sqlite3.connect('file:'+quote(str(path))+'?mode=ro',uri=True,timeout=2)) as db:
                for (raw,) in db.execute('SELECT audit FROM notification_reviews WHERE guild=? ORDER BY id DESC LIMIT 10',(guild,)):
                    rows.append({**json.loads(raw),'kind':'組隊通知'})
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc): warnings.append('組隊通知紀錄讀取失敗')
        except (sqlite3.Error,ValueError,TypeError):
            warnings.append('組隊通知紀錄讀取失敗')
    else:
        warnings.append('社群紀錄資料庫未建立／未找到')
    if level_path and Path(level_path).is_file():
        try:
            with closing(sqlite3.connect('file:'+quote(str(level_path))+'?mode=ro',uri=True,timeout=2)) as db:
                record=db.execute('SELECT value FROM settings WHERE guild=?',(guild,)).fetchone()
                if record:
                    rows.extend({**entry,'kind':'週榜'} for entry in json.loads(record[0]).get('notification_reviews',[])[-10:])
        except (sqlite3.Error,ValueError,TypeError):
            warnings.append('週榜操作紀錄讀取失敗')
    else:
        warnings.append('等級帳本未建立／未找到')
    valid=[r for r in rows if isinstance(r,dict) and isinstance(r.get('stamp'),(int,float)) and isinstance(r.get('actor'),int) and r.get('action') in ('sent','retry','cancel')]
    return sorted(valid,key=lambda r:r['stamp'],reverse=True)[:10]
