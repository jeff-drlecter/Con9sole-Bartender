"""Read-only aggregate preflight on the existing machine; never log in a Bot.

No migrations, data writes, credential output, member IDs or private activity totals.
A successful inspection is not deployment approval or live account acceptance.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing


def inspect(root, environ=None):
    environ = os.environ if environ is None else environ
    root = Path(root).resolve(strict=True)
    def path(name, override=None):
        result = Path(environ.get(override, root/name) if override else root/name).resolve(strict=True)
        result.relative_to(root)
        return result
    stats=path('community_stats.sqlite3','STATS_DB_PATH')
    with closing(sqlite3.connect(stats.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
            raise ValueError('Notification store integrity unavailable')
        columns={r[1] for r in db.execute('PRAGMA table_info(squad_interest_delivery)')}
        # Old receipts are unclassified even if today's preferences look similar.
        has_origins='origins' in columns
        sql="SELECT d.users,"+('d.origins' if has_origins else "'{}'")+",d.state FROM squad_interest_delivery d WHERE d.state IN ('pending','uncertain') AND NOT EXISTS (SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=d.session_id)"
        unknown=False;uncertain=False;pending=False
        for users,raw,state in db.execute(sql):
            origins=json.loads(raw)
            if not isinstance(origins,dict):raise ValueError('Invalid receipt provenance')
            unknown |= any(not isinstance(origins.get(str(uid)),dict) or any(type(origins[str(uid)].get(k)) is not bool for k in ('game','plan')) for uid in json.loads(users))
            uncertain |= state=='uncertain';pending |= state=='pending'
        card_unknown=bool(db.execute("SELECT 1 FROM squad_card_posts WHERE state='uncertain' LIMIT 1").fetchone())
    plans=json.loads(path('squad_plans.json').read_text())['plans']
    sessions=json.loads(path('squad_cards.json','SQUAD_CARDS_PATH').read_text())['sessions']
    if not isinstance(plans,dict) or not isinstance(sessions,dict):raise ValueError('Invalid activity store')
    active={'open','due','gathering','live'}
    return dict(inspection='completed_read_only',notification_store='integrity_checked',
        receipt_origin_column=has_origins,unclassified_active_receipts_present=unknown,
        pending_receipts_present=pending,uncertain_receipts_present=uncertain,
        uncertain_card_posts_present=card_unknown,
        active_plans_present=any(p['status'] in active for p in plans.values()),
        plan_posting_or_voice_attempt_present=any(p['status']=='posting' or (p['status'] in active and p.get('voice_attempt')) for p in plans.values()),
        plan_event_unresolved_present=any(p.get('delivery',{}).get('event',{}).get('state') in {'creating','unknown','syncing','unknown_sync','conflict'} for p in plans.values()),
        host_notice_unresolved_present=any(n.get('state') in {'queued','sending','unknown'} for p in plans.values() for n in p.get('delivery',{}).get('notices',[])),
        assembly_delivery_unresolved_present=any(
            a.get('retired') or a.get('unresolved') or
            any(a.get(kind, {}).get('state') in {'requested', 'sending', 'unknown'} for kind in ('due', 'nudge'))
            for a in (p.get('assembly', {}) for p in plans.values())),
        persisted_active_voice_sessions_present=any(s.get('ended') is None for s in sessions.values()),
        voice_evidence='persisted Bot state; not a live Discord voice-state snapshot',
        legacy_receipt_policy='preserve and quarantine unclassified receipts; never guess origins or replay uncertain',
        deployment_approved=False)


def require_idle(result):
    """A deployment guard, not a substitute for identity acceptance.

    Refuse even valid pending work: this release must not replace a dispatcher
    while delivery or a voice/plan operation is in progress. Missing evidence
    is blocked rather than interpreted as an empty store.
    """
    flags = ('unclassified_active_receipts_present', 'pending_receipts_present',
             'uncertain_receipts_present', 'uncertain_card_posts_present',
             'active_plans_present', 'plan_posting_or_voice_attempt_present',
             'plan_event_unresolved_present', 'host_notice_unresolved_present',
             'assembly_delivery_unresolved_present', 'persisted_active_voice_sessions_present')
    blocked = [key for key in flags if result.get(key) is not False]
    if result.get('notification_store') != 'integrity_checked':
        blocked.append('notification_store')
    if result.get('inspection') != 'completed_read_only':
        blocked.append('inspection')
    if blocked:
        raise ValueError('Deployment held: ' + ', '.join(blocked))


if __name__=='__main__':
    try:
        result=inspect(os.getenv('DRINK_DATA_DIR') or '/data')
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
        raise SystemExit('Readiness inspection unavailable; deployment remains unverified') from None
    print(json.dumps(result,ensure_ascii=False))
    if '--require-idle' in sys.argv:
        try:
            require_idle(result)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
