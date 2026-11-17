"""Private, offline growth diagnostics; never run in public Actions logs.

Standard library only: no Bot login, imports of stores, initialization, migration,
repair, checkpoint, backup, network, or data writes. Read the live SQLite database
with its WAL in place, or an existing consistent SQLite-backup-API snapshot.
Each database has one read transaction; JSON/database snapshots are NOT atomic
across stores. Output contains private aggregates and route channel IDs, no
member IDs, display names, session IDs, message text, or credentials.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time


@contextmanager
def read_database(path):
    # mode=ro must not silently create a missing DB; never use immutable on WAL.
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def scoped_path(root, name, override=None):
    path = Path(override) if override else root / name
    path = path.resolve()
    path.relative_to(root)  # Outside-root overrides need separate explicit review.
    return path


def summary(db, table, stamp):
    # Identifiers are fixed by the caller below, never CLI data.
    if not db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone():
        return {'status': 'table_unavailable'}
    n, first, last = db.execute(f'SELECT COUNT(*),MIN({stamp}),MAX({stamp}) FROM {table}').fetchone()
    return dict(status='read', rows=n, first=first, last=last)


def outcomes(path, guild, start, end, as_of, excluded):
    with read_database(path) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            return {'status': 'integrity_failed'}
        result = {'status': 'read', 'tables': {table: summary(db, table, stamp) for table, stamp in (
            ('outcome_sessions', 'first_seen'), ('outcome_attendance', 'first_seen'),
            ('outcome_visits', 'first_seen'), ('outcome_coverage', 'start'),
            ('outcome_observer_runs', 'started'), ('outcome_meta', 'stamp'))}}
        result['meta'] = dict(db.execute("SELECT key,stamp FROM outcome_meta WHERE key IN ('since','natural_since','coplay_since')"))
        result['session_groups'] = [dict(zip(('target_guild', 'test', 'origin', 'source_missing', 'rows', 'first', 'last'), row))
            for row in db.execute("""SELECT guild=?,CASE WHEN test=0 THEN 'no' WHEN test=1 THEN 'yes' ELSE 'unknown' END,
            CASE WHEN origin IN ('linked','natural') THEN origin ELSE 'unknown' END,
            (source_channel IS NULL OR voice_channel IS NULL OR origin IS NULL),COUNT(*),MIN(first_seen),MAX(first_seen)
            FROM outcome_sessions GROUP BY 1,2,3,4""", (guild,))]
        result['attendance_groups'] = [dict(zip(('target_guild', 'test', 'origin', 'source_missing', 'rows', 'first', 'last'), row))
            for row in db.execute("""SELECT a.guild=?,CASE WHEN s.test=0 THEN 'no' WHEN s.test=1 THEN 'yes' ELSE 'unknown' END,
            CASE WHEN s.origin IN ('linked','natural') THEN s.origin ELSE 'unknown' END,
            (s.source_channel IS NULL OR s.voice_channel IS NULL OR s.origin IS NULL),COUNT(*),MIN(a.first_seen),MAX(a.first_seen)
            FROM outcome_attendance a LEFT JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session
            GROUP BY 1,2,3,4""", (guild,))]
        eligibility = "s.test=0 AND s.origin IN ('linked','natural') AND s.source_channel IS NOT NULL AND s.voice_channel IS NOT NULL"
        params = []
        if excluded:
            marks = ','.join('?' for _ in excluded)
            eligibility += f' AND s.source_channel NOT IN ({marks}) AND s.voice_channel NOT IN ({marks})'
            params = list(excluded) * 2
        result['window_attendance'] = dict(zip(('raw_rows', 'distinct_accounts'), db.execute(
            'SELECT COUNT(*),COUNT(DISTINCT user) FROM outcome_attendance WHERE guild=? AND first_seen>=? AND first_seen<?',
            (guild, start, end)).fetchone()))
        result['window_eligible_attendance'] = dict(zip(('rows', 'distinct_accounts'), db.execute(
            'SELECT COUNT(*),COUNT(DISTINCT a.user) FROM outcome_attendance a JOIN outcome_sessions s '
            'ON s.guild=a.guild AND s.session=a.session WHERE a.guild=? AND a.first_seen>=? AND a.first_seen<? AND ' + eligibility,
            (guild, start, end, *params)).fetchone()))
        result['undated_attendance'] = db.execute('SELECT COUNT(*) FROM outcome_attendance WHERE guild=? AND first_seen IS NULL', (guild,)).fetchone()[0]
        result['orphan_attendance'] = db.execute('SELECT COUNT(*) FROM outcome_attendance a LEFT JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session WHERE a.guild=? AND s.session IS NULL', (guild,)).fetchone()[0]
        result['future_attendance'] = db.execute('SELECT COUNT(*) FROM outcome_attendance WHERE guild=? AND first_seen>?', (guild, as_of)).fetchone()[0]
        # Earliest coverage is evidence of recorded coverage, not feature activation.
        result['coverage_range'] = dict(zip(('rows', 'first', 'last'), db.execute(
            'SELECT COUNT(*),MIN(start),MAX(end) FROM outcome_coverage WHERE guild=?', (guild,)).fetchone()))
        intervals = []
        invalid = 0
        for a, b in db.execute('SELECT start,end FROM outcome_coverage WHERE guild=? ORDER BY start,end', (guild,)):
            if a is None or b is None or b < a:
                invalid += 1
                continue
            a, b = max(a, start), min(b, end)
            if b < a:
                continue
            if intervals and a <= intervals[-1][1]:
                intervals[-1][1] = max(b, intervals[-1][1])
            else:
                intervals.append([a, b])
        result['coverage_window'] = dict(union_seconds=sum(b-a for a,b in intervals), segments=len(intervals), invalid_rows=invalid)
        run = db.execute('SELECT started,last_success,failures FROM outcome_observer_runs ORDER BY started DESC,run DESC LIMIT 1').fetchone()
        result['observer'] = dict(latest_run=dict(zip(('started','last_success','failures'), run)) if run else None,
            all_runs_failures=db.execute('SELECT COALESCE(SUM(failures),0) FROM outcome_observer_runs').fetchone()[0],
            failure_timestamps='not_recorded', guild_scope='run table has no guild column',
            current_cog_health='not_observable_from_disk')
        raw = result['tables']['outcome_attendance']['rows']
        selected = result['window_attendance']['raw_rows']
        eligible = result['window_eligible_attendance']['rows']
        result['diagnostic'] = ('raw_attendance_empty' if raw == 0 else
            'no_target_guild_window_rows' if selected == 0 else
            'target_rows_all_ineligible' if eligible == 0 else 'eligible_rows_exist_compare_first_observation_anchors')
        result['limitations'] = ['eligible rows are not first-observation cohorts or retention',
            'visits must also be unioned for activity baselines', 'unregistered test accounts not excluded',
            'no session is compatible with a successful heartbeat', 'skipped session history was not recorded']
        return result


def states(cards_path, plans_path, guild):
    cards = json.loads(cards_path.read_text())
    plans = json.loads(plans_path.read_text())['plans']
    if not isinstance(cards['sessions'], dict) or not isinstance(plans, dict):
        raise ValueError('Invalid state')
    settings = cards.get('settings', {})
    routes = dict(settings.get('routes', {}))
    if 'category' in settings:
        routes = {str(settings['category']): settings['destination'], **routes}
    groups = Counter()
    for session in cards['sessions'].values():
        plan = plans.get(session.get('plan_id'))
        if session.get('ended') is not None:
            origin = 'ended'
        elif session.get('plan_id'):
            origin = 'linked' if (plan and plan.get('guild') == guild and plan.get('id') == session['plan_id']
                and plan.get('status') == 'live' and plan.get('session') == session.get('id')) else 'unknown'
        else:
            origin = 'natural' if session.get('id') and session.get('message') else 'waiting'
        # Explicit plan flags only; live channel/category and exclusion IDs need
        # a separate authorised Discord GET, never inferred from this snapshot.
        test = bool(plan and (plan.get('analytics_test') or plan.get('test') or plan.get('is_test')))
        groups[(origin, bool(session.get('message')), bool(session.get('plan_id')), test)] += 1
    return dict(routes=[dict(category=int(k), destination=int(v)) for k,v in sorted(routes.items())],
        session_groups=[dict(origin=k[0], message_present=k[1], plan_link_present=k[2], explicit_plan_test=k[3], rows=n)
            for k,n in sorted(groups.items())],
        plans=dict(rows=len(plans),target_guild=sum(p.get('guild') == guild for p in plans.values()),
            undated=sum(p.get('guild') == guild and p.get('created_at') is None for p in plans.values())),
        live_channels_permissions_members='unverified; disk is not live Discord')


def card_posts(path):
    with read_database(path) as db:
        return dict(status='read', scope='table has no guild column', groups=[dict(zip(
            ('state','message_present','rows','first','last'), row)) for row in db.execute("""
            SELECT CASE WHEN state IN ('sent','uncertain','rejected') THEN state ELSE 'other' END,
            message_id IS NOT NULL,COUNT(*),MIN(stamp),MAX(stamp) FROM squad_card_posts GROUP BY 1,2""")])


def referral_window(path, guild, start, end, codes):
    with read_database(path) as db:
        personal = {r[0] for r in db.execute('SELECT code FROM referral_links WHERE guild=?', (guild,))}
        requested = list(dict.fromkeys(codes))
        allowed = [c for c in requested if c not in personal]
        rows = []
        for index, code in enumerate(requested):
            values = db.execute('SELECT COUNT(*),COUNT(DISTINCT user),SUM(fresh=0) FROM referral_joins WHERE guild=? AND joined>=? AND joined<? AND code=?', (guild,start,end,code)).fetchone()
            rows.append(dict(requested_code_index=index, personal=code in personal,
                events=values[0], distinct_accounts=values[1], recorded_reentries=values[2] or 0))
        marks = ','.join('?' for _ in allowed) or 'NULL'
        union = db.execute(f'SELECT COUNT(*),COUNT(DISTINCT user) FROM referral_joins WHERE guild=? AND joined>=? AND joined<? AND code IN ({marks})', (guild,start,end,*allowed)).fetchone()
        unknown = db.execute('SELECT COUNT(*) FROM referral_joins WHERE guild=? AND joined>=? AND joined<? AND code IS NULL', (guild,start,end)).fetchone()[0]
        return dict(status='read', requested_codes=rows, nonpersonal_union=dict(events=union[0],distinct_accounts=union[1]),
            unknown_source_events=unknown, code_label='requires current authorised invite-list GET',
            qualification='account events only; Bot/test registry/current membership/first participation not verified')


def inspect(root, guild, start, end, as_of, *, environ=None, codes=()):
    if not all(math.isfinite(v) for v in (start,end,as_of)) or not start < end <= as_of or end-start > 90*86400:
        raise ValueError('Require a positive window of at most 90 days ending no later than as_of')
    env = os.environ if environ is None else environ
    root = Path(root).resolve(strict=True)
    excluded = tuple(sorted({int(v) for v in env.get('OUTCOMES_TEST_CHANNEL_IDS','').split(',') if v.strip()}))
    commit = env.get('APP_COMMIT', '')
    result = dict(schema_version=1, captured_started_at=time.time(),
        runtime_app_commit=commit if re.fullmatch('[0-9a-f]{40}',commit) else None,
        root=str(root), window=dict(start=start,end=end,as_of=as_of,right_exclusive=True),
        excluded_channel_count=len(excluded), consistency='one read transaction per database; not cross-store atomic',
        membership_enumeration='not_performed', live_routes_permissions='not_performed')
    operations = {
        'outcomes': lambda: outcomes(scoped_path(root,'community_outcomes.sqlite3'),guild,start,end,as_of,excluded),
        'state': lambda: states(scoped_path(root,'squad_cards.json',env.get('SQUAD_CARDS_PATH')),
            scoped_path(root,'squad_plans.json'),guild),
        'card_posts': lambda: card_posts(scoped_path(root,'community_stats.sqlite3',env.get('STATS_DB_PATH'))),
        'referrals': lambda: referral_window(scoped_path(root,'community_levels.sqlite3'),guild,start,end,codes),
    }
    for key, operation in operations.items():
        try:
            result[key] = operation()
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
            # No raw exception/path/member/code data in error output; never zero.
            result[key] = {'status': 'unavailable_or_incompatible', 'rows': None}
    result['captured_finished_at'] = time.time()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--guild', required=True, type=int)
    parser.add_argument('--start', required=True, type=float)
    parser.add_argument('--end', required=True, type=float)
    parser.add_argument('--as-of', required=True, type=float)
    parser.add_argument('--public-code', action='append', default=[])
    args = parser.parse_args()
    print(json.dumps(inspect(args.data_dir,args.guild,args.start,args.end,args.as_of,codes=args.public_code), ensure_ascii=False, indent=2))
