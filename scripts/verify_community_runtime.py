"""GET/read-only runtime verification. Output only operational configuration.

Never print member IDs, event contents, attendance/XP totals or private statistics.
No store initialization, Bot login, messages, role edits or policy writes.
Each SQLite read has its own snapshot; not a global cross-store transaction.
"""
import json
import os
from pathlib import Path
import sqlite3
import time

GUILD = 626378673523785731
SETTING_KEYS = ('mode', 'text_cooldown', 'activity_cooldown', 'activity_daily_cap',
                'voice_interval', 'voice_xp', 'booster_multiplier')
ENV_KEYS = ('STORE_NEWS_PUBLIC', 'RSS_PERSONAL_PUBLIC', 'RSS_CATEGORY_DELIVERY',
            'RSS_DELIVERY_SOURCES', 'HELPER_SANDBOX')


def read_db(path, queries):
    if not path.is_file():
        return None
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Runtime database integrity check failed')
        return [db.execute(sql, args).fetchall() for sql, args in queries]


def verify(root, environ, now):
    result = dict(configuration={k: environ.get(k, 'unset') for k in ENV_KEYS})
    result['notification_preference_exp']='disabled by code; historical XP retained'
    # Only explicit stored policy; absence is not silently reported as the default.
    settings = read_db(root/'community_levels.sqlite3', [
        ('SELECT value FROM settings WHERE guild=?', (GUILD,))])
    cfg = json.loads(settings[0][0][0]) if settings and settings[0] else {}
    result['stored_exp_policy'] = {k: cfg.get(k, 'not explicitly stored') for k in SETTING_KEYS}
    path = Path(environ.get('RSS_DIGEST_CONFIG', 'docs/rss_production.json'))
    if path.is_file():
        raw = json.loads(path.read_text())
        result['digest_policy'] = {k: raw.get(k) for k in ('enabled','simulation','max_items','include_any','exclude_any','boost_any')}
    plans_path=root/'squad_plans.json'
    if plans_path.is_file():
        plans=json.loads(plans_path.read_text())['plans'].values()
        # Do not output even anonymous plan/attendance counts to public CI logs.
        assert all(isinstance(p.get('start'), (int,float)) for p in plans), 'Invalid plan times'
        result['plan_store']='readable; no private statistics emitted'
    else:
        result['plan_store']='unavailable'
    outcomes=root/'community_outcomes.sqlite3'
    rows=read_db(outcomes,[('SELECT name FROM sqlite_master WHERE type=?',('table',))])
    if rows is not None:
        names={r[0] for r in rows[0]}
        assert {'outcome_sessions','outcome_attendance','outcome_meta'} <= names
        if 'outcome_coplay' in names:
            start=read_db(outcomes,[("SELECT stamp FROM outcome_meta WHERE key='coplay_since'",())])
            assert start[0] and start[0][0][0] <= now, 'Missing participation observation start'
            result['coparticipation']='same pair / same room / 120 observed seconds; durable milestones only'
        else:
            result['coparticipation']='previous schema; unavailable'
        if 'outcome_observer_runs' in names:
            values=read_db(outcomes,[('SELECT MAX(last_success) FROM outcome_observer_runs',())])
            stamp=values[0][0][0]
            result['outcome_observer']='recent' if stamp and 0 <= now-stamp < 120 else 'not yet observed / unavailable'
        else:
            result['outcome_observer']='previous schema; no coverage heartbeat'
        result['outcome_store']='integrity verified; private statistics withheld'
    else:
        result['outcome_store']='unavailable'
    return result


if __name__ == '__main__':
    result=verify(Path(os.getenv('DRINK_DATA_DIR','/data')),os.environ,time.time())
    assert result.get('outcome_observer') == 'recent', 'Outcome observer has no recent successful cycle'
    assert result.get('coparticipation','').startswith('same pair'), 'Participation schema unavailable'
    print(json.dumps(result,ensure_ascii=False))
