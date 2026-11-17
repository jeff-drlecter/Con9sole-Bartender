"""Private, read-only account baseline. No rewards, census cache or backfilling.

Member IDs exist only in the request's memory; public results contain aggregates.
Attendance is observed non-Bot account presence, never completed gameplay or people.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from pathlib import Path
import sqlite3
import time

import discord
from features.observed_returns import HK, merge_intervals, covered


@dataclass(frozen=True)
class TestAccountRegistry:
    """Explicit private confirmations only; absence is not an empty registry."""
    ids: frozenset[int]
    provenance: str

    def __post_init__(self):
        if not self.provenance.strip() or any(type(uid) is not int or uid <= 0 for uid in self.ids):
            raise ValueError('An explicit confirmation source and account IDs are required')


@dataclass(frozen=True)
class MemberSnapshot:
    ids: frozenset[int]
    bot_ids: frozenset[int]
    metadata: dict

    def aggregate(self, registry=None):
        complete = self.metadata['enumeration_complete']
        non_bots = self.ids - self.bot_ids
        tests = None if registry is None else len(non_bots & registry.ids)
        return dict(self.metadata, total_accounts=len(self.ids) if complete else None,
                    bot_accounts=len(self.bot_ids) if complete else None,
                    non_bot_accounts=len(non_bots) if complete else None,
                    observed_total_lower_bound=len(self.ids),
                    observed_non_bot_lower_bound=len(non_bots),
                    confirmed_owned_test_accounts=tests if complete else None,
                    confirmed_test_lower_bound=tests,
                    test_account_registry='unverified' if registry is None else 'confirmed_subset')


async def enumerate_members(guild, *, clock=time.time):
    """Exhaust discord.py REST pagination; never fall back to guild.members.

Reported counts are explicitly Gateway context, not a second census. Drift,
duplicates, or a reported-count mismatch invalidate an exact intersection.
"""
    started = clock()
    before = guild.member_count
    ids, bots, duplicates, exhausted, reasons = set(), set(), 0, False, []
    try:
        async for member in guild.fetch_members(limit=None):
            uid = int(member.id)
            if uid in ids:
                duplicates += 1
            ids.add(uid)
            if member.bot:
                bots.add(uid)
        exhausted = True
    except (discord.HTTPException, OSError, discord.ClientException):
        reasons.append('membership_read_failed')
    after = guild.member_count
    finished = clock()
    drift = after - before if before is not None and after is not None else None
    if duplicates:
        reasons.append('duplicate_member_ids')
    if drift:
        reasons.append('reported_member_count_drift')
    if after is not None and after != len(ids):
        reasons.append('reported_member_count_mismatch')
    complete = exhausted and not reasons
    if not complete:
        reasons.append('member_list_incomplete')
    return MemberSnapshot(frozenset(ids), frozenset(bots), dict(
        snapshot_started_at=started, snapshot_finished_at=finished,
        enumeration_method='discord_rest_fetch_members(limit=None)',
        enumeration_exhausted=exhausted, enumeration_complete=complete, atomic=False,
        reported_member_count=after, reported_member_count_before=before,
        reported_count_method='gateway_member_count_context_only',
        reported_count_drift=drift, duplicate_ids=duplicates, unknown_reason=reasons))


def windows(as_of):
    if not math.isfinite(as_of):
        raise ValueError('A finite as_of timestamp is required')
    end = datetime.fromtimestamp(as_of, HK).replace(hour=0, minute=0, second=0, microsecond=0)
    return [(str(n), (end-timedelta(days=n)).timestamp(), end.timestamp()) for n in (7, 28)] + [
        ('today_partial', end.timestamp(), as_of)]


def baseline(path, guild, as_of, membership, *, excluded_channels=(), registry=None):
    """One SQLite read transaction for all windows; fail closed on absent schema.

Unknown dates are unassignable to any window and are reported conservatively in
each window. Coverage is clipped interval union, independent of DB lifetime.
"""
    periods = windows(as_of)
    excluded = set(excluded_channels)
    excluded_users = set() if registry is None else registry.ids
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        since_row = db.execute("SELECT stamp FROM outcome_meta WHERE key='since'").fetchone()
        since = since_row[0] if since_row else None
        heartbeat = db.execute('SELECT MAX(last_success),SUM(failures) FROM outcome_observer_runs').fetchone()
        latest = db.execute('SELECT started,last_success,failures FROM outcome_observer_runs ORDER BY started DESC LIMIT 1').fetchone()
        results = []
        for label, start, end in periods:
            # Actual event timestamps, not session date, day label or today's names.
            rows = db.execute('''SELECT a.user,a.first_seen,s.test,s.origin,s.source_channel,s.voice_channel
                FROM (
                  SELECT guild,session,user,first_seen FROM outcome_attendance
                  WHERE guild=? AND (first_seen>=? AND first_seen<? OR first_seen IS NULL
                                     OR typeof(first_seen) NOT IN ('integer','real'))
                  UNION
                  SELECT guild,session,user,first_seen FROM outcome_visits
                  WHERE guild=? AND (first_seen>=? AND first_seen<? OR first_seen IS NULL
                                     OR typeof(first_seen) NOT IN ('integer','real'))
                ) a LEFT JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session''',
                (guild,start,end,guild,start,end)).fetchall()
            users = set()
            source_unknown = date_unknown = 0
            for user, stamp, test, origin, source, voice in rows:
                if test == 1 or source in excluded or voice in excluded or user in excluded_users:
                    continue
                if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
                    date_unknown += 1
                    continue
                if (test != 0 or origin not in ('linked', 'natural')
                        or not isinstance(source, int) or source <= 0
                        or not isinstance(voice, int) or voice <= 0
                        or not isinstance(user, int) or user <= 0):
                    source_unknown += 1
                    continue
                users.add(user)
            intervals = merge_intervals((max(start,a),min(end,b)) for a,b in db.execute(
                'SELECT start,end FROM outcome_coverage WHERE guild=? AND start<? AND end>?',
                (guild,end,start)) if a <= b)
            complete_coverage = start < end and covered(intervals, start, end)
            reasons = []
            if since is None or since > start:
                reasons.append('before_observation_start')
            if not complete_coverage:
                reasons.append('coverage_gap')
            if registry is None:
                reasons.append('account_registry_unverified')
            if source_unknown:
                reasons.append('source_unknown')
            if date_unknown:
                reasons.append('date_unknown')
            current = users & (membership.ids - membership.bot_ids)
            results.append(dict(label=label, start=start, end=end, timezone='Asia/Hong_Kong',
                distinct_accounts=len(users) if not reasons else None,
                observed_lower_bound=len(users), unknown_reason=reasons,
                current_members=dict(distinct_accounts=len(current) if not reasons and membership.metadata['enumeration_complete'] else None,
                    observed_lower_bound=len(current),
                    membership_intersection='complete' if membership.metadata['enumeration_complete'] else 'incomplete',
                    unknown_reason=[] if membership.metadata['enumeration_complete'] else ['member_list_incomplete']),
                coverage=dict(status='complete' if complete_coverage else 'gap',
                              seconds=sum(b-a for a,b in intervals)),
                unknown_source_rows=source_unknown, unknown_date_rows=date_unknown))
        return dict(schema_version=1, as_of=as_of, membership=membership.aggregate(registry),
            source=dict(kind='observed_voice',origins=['linked','natural'],scope='recorded SquadCards sessions',
                        bots='observer_filtered_at_event', test_sessions='stored_flag',
                        excluded_channels=len(excluded), test_account_registry='unverified' if registry is None else 'confirmed_subset'),
            observation_since=since, windows=results,
            heartbeat=dict(last_success=heartbeat[0], cumulative_failures=heartbeat[1],
                           latest_run=None if latest is None else dict(started=latest[0],last_success=latest[1],failures=latest[2]),
                           scope='all_recorded_runs_not_guild_specific'),
            first_participation_cohort='pending')
    finally:
        db.close()


def render(result, code='neutral'):
    """Static HK/TW/neutral text; never includes IDs, names or raw exceptions."""
    stamp = lambda value: datetime.fromtimestamp(value, HK).isoformat(timespec='seconds') if value is not None else '未知'
    value = lambda number: '未知' if number is None else str(number)
    m = result['membership']
    lines = ['**成員／觀測基線（香港時間）**', f"截至 {stamp(result['as_of'])}",
        f"REST 成員：總帳戶 {value(m['total_accounts'])}｜Bot {value(m['bot_accounts'])}｜非 Bot {value(m['non_bot_accounts'])}",
        f"已枚舉下限 {m['observed_total_lower_bound']}｜完整 {m['enumeration_complete']}｜非原子快照",
        f"擷取 [{stamp(m['snapshot_started_at'])}, {stamp(m['snapshot_finished_at'])}]；正常耗盡 {m['enumeration_exhausted']}；重複 {m['duplicate_ids']}",
        f"方法 REST fetch_members；Gateway 報告 {value(m['reported_member_count_before'])} → {value(m['reported_member_count'])}（僅旁證）；漂移 {value(m['reported_count_drift'])}",
        f"成員未知原因：{', '.join(m['unknown_reason']) or '無'}",
        f"自有測試帳名冊：{m['test_account_registry']}；已確認當前帳戶 {value(m['confirmed_owned_test_accounts'])}"]
    for w in result['windows']:
        label = '今日未完結' if w['label']=='today_partial' else f"最近 {w['label']} 個完整香港日"
        lines += [f"{label} [{stamp(w['start'])}, {stamp(w['end'])})",
            f"已觀測帳戶下限 {w['observed_lower_bound']}｜其中當前成員下限 {w['current_members']['observed_lower_bound']}（交集 {w['current_members']['membership_intersection']}）",
            f"coverage {w['coverage']['status']}／{w['coverage']['seconds']:.0f} 秒；未知：{', '.join(w['unknown_reason']) or '無'}"]
    h = result['heartbeat']
    scope = result.get('session_scope', {})
    latest = h['latest_run'] or {}
    lines += [f"觀測庫起點 {stamp(result['observation_since'])}；心跳最近成功 {stamp(h['last_success'])}；累計失敗 {value(h['cumulative_failures'])}（全庫，非例外次數）",
        f"最新 run 始於 {stamp(latest.get('started'))}／成功 {stamp(latest.get('last_success'))}／失敗 {value(latest.get('failures'))}；當下 cog 可用 {result.get('current_health', {}).get('available', 'unknown')}",
        f"當下 session 快照 {stamp(scope.get('as_of'))}：{scope.get('status', 'unknown')}；分類 {scope.get('counts', {})}。",
        '心跳、coverage、合資格到場分開；只涵蓋已記錄 SquadCards sessions，並非全群普查。',
        '非 Bot 帳戶不代表獨立真人；測試名冊未核實時下限仍可能包含副帳。',
        '出席不代表完成遊戲或個人達標；沒有記錄不代表沒有活動。05 首次觀察 cohort：pending。']
    text = '\n'.join(lines)
    if code == 'hk':
        text = text.replace('沒有記錄不代表沒有活動', '冇記錄唔代表冇活動')
    return text
