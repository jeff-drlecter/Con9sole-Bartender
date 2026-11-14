"""Read-only aggregate coverage inventory. Run against a consistent runtime backup.

No chat content, display names or member IDs are emitted. Never initializes databases.
"""
import argparse
import json
import sqlite3
from pathlib import Path


def inventory(root):
    result = {}
    path = root / 'squad_plans.json'
    if path.exists():
        plans = list(json.loads(path.read_text())['plans'].values())
        result['plans'] = dict(rows=len(plans),
            created_range=[min((p['created_at'] for p in plans if p.get('created_at') is not None),default=None),
                           max((p['created_at'] for p in plans if p.get('created_at') is not None),default=None)],
            scheduled_range=[min((p['start'] for p in plans),default=None), max((p['start'] for p in plans),default=None)],
            undated=sum(p.get('created_at') is None for p in plans),
            marked_test=sum(bool(p.get('analytics_test') or p.get('test') or p.get('is_test')) for p in plans))
    else:
        result['plans'] = 'unavailable'
    sources = {
        'community_stats.sqlite3': [('command_usage','used_at'),('daily_bar_completions','completed_at'),
            ('squad_interest_attempts','attempted_at'),('squad_ended_sessions','stamp'),('squad_card_posts','stamp')],
        'community_levels.sqlite3': [('xp_events','stamp'),('receipts','stamp')],
        'community_outcomes.sqlite3': [('outcome_attendance','first_seen'),('outcome_sessions','first_seen')],
    }
    for filename, tables in sources.items():
        path = root / filename
        result[filename] = {}
        if not path.exists():
            result[filename] = 'unavailable'
            continue
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            for table, column in tables: # Fixed identifiers, never user input.
                exists = db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone()
                if exists:
                    row = db.execute(f'SELECT COUNT(*),MIN({column}),MAX({column}) FROM {table}').fetchone()
                    result[filename][table] = dict(rows=row[0],first=row[1],last=row[2])
                else:
                    result[filename][table] = 'unavailable'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(inventory(args.data_dir),ensure_ascii=False,indent=2))
