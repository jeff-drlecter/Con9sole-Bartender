"""Source-filtered, observational return cohorts. Never a churn/causality model."""
from datetime import datetime, timedelta
from core.sqlite_storage import connect_sqlite
from zoneinfo import ZoneInfo

HK = ZoneInfo('Asia/Hong_Kong')
MAX_GAP = 10  # At most two scheduled 5-second samples; gaps are unknown.


def migrate(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(outcome_sessions)')}
    for name, kind in [('source_channel','INTEGER'), ('voice_channel','INTEGER'),
                       ('origin','TEXT'), ('plan_origin','TEXT')]:
        if name not in columns:
            db.execute(f'ALTER TABLE outcome_sessions ADD COLUMN {name} {kind}')
    db.executescript('''
        CREATE INDEX IF NOT EXISTS outcome_attendance_time ON outcome_attendance(guild,first_seen,user,session);
        CREATE INDEX IF NOT EXISTS outcome_attendance_user ON outcome_attendance(guild,user,first_seen,session);
        CREATE INDEX IF NOT EXISTS outcome_source ON outcome_sessions(guild,origin,source_channel,first_seen);
        CREATE TABLE IF NOT EXISTS outcome_visits (
            guild INTEGER, session TEXT, user INTEGER, day TEXT, first_seen REAL,
            PRIMARY KEY(guild,session,user,day));
        CREATE INDEX IF NOT EXISTS outcome_visits_user ON outcome_visits(guild,user,first_seen,session);
        CREATE TABLE IF NOT EXISTS outcome_coverage (
            guild INTEGER, run TEXT, start REAL, end REAL, PRIMARY KEY(guild,run,start));
        CREATE INDEX IF NOT EXISTS outcome_coverage_time ON outcome_coverage(guild,start,end);
        CREATE TABLE IF NOT EXISTS outcome_coverage_state (
            guild INTEGER, run TEXT, stamp REAL, healthy INTEGER, segment REAL,
            PRIMARY KEY(guild,run));
    ''')


def coverage_sample(db, guild, run, now, success):
    db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT stamp,healthy,segment FROM outcome_coverage_state WHERE guild=? AND run=?',
                     (guild,run)).fetchone()
    if success:
        segment = row[2] if row and row[1] and 0 <= now-row[0] <= MAX_GAP else now
        db.execute('INSERT INTO outcome_coverage VALUES(?,?,?,?) ON CONFLICT(guild,run,start) DO UPDATE SET end=MAX(end,excluded.end)',
                   (guild,run,segment,now))
    else:
        segment = now
    db.execute('INSERT OR REPLACE INTO outcome_coverage_state VALUES(?,?,?,?,?)',
               (guild,run,now,int(success),segment))


def merge_intervals(rows):
    merged=[]
    for start,end in sorted(rows):
        if merged and start<=merged[-1][1]:
            merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:
            merged.append((start,end))
    return merged


def covered(intervals, start, end):
    return any(a<=start and b>=end for a,b in intervals)


def returns(path, guild, start, end, as_of, *, excluded_channels=(), origins=('linked','natural')):
    if not start < end <= as_of or end-start > 90*86400:
        raise ValueError('Cohort range must be positive, at most 90 days, and no later than as_of')
    if not origins or not set(origins)<= {'linked','natural'}:
        raise ValueError('Unsupported origin')
    excluded=tuple(sorted(set(excluded_channels)))
    marks=lambda items: ','.join('?' for _ in items)
    eligible="s.test=0 AND s.origin IN ("+marks(origins)+") AND s.source_channel IS NOT NULL AND s.voice_channel IS NOT NULL"
    params=list(origins)
    if excluded:
        eligible+=f' AND s.source_channel NOT IN ({marks(excluded)}) AND s.voice_channel NOT IN ({marks(excluded)})'
        params+=list(excluded)*2
    # Candidate users are time/guild bounded; each user's earliest eligible event
    # uses the covering guild/user/time index, not an unbounded full-store scan.
    with connect_sqlite(path) as db:
        db.execute('BEGIN')
        candidates=db.execute('SELECT DISTINCT user FROM outcome_attendance WHERE guild=? AND first_seen>=? AND first_seen<?',
                              (guild,start,end)).fetchall()
        cohort=[]; unknown=0
        anchor_eligible = eligible.replace('s.origin IN ('+marks(origins)+')', "s.origin IN ('linked','natural')")
        anchor_params = list(excluded)*2
        for (user,) in candidates:
            row=db.execute(f'''SELECT a.first_seen,a.session,s.origin FROM outcome_attendance a
                JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session
                WHERE a.guild=? AND a.user=? AND a.first_seen<=? AND {anchor_eligible}
                ORDER BY a.first_seen,a.session LIMIT 1''',(guild,user,as_of,*anchor_params)).fetchone()
            legacy=db.execute('''SELECT MIN(a.first_seen) FROM outcome_attendance a
                JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session
                WHERE a.guild=? AND a.user=? AND a.first_seen<=? AND s.test=0 AND
                (s.origin IS NULL OR s.source_channel IS NULL OR s.voice_channel IS NULL)''',
                (guild,user,as_of)).fetchone()[0]
            if legacy is not None and (row is None or legacy<=row[0]):
                unknown+=1; continue
            if not row or row[2] not in origins or not start<=row[0]<end:
                continue
            first,session,_=row
            day=datetime.fromtimestamp(first,HK).replace(hour=0,minute=0,second=0,microsecond=0)
            horizon=min(as_of,(day+timedelta(days=29)).timestamp())
            events=db.execute(f'''SELECT a.first_seen,a.session FROM
                (SELECT guild,session,user,first_seen FROM outcome_attendance
                 WHERE guild=? AND user=? AND first_seen>=? AND first_seen<=?
                 UNION SELECT guild,session,user,first_seen FROM outcome_visits
                 WHERE guild=? AND user=? AND first_seen>=? AND first_seen<=?) a
                JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session
                WHERE a.guild=? AND a.user=? AND a.first_seen>=? AND a.first_seen<=?
                AND a.session<>? AND {eligible}''',(guild,user,first,horizon,guild,user,first,horizon,guild,user,first,horizon,session,*params)).fetchall()
            cohort.append((first,day,events))
        intervals=merge_intervals(db.execute('SELECT start,end FROM outcome_coverage WHERE guild=? AND start<=? AND end>=?',
                                            (guild,as_of,start)).fetchall())
        since=db.execute("SELECT stamp FROM outcome_meta WHERE key='since'").fetchone()[0]
        unknown_rows=db.execute('''SELECT COUNT(*) FROM outcome_attendance a JOIN outcome_sessions s
            ON s.guild=a.guild AND s.session=a.session WHERE a.guild=? AND a.first_seen>=? AND a.first_seen<? AND s.test=0
            AND (s.origin IS NULL OR s.source_channel IS NULL OR s.voice_channel IS NULL)''',(guild,start,end)).fetchone()[0]
        spans=db.execute('''SELECT MIN(a.first_seen),MAX(a.first_seen) FROM outcome_attendance a
            JOIN outcome_sessions s ON s.guild=a.guild AND s.session=a.session
            WHERE a.guild=? AND a.first_seen>=? AND a.first_seen<=? AND '''+eligible,
            (guild,start,as_of,*params)).fetchone()
    windows={}
    for n in (0,7,28):
        mature=returned=pending=complete=0
        for first,day,events in cohort:
            finish=(day+timedelta(days=n+1)).timestamp()
            begin=first if n==0 else (day+timedelta(days=1)).timestamp()
            if as_of<finish:
                pending+=1; continue
            mature+=1
            returned+=any(begin<=t<finish for t,_ in events)
            complete+=covered(intervals,first,finish)
        windows[n]=dict(numerator=returned,denominator=mature,pending=pending,covered=complete,
                        rate=(returned/mature if mature and complete==mature else None))
    return dict(first_observed=len(cohort),unknown_people=unknown,unknown_rows=unknown_rows,
                windows=windows,since=since,start=start,end=end,as_of=as_of,
                origins=list(origins),excluded=list(excluded),observed_range=spans,
                coverage_seconds=sum(max(0,min(b,as_of)-max(a,start)) for a,b in intervals))


def render(r, code='neutral'):
    stamp=lambda t: datetime.fromtimestamp(t,HK).strftime('%Y-%m-%d %H:%M')
    lines=['**首次觀察與再次到場（香港時間）**',
        f"首次可用觀察批次 [{stamp(r['start'])}, {stamp(r['end'])})；截至 {stamp(r['as_of'])}",
        f"觀測庫起點 {stamp(r['since'])}；來源 {'／'.join(r['origins'])}；排除頻道 {len(r['excluded'])} 個。",
        f"首次可用觀察 {r['first_observed']} 人；來源未知 {r['unknown_rows']} 筆／首次時間未能核實 {r['unknown_people']} 人。"]
    for n,label in [(0,'D0 同日另一局'),(7,'D1–D7'),(28,'D1–D28')]:
        w=r['windows'][n]
        rate=f"觀測再參與率 {w['rate']:.1%}" if w['rate'] is not None else '資料不足，不提供確定比率'
        lines.append(f"{label}：已觀察再到場 {w['numerator']}／成熟 {w['denominator']} 人；待觀察 {w['pending']} 人；連續覆蓋 {w['covered']} 人。{rate}。")
    a,b=r['observed_range']
    lines.extend([f"本次有效到場範圍：{stamp(a)+' 至 '+stamp(b) if a is not None else '沒有可用觀測'}；已記錄覆蓋 {r['coverage_seconds']:.0f} 秒。",
        '首次觀察不是加入社群日期；再次到場必須是另一 session，同場重入不計。',
        '只計來源可核實的觀測；早於來源可信紀錄的未知歷史不重新當新人。',
        '成熟按香港日界完整經過 D7／D28 後判定；缺漏期間未知，未再次出現不等於流失。',
        '連續覆蓋僅為已記錄成功抽樣區段，不能證明 Discord 沒有漏接。',
        '到場不代表個人完成雙人 120 秒共同參與；共同參與維持局數指標，沒有個人達標推算。'])
    return '\n'.join(lines)
