"""Minimal, observational squad outcomes. No XP or message-content access."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import time

from core.sqlite_storage import connect_sqlite
from features.squad_plans import deadline

HK = ZoneInfo('Asia/Hong_Kong')


def window(period, now):
    local = datetime.fromtimestamp(now, HK)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period in ('week', 'previous_week'):
        start -= timedelta(days=start.weekday())
        if period == 'previous_week':
            return (start - timedelta(days=7)).timestamp(), start.timestamp()
    elif period != 'day':
        raise ValueError('Unknown period')
    return start.timestamp(), now


def test_channel(channel):
    """Conservative labels supplement explicit persisted test flags/ID exclusions."""
    names = [getattr(channel, 'name', ''), getattr(getattr(channel, 'category', None), 'name', '')]
    return any(token in name.casefold() for name in names
               for token in ('測試', 'sandbox', 'test'))


class Outcomes:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        with connect_sqlite(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS outcome_meta (key TEXT PRIMARY KEY, stamp REAL);
                CREATE TABLE IF NOT EXISTS outcome_sessions (
                    guild INTEGER, session TEXT, plan TEXT, first_seen REAL,
                    test INTEGER NOT NULL, PRIMARY KEY(guild,session));
                CREATE TABLE IF NOT EXISTS outcome_attendance (
                    guild INTEGER, session TEXT, user INTEGER, first_seen REAL,
                    PRIMARY KEY(guild,session,user));
            ''')
            db.execute('INSERT OR IGNORE INTO outcome_meta VALUES(?,?)', ('since', self.clock()))

    def observe(self, guild, session, plan, members, *, test=False):
        """Caller supplies current Gateway humans only, never accumulated names/RSVPs."""
        now = self.clock()
        with connect_sqlite(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT INTO outcome_sessions VALUES(?,?,?,?,?)
                ON CONFLICT(guild,session) DO UPDATE SET
                plan=COALESCE(outcome_sessions.plan,excluded.plan),
                test=MAX(outcome_sessions.test,excluded.test)''',
                (guild, session, plan, now, int(test)))
            db.executemany('INSERT OR IGNORE INTO outcome_attendance VALUES(?,?,?,?)',
                          [(guild, session, m.id, now) for m in members if not m.bot])

    def report(self, guild, plans, start, end, *, excluded_channels=(), as_of=None):
        as_of = end if as_of is None else as_of
        excluded = set(excluded_channels)
        with connect_sqlite(self.path) as db:
            observed_tests = {r[0] for r in db.execute(
                'SELECT plan FROM outcome_sessions WHERE guild=? AND test=1', (guild,))}
        all_plans = {p['id']: p for p in plans if p['guild'] == guild}
        clean = [p for p in all_plans.values() if not p.get('analytics_test')
                 and not p.get('test') and not p.get('is_test') and p['channel'] not in excluded
                 and p['id'] not in observed_tests]
        unpublished = sum(p['status'] == 'posting' for p in clean)
        clean = [p for p in clean if p['status'] != 'posting']
        cohort = [p for p in clean if p.get('created_at') is not None
                  and start <= p['created_at'] < end]
        matured = [p for p in cohort if deadline(p) <= as_of]
        def outcome(p):
            if p['status'] in ('live', 'ended') and p.get('session'):
                return 'opened'
            if p['status'] == 'cancelled':
                return 'cancelled'
            if p['status'] == 'expired':
                return 'unopened'
            return 'unknown'
        counts = {k: sum(outcome(p) == k for p in matured)
                  for k in ('opened', 'cancelled', 'unopened', 'unknown')}
        ids = {p['id'] for p in cohort}
        with connect_sqlite(self.path) as db:
            since = db.execute("SELECT stamp FROM outcome_meta WHERE key='since'").fetchone()[0]
            rows = db.execute('''SELECT s.plan,s.session,a.user,a.first_seen FROM outcome_sessions s
                JOIN outcome_attendance a ON a.guild=s.guild AND a.session=s.session
                WHERE s.guild=? AND s.test=0''', (guild,)).fetchall()
        # Cohort attendance, bounded at report time; repeat joins count once/session.
        pairs = {(session, user) for plan, session, user, stamp in rows
                 if plan in ids and stamp <= as_of}
        users = {user for _, user in pairs}
        per_user = {u: sum(v == u for _, v in pairs) for u in users}
        return dict(start=start, end=end, as_of=as_of, new=len(cohort), matured=len(matured), pending=len(cohort)-len(matured),
                    opened_total=sum(outcome(p) == 'opened' for p in cohort),
                    cancelled_total=sum(outcome(p) == 'cancelled' for p in cohort),
                    unopened_total=sum(outcome(p) == 'unopened' for p in cohort),
                    **counts, rate=(counts['opened']/len(matured)
                        if matured and not counts['unknown'] else None),
                    attendance=len(pairs), unique=len(users),
                    repeat=sum(n > 1 for n in per_user.values()),
                    attendance_sessions=len({s for s, _ in pairs}),
                    undated=sum(p.get('created_at') is None for p in clean),
                    excluded=len(all_plans)-len(clean)-unpublished, unpublished=unpublished, since=since,
                    first_created=min((p['created_at'] for p in clean if p.get('created_at') is not None), default=None))


def display(r):
    rate = f"{r['rate']:.1%}" if r['rate'] is not None else '資料不足／含未知狀態'
    since = datetime.fromtimestamp(r['since'], HK).strftime('%Y-%m-%d %H:%M')
    stamp = lambda t: datetime.fromtimestamp(t, HK).strftime('%m-%d %H:%M')
    return (f"**社群成效（香港時間）**\n建立區間 [{stamp(r['start'])}, {stamp(r['end'])})；判定截至 {stamp(r['as_of'])}\n新約局 {r['new']}｜已到判定期限 {r['matured']}｜未到期限 {r['pending']}\n"
            f"本批全部：已開局 {r['opened_total']}｜未開局 {r['unopened_total']}｜取消 {r['cancelled_total']}\n"
            f"同批到期約局：已開局 {r['opened']}｜未開局 {r['unopened']}｜取消 {r['cancelled']}｜未知 {r['unknown']}\n"
            f"成局率 {rate}（分母 {r['matured']}，包括取消；未知時不提供確定比率）\n"
            f"本批約局觀測語音：{r['attendance']} 人次｜{r['unique']} 位真人｜跨局再參與 {r['repeat']} 人\n"
            f"有到場觀測 {r['attendance_sessions']} 場；其餘出席未知，未當作 0。\n"
            f"無建立日期的歷史 {r['undated']} 筆未納入日期比較；排除可辨識測試 {r['excluded']} 筆；未發布 {r['unpublished']} 筆未計入。\n"
            f"到場收集始於 {since}；5 秒抽樣及 Gateway 事件只提供已觀測下限，停機／漏接未知。\n"
            '開局沿用 03：一位真人通過既有約 30 秒流程；不等於成功湊齊隊伍。\n'
            '未開局以逾時狀態為證；預約期限為開始後 2 小時，現在玩為 6 小時。\n'
            '報名、稍後到及原有朋友數不計出席；不包含未連接約局的自然語音局。')
