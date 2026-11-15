"""Additive observations in existing stores; never delivery reservations or receipts."""
import json
import sqlite3


def record(store, key, result, *, obtained=False, delivered=False, failed=False, pending=False, now=None):
    import time
    now = time.time() if now is None else now
    with sqlite3.connect(store.path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS delivery_observations (key TEXT PRIMARY KEY, body TEXT NOT NULL)')
        row = db.execute('SELECT body FROM delivery_observations WHERE key=?', (key,)).fetchone()
        data = json.loads(row[0]) if row else {}
        data.update(attempt=now, result=result, failures=data.get('failures', 0)+1 if failed else data.get('failures', 0) if result in ('attempting','outside_window') else 0,
                    pending=pending)
        if obtained: data['obtained'] = now
        if delivered: data['delivered'] = now
        if failed: data['last_failure'] = now
        db.execute('INSERT OR REPLACE INTO delivery_observations VALUES (?,?)', (key, json.dumps(data)))


def snapshot(store):
    # No table creation, migrations or writes on health-page reads.
    if store is None: return {}
    with sqlite3.connect(f'file:{store.path}?mode=ro', uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_observations'").fetchone(): return {}
        return {key: json.loads(body) for key, body in db.execute('SELECT key,body FROM delivery_observations')}


def safe_snapshot(store):
    try: return snapshot(store), False
    except (OSError, ValueError, sqlite3.Error): return {}, True


def source_condition(rows, keys, now, ttl):
    values = [rows.get(k, {}) for k in keys]
    failed = sum(v.get('failures', 0) > 0 for v in values)
    stale = sum(v.get('obtained', 0) > 0 and now-v['obtained'] > ttl for v in values)
    unknown = sum(not v.get('obtained') for v in values)
    return 'partial' if failed and failed < len(values) else 'failed' if failed else 'stale' if stale else 'unknown' if unknown else 'ok'


def format_health(data):
    def stamp(value): return f'<t:{int(value)}:R>' if value else '未知'
    lines = [f"收集：{data.get('collection', '未知')}｜私人預覽：{data.get('preview', '未知')}｜正式推送：{data.get('delivery', '未知')}"]
    if data.get('read_error'): lines.append('狀態讀取失敗，待核對')
    rows = data.get('observations', {})
    lines.append(f"待核對項目：{sum(bool(r.get('pending')) for r in rows.values())}")
    for key, row in sorted(rows.items(), key=lambda item: (not item[1].get('pending', False), item[0])):
        lines.append(f"{key}：{row.get('result','未知')}｜嘗試 {stamp(row.get('attempt'))}｜取得 {stamp(row.get('obtained'))}｜交付 {stamp(row.get('delivered'))}｜連敗 {row.get('failures',0)}｜待核對 {bool(row.get('pending'))}")
    return '\n'.join(lines)[:1000]
