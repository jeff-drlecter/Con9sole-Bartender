import hashlib, json, os, shutil, sqlite3
from datetime import datetime, timezone
from pathlib import Path
os.chdir('/app')
from core.storage_paths import STATS_DB
source = Path(STATS_DB).resolve()
assert source.exists(), 'Missing live database'
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
root = Path('/data/backups') / ('theme-collections-v1-' + stamp)
assert shutil.disk_usage('/data').free > source.stat().st_size * 3 + 10000000
root.mkdir(parents=True, exist_ok=False)
backup = root / 'community_stats.sqlite3'
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as live:
    with sqlite3.connect(backup) as dest:
        live.backup(dest)
os.chmod(backup, 0o600)
tables = ['drink_events', 'drink_collection', 'drink_milestones', 'drink_collection_titles']
report = {'backup': str(backup), 'created_at': stamp, 'quick_check': 'ok', 'tables': {}}
with sqlite3.connect(backup) as conn:
    assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    for table in tables:
        rows = conn.execute('SELECT * FROM ' + table).fetchall()
        report['tables'][table] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(sorted(rows), ensure_ascii=False).encode()).hexdigest()}
    report['max_event_id'] = conn.execute('SELECT COALESCE(MAX(id),0) FROM drink_events').fetchone()[0]
    report['ownership_users'] = conn.execute('SELECT COUNT(*) FROM (SELECT DISTINCT guild_key,user_id FROM drink_collection)').fetchone()[0]
(root / 'backup_report.json').write_text(json.dumps(report, indent=2))
Path('/data/backups/theme-collections-v1-latest.json').write_text(json.dumps(report))
print(json.dumps(report))
