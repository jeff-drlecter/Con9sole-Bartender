"""Read-only hints readiness; no reservations, Discord login or messages."""
import json
import os
from pathlib import Path
import sqlite3
import sys


def inspect(path, root, *, enabled):
    path, root = Path(path).resolve(), Path(root).resolve(strict=True)
    if not enabled or path.parent != root or not os.access(root, os.W_OK):
        raise ValueError('Hints must be enabled on the existing writable persistent directory.')
    result = dict(member_hints_enabled=True, persistent_path=True, store='not_created_yet')
    if path.exists():
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1) as db:
            if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Hints database integrity check failed.')
            # Do not read member IDs, counters or receipts.
            required = {'hint_scopes': {'guild', 'scope', 'scope_id', 'day', 'count', 'stamp', 'last_tip'},
                        'hint_receipts': {'interaction', 'stamp'}}
            for table, columns in required.items():
                if not columns.issubset({row[1] for row in db.execute(f'PRAGMA table_info({table})')}):
                    raise ValueError('Hints schema is incomplete.')
        result['store'] = 'integrity_checked_read_only'
    return result


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from features.member_hints import HINT_DB
    print(json.dumps(inspect(HINT_DB, os.getenv('DRINK_DATA_DIR') or '/data',
                             enabled=os.getenv('MEMBER_HINTS_ENABLED', '1').casefold() in {'1', 'true', 'yes'})))
