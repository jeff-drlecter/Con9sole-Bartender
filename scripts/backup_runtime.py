"""Private online backups, consistent per store, never a cross-store transaction.

JSON stores use atomic replacement; SQLite uses the backup API, including WAL.
Each copied store is reopened and checked before a ready manifest is published.
Do not restore old notification/XP databases on code rollback.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import uuid


OVERRIDES = ('STATS_DB_PATH', 'DRINK_STATE_PATH', 'GAME_ANNOUNCEMENTS_PATH',
             'ACTIVITY_REMINDER_PATH', 'SQUAD_CARDS_PATH')


def backup(root, target, *, environ=None):
    env = os.environ if environ is None else environ
    root = Path(root).resolve(strict=True)
    if not re.fullmatch(r'[0-9a-f]{40}', target):
        raise ValueError('A full target commit SHA is required.')
    # External overrides need their own reviewed backup; never silently omit them.
    for name in OVERRIDES:
        if env.get(name):
            Path(env[name]).resolve().relative_to(root)
    destination = root / 'release_backups'
    if destination.is_symlink():
        raise ValueError('Backup directory must not be a symlink.')
    destination.mkdir(mode=0o700, exist_ok=True)
    destination.chmod(0o700)
    files = []
    for current, directories, names in os.walk(root, followlinks=False):
        parent = Path(current)
        if parent == root:
            directories[:] = [d for d in directories if d != destination.name]
        if any((parent / d).is_symlink() for d in directories):
            raise ValueError('Symlink in runtime directory; backup needs review.')
        for name in names:
            path = parent / name
            if path.is_symlink():
                raise ValueError('Symlink in runtime directory; backup needs review.')
            if not path.is_file():
                raise ValueError('Unsupported runtime entry; backup needs review.')
            if name.startswith('.env') or name.endswith(('-wal', '-shm', '-journal', '.tmp')):
                continue
            files.append(path)
    if not files:
        raise ValueError('Runtime is empty; refusing an empty backup.')
    if shutil.disk_usage(root).free < 2 * sum(p.stat().st_size for p in files) + 1024 * 1024:
        raise ValueError('Insufficient free space for checked backup.')
    folder = destination / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    manifest = dict(target_sha=target, started_at=datetime.now(timezone.utc).isoformat(),
                    consistency='per-store-online; not a global transaction', files=[])
    try:
        for path in sorted(files):
            relative = path.relative_to(root)
            output = folder / 'stores' / relative
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open('rb') as stream:
                sqlite = stream.read(16) == b'SQLite format 3\x00'
            if path.suffix in ('.db', '.sqlite', '.sqlite3') and not sqlite:
                raise ValueError('Database header invalid; refusing an unchecked copy.')
            if sqlite:
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10) as source, sqlite3.connect(output) as copied:
                    source.backup(copied)
                    if copied.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise ValueError('SQLite backup integrity check failed.')
                # Reopen into an isolated in-memory restore, never the live store.
                with sqlite3.connect(output.as_uri() + '?mode=ro', uri=True) as copied, sqlite3.connect(':memory:') as restored:
                    copied.backup(restored)
                    if restored.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise ValueError('SQLite restore check failed.')
            else:
                payload = path.read_bytes()
                if path.suffix == '.json':
                    json.loads(payload)
                output.write_bytes(payload)
            output.chmod(0o600)
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            manifest['files'].append(dict(path=str(relative), sha256=digest,
                kind='sqlite' if sqlite else 'file', captured_at=datetime.now(timezone.utc).isoformat()))
        for item in manifest['files']:
            if hashlib.sha256((folder / 'stores' / item['path']).read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Backup readback failed.')
        manifest.update(ready=True, completed_at=datetime.now(timezone.utc).isoformat())
        marker = folder / 'manifest.json'
        marker.write_text(json.dumps(manifest, indent=2))
        marker.chmod(0o600)
        return folder, manifest
    except Exception:
        # Partial files remain private for diagnostics, without a ready marker.
        raise RuntimeError('Backup incomplete; deployment must stop.') from None


if __name__ == '__main__':
    folder, result = backup(os.getenv('DRINK_DATA_DIR') or '/data', sys.argv[1])
    print(json.dumps(dict(backup_ready=True, target_sha=result['target_sha'],
                         backup_id=folder.name, stores=len(result['files']),
                         consistency=result['consistency'], restore_check='passed')))
