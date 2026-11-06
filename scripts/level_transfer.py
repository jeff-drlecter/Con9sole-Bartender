"""Offline-only level backup/transfer. Stop the Bot before running write operations."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from features.community_levels import Ledger
from features.level_migration import strict_json,apply_snapshot,create_backup,restore_backup


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--guild',type=int,required=True)
    p.add_argument('--offline',action='store_true',help='Attest Bot process is stopped; required for all actions')
    sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('backup');b.add_argument('--output',type=Path,required=True)
    i=sub.add_parser('import-snapshot');i.add_argument('--snapshot',type=Path,required=True);i.add_argument('--roster',type=Path,required=True)
    i.add_argument('--source-count',type=int,required=True);i.add_argument('--backup',type=Path,required=True);i.add_argument('--commit',action='store_true')
    r=sub.add_parser('restore');r.add_argument('--backup',type=Path,required=True);r.add_argument('--sha256',required=True);r.add_argument('--checkpoint',type=Path,required=True)
    a=p.parse_args()
    if not a.offline: p.error('Stop the Bot process and use --offline; do not run against a live Bot.')
    if not a.db.is_file() or a.db.is_symlink():p.error('Existing regular ledger database required')
    ledger=Ledger(a.db)
    if ledger.settings(a.guild)['mode']!='off':p.error('Pause the feature before stopping the Bot')
    if a.action=='backup':result=dict(sha256=create_backup(ledger,a.output))
    elif a.action=='restore':result=restore_backup(ledger,a.backup,expected_sha=a.sha256,guild=a.guild,checkpoint_path=a.checkpoint)
    else:
        result=apply_snapshot(ledger,strict_json(a.snapshot.read_text()),guild=a.guild,
            roster_ids=strict_json(a.roster.read_text()),expected_count=a.source_count,backup_path=a.backup,commit=a.commit)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
