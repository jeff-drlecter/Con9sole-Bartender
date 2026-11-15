"""Minimal, observational squad outcomes. No XP or message-content access."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import time

from core.sqlite_storage import connect_sqlite
from features.squad_outcome_state import evidence, plan_outcome

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
                CREATE TABLE IF NOT EXISTS outcome_observer_runs (
                    run TEXT PRIMARY KEY, started REAL, last_success REAL, failures INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS outcome_attendance (
                    guild INTEGER, session TEXT, user INTEGER, first_seen REAL,
                    PRIMARY KEY(guild,session,user));
            ''')
            db.execute('INSERT OR IGNORE INTO outcome_meta VALUES(?,?)', ('since', self.clock()))
            db.execute('INSERT OR IGNORE INTO outcome_meta VALUES(?,?)', ('natural_since', self.clock()))

    def heartbeat(self, run, *, success):
        """Record observation coverage only; offline intervals are never filled in."""
        now = self.clock()
        with connect_sqlite(self.path) as db:
            db.execute("INSERT OR IGNORE INTO outcome_observer_runs VALUES(?,?,NULL,0)", (run, now))
            if success:
                db.execute("UPDATE outcome_observer_runs SET last_success=? WHERE run=?", (now, run))
            else:
                db.execute("UPDATE outcome_observer_runs SET failures=failures+1 WHERE run=?", (run,))

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
        matured = [p for p in cohort if evidence(p, as_of=as_of)['matured']]
        outcome = plan_outcome
        counts = {k: sum(outcome(p) == k for p in matured)
                  for k in ('opened', 'cancelled', 'unopened', 'unknown')}
        ids = {p['id'] for p in cohort}
        with connect_sqlite(self.path) as db:
            since = db.execute("SELECT stamp FROM outcome_meta WHERE key='since'").fetchone()[0]
            natural_since = db.execute("SELECT stamp FROM outcome_meta WHERE key='natural_since'").fetchone()[0]
            rows = db.execute('''SELECT s.plan,s.session,a.user,a.first_seen,s.first_seen FROM outcome_sessions s
                JOIN outcome_attendance a ON a.guild=s.guild AND a.session=s.session
                WHERE s.guild=? AND s.test=0''', (guild,)).fetchall()
        # Cohort attendance, bounded at report time; repeat joins count once/session.
        pairs = {(session, user) for plan, session, user, stamp, _ in rows
                 if plan in ids and stamp <= as_of}
        natural = {(session, user) for plan, session, user, stamp, first in rows
                   if plan is None and start <= first < end and stamp <= as_of}
        with connect_sqlite(self.path) as db:
            coverage = db.execute("SELECT MAX(last_success), COALESCE(SUM(failures),0) FROM outcome_observer_runs").fetchone()
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
                    per_session=sorted(sum(s == key for s, _ in pairs) for key in {s for s, _ in pairs}),
                    natural_sessions=len({s for s, _ in natural}), natural_attendance=len(natural),
                    natural_unique=len({u for _, u in natural}),
                    last_success=coverage[0], observation_failures=coverage[1], natural_since=natural_since,
                    undated=sum(p.get('created_at') is None for p in clean),
                    excluded=len(all_plans)-len(clean)-unpublished, unpublished=unpublished, since=since,
                    first_created=min((p['created_at'] for p in clean if p.get('created_at') is not None), default=None))


def display(r, code='neutral'):
    rate = f"{r['rate']:.1%}" if r['rate'] is not None else '資料不足／含未知狀態'
    stamp = lambda t: datetime.fromtimestamp(t, HK).strftime('%Y-%m-%d %H:%M')
    attendance = (f"{r['attendance']} 人次｜跨局去重 {r['unique']} 人｜跨局再參與 {r['repeat']} 人"
                  if r['attendance_sessions'] else '出席未知（沒有可用觀測）')
    natural = (f"{r['natural_sessions']} 局／{r['natural_attendance']} 人次／跨局去重 {r['natural_unique']} 人"
               if r['natural_sessions'] else '未觀測／未涵蓋，不能解讀為沒有活動')
    per_session = (f"{min(r['per_session'])}–{max(r['per_session'])} 人" if r['per_session'] else '未知')
    last = stamp(r['last_success']) if r['last_success'] is not None else '尚無記錄'
    result = (f"**社群成效（香港時間）**\n建立區間 [{stamp(r['start'])}, {stamp(r['end'])})；判定截至 {stamp(r['as_of'])}\n"
            f"新約局 {r['new']}｜已到判定期限 {r['matured']}｜未到期限 {r['pending']}\n"
            f"本批全部：已開局 {r['opened_total']}｜未開局 {r['unopened_total']}｜取消 {r['cancelled_total']}\n"
            f"同批到期：約局已開局 {r['opened']}｜未開局 {r['unopened']}｜取消 {r['cancelled']}｜未知 {r['unknown']}\n"
            f"房間開局率 {rate}（分母 {r['matured']}，包括取消；未知時不提供確定比率）\n"
            f"本批約局語音：{attendance}\n有到場觀測 {r['attendance_sessions']} 局；每局去重 {per_session}。其餘出席未知。\n"
            f"自然語音局（首次觀測在期間內）：{natural}；觀測始於 {stamp(r['natural_since'])}，不加入開局率。\n"
            f"無建立日期歷史 {r['undated']} 筆；排除可辨識測試 {r['excluded']} 筆；未發布 {r['unpublished']} 筆。\n"
            f"觀測庫始於 {stamp(r['since'])}；最近成功抽樣 {last}；累計記錄的抽樣錯誤 {r['observation_failures']} 次。\n"
            '5 秒抽樣及 Gateway 事件只提供已觀測下限；重啟／漏接未知，開始日期不代表全程覆蓋。\n'
            '開局＝至少一位真人通過既有約 30 秒流程；不等於成功組隊或滿員。\n'
            '報名、稍後到、原有朋友數不是出席；同局重入只計一次，跨局再計人次。\n'
            '兩人先後出現不證明同時參與；共同參與門檻尚未啟用。\n'
            '預約到期＝開始後 2 小時；現在玩＝6 小時。')
    if code == 'hk':
        # Only Bot-owned static copy; never translate stored game names/member input.
        result = result.replace('出席未知（沒有可用觀測）', '出席未知（暫時冇可用觀測）')
        result = result.replace('不能解讀為沒有活動', '唔代表冇活動')
        result = result.replace('不等於成功組隊或滿員', '唔等於成功組隊或者滿員')
    return result
