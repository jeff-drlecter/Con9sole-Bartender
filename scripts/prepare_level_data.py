"""Validate and stage an Amari CSV/JSON export. Never reads or writes the live ledger."""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from features.level_intake import MAX_BYTES,prepare_intake
from features.level_migration import strict_json


def read(path):
    with path.open('rb') as source:
        raw=source.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Input exceeds 20 MiB')
    return raw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--guild',type=int,required=True)
    p.add_argument('--totals',type=Path,required=True)
    p.add_argument('--format',choices=('csv','json'),required=True)
    p.add_argument('--mapping',type=Path,required=True)
    p.add_argument('--roster',type=Path,required=True,help='Independently verified intended XP member IDs')
    p.add_argument('--source-count',type=int,required=True,help='Independent total source row count before exclusions')
    p.add_argument('--metadata',type=Path,required=True)
    p.add_argument('--excluded-ids',type=Path,help='Explicitly verified departed IDs; never names')
    p.add_argument('--weekly',type=Path)
    p.add_argument('--weekly-format',choices=('csv','json'))
    p.add_argument('--weekly-mapping',type=Path)
    p.add_argument('--output',type=Path,required=True,help='New private output directory; existing paths are rejected')
    a=p.parse_args()
    if bool(a.weekly)!=bool(a.weekly_format) or bool(a.weekly)!=bool(a.weekly_mapping):
        p.error('Supply weekly, weekly-format and weekly-mapping together')
    try:
        load=lambda path:strict_json(read(path).decode('utf-8-sig'))
        result=prepare_intake(guild=a.guild,totals_raw=read(a.totals),totals_format=a.format,
            totals_mapping=load(a.mapping),roster_ids=load(a.roster),source_count=a.source_count,
            metadata=load(a.metadata),excluded_ids=load(a.excluded_ids) if a.excluded_ids else None,
            weekly_raw=read(a.weekly) if a.weekly else None,weekly_format=a.weekly_format,
            weekly_mapping=load(a.weekly_mapping) if a.weekly_mapping else None)
        # Validation completes before output creation. Never overwrite previous intake evidence.
        a.output.mkdir(mode=0o700,parents=True,exist_ok=False)
        contents=json.dumps(result,ensure_ascii=False,indent=2).encode()
        fd=os.open(a.output/'intake.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as target:target.write(contents)
        print(json.dumps(dict(staged=True,migration_ready=False,members=result['member_count'],
            excluded=len(result['excluded_ids']),missing_weekly=len(result['missing_weekly_ids'])),ensure_ascii=False))
    except (ValueError,TypeError,UnicodeError,csv.Error,OSError) as exc:
        p.exit(2,f'Intake rejected: {exc}\n')


if __name__=='__main__':main()
