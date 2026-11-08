"""Read-only subsystem health; never opens a missing database for writing."""
import sqlite3
from pathlib import Path
from urllib.parse import quote
from core.storage_paths import STATS_DB


def database_health(path, queries):
    path=Path(path)
    if not path.is_file():return {'status':'未建立／未找到'}
    try:
        with sqlite3.connect('file:'+quote(str(path))+'?mode=ro',uri=True,timeout=2) as db:
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
            ('待查週榜',"SELECT count(*) FROM settings s,json_each(s.value,'$.weekly_publications') p WHERE s.guild=? AND json_extract(p.value,'$.state') IN ('pending','uncertain')",(guild,))]),
        '社群紀錄':database_health(stats_path or STATS_DB,[
            ('待發通知',"SELECT count(*) FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope WHERE t.guild_id=? AND d.state='pending'",(guild,)),
            ('待查召人卡',"SELECT count(*) FROM squad_card_posts WHERE state='uncertain'",()),
            ('待查通知',"SELECT count(*) FROM squad_interest_delivery d JOIN squad_interest_topics t ON t.scope=d.scope WHERE t.guild_id=? AND d.state='uncertain'",(guild,))]),
    }
