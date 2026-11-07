"""Stage externally supplied XP exports. No live database or network access."""
from __future__ import annotations

import csv
import hashlib
import io
from copy import deepcopy

from features.community_levels import level_for,threshold
from features.level_migration import integer,instant,strict_json

MAX_BYTES=20*1024*1024


def read_rows(raw,format,*,rows_key=None):
    if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:raise ValueError('Export exceeds 20 MiB')
    text=raw.decode('utf-8-sig')
    if format=='json':
        data=strict_json(text)
        if rows_key is not None:
            if not isinstance(rows_key,str) or not rows_key or type(data) is not dict or rows_key not in data:
                raise ValueError('Explicit JSON rows key not found')
            data=data[rows_key]
        if type(data) is not list:raise ValueError('Expected JSON array; specify rows_key for wrapped exports')
        rows=data
    elif format=='csv':
        reader=csv.DictReader(io.StringIO(text),strict=True)
        headers=reader.fieldnames
        if not headers or any(not h for h in headers) or len(headers)!=len(set(headers)):
            raise ValueError('CSV headers must be nonempty and unique')
        rows=list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError('CSV row width mismatch')
    else:raise ValueError('Use csv or json')
    if not 0<len(rows)<=100000 or any(type(row) is not dict for row in rows):
        raise ValueError('Expected 1 to 100000 object rows')
    return rows


def normalize(raw,format,mapping,*,weekly=False):
    allowed={'user_id','weekly_xp'} if weekly else {'user_id','total_xp','level','weekly_xp'}
    required={'user_id','weekly_xp'} if weekly else {'user_id','total_xp'}
    if type(mapping) is not dict or set(mapping)-{'columns','rows_key'}:raise ValueError('Invalid mapping')
    columns=mapping.get('columns')
    if type(columns) is not dict or not required<=set(columns) or set(columns)-allowed:
        raise ValueError('Missing or unsupported mapped columns')
    if any(not isinstance(v,str) or not v for v in columns.values()) or len(set(columns.values()))!=len(columns):
        raise ValueError('Mapped source column names must be distinct')
    rows=read_rows(raw,format,rows_key=mapping.get('rows_key'))
    result={};derived=False
    for index,row in enumerate(rows,1):
        try:
            if any(column not in row for column in columns.values()):raise ValueError('Missing mapped field')
            values={field:integer(row[column],positive=field=='user_id') for field,column in columns.items()}
            uid=values['user_id']
            if uid in result:raise ValueError('Duplicate user ID')
            if not weekly:
                xp=values['total_xp'];level=level_for(xp)
                if level>10000:raise ValueError('Level exceeds supported range')
                if 'level' in values and values['level']!=level:raise ValueError('XP/level mismatch')
                if 'level' not in values:derived=True
                values.update(level=level,level_xp=xp-threshold(level))
            result[uid]=values
        except (ValueError,TypeError,KeyError) as exc:
            # Do not include untrusted field contents or account names in error messages.
            raise ValueError(f'Row {index}: invalid ID, XP, duplicate or mapped field') from exc
    return result,derived


def prepare_intake(*,guild,totals_raw,totals_format,totals_mapping,roster_ids,source_count,metadata,
                   excluded_ids=None,weekly_raw=None,weekly_format=None,weekly_mapping=None):
    totals,derived=normalize(totals_raw,totals_format,totals_mapping)
    if len(totals)!=integer(source_count,positive=True):raise ValueError('Independent source row count mismatch')
    if type(roster_ids) is not list or (excluded_ids is not None and type(excluded_ids) is not list):
        raise ValueError('Roster and exclusions must be JSON arrays')
    excluded_ids=[] if excluded_ids is None else excluded_ids
    roster=[integer(uid,positive=True) for uid in roster_ids]
    excluded=[integer(uid,positive=True) for uid in excluded_ids]
    if not roster or len(roster)!=len(set(roster)) or len(excluded)!=len(set(excluded)) or set(roster)&set(excluded):
        raise ValueError('Roster/exclusion duplicate or overlap')
    if not set(excluded)<=set(totals):raise ValueError('Excluded ID missing from source')
    if set(totals)-set(excluded)!=set(roster):raise ValueError('Missing or extra unverified member IDs')
    if type(metadata) is not dict or set(metadata)-{'guild_id','exported_at','weekly_period','source_reference','weekly_exported_at','weekly_source_reference'}:
        raise ValueError('Invalid metadata fields')
    if integer(metadata.get('guild_id'),positive=True)!=integer(guild,positive=True):raise ValueError('Wrong guild')
    instant(metadata.get('exported_at'))
    reference=metadata.get('source_reference')
    if not isinstance(reference,str) or not reference.strip() or len(reference)>500:raise ValueError('Source provenance required')
    if weekly_raw is not None:
        if 'weekly_xp' in totals_mapping['columns']:raise ValueError('Weekly XP supplied twice')
        weekly,_=normalize(weekly_raw,weekly_format,weekly_mapping,weekly=True)
        if set(weekly)-set(totals):raise ValueError('Weekly export contains unknown extra IDs')
    else:weekly={uid:row for uid,row in totals.items() if 'weekly_xp' in row}
    users=[];missing_weekly=[]
    for uid in sorted(roster):
        row=dict(totals[uid]);row['weekly_xp']=weekly.get(uid,{}).get('weekly_xp')
        if row['weekly_xp'] is None:missing_weekly.append(uid)
        users.append(row)
    blockers=['Source authenticity, completeness and member scope require independent verification.',
              'A common frozen cutover time and backup/restore acceptance are still required.',
              'Historical compensation is separate and requires shared-text-cooldown reconciliation.']
    if missing_weekly:blockers.append('Weekly XP is missing; no zero balances have been invented.')
    if weekly_raw is not None:
        weekly_time=metadata.get('weekly_exported_at')
        weekly_ref=metadata.get('weekly_source_reference')
        if weekly_time is None:blockers.append('Separate weekly export timestamp is missing.')
        else:
            instant(weekly_time)
            if instant(weekly_time)!=instant(metadata['exported_at']):
                blockers.append('Totals and weekly capture times differ; frozen-source consistency is unverified.')
        if not isinstance(weekly_ref,str) or not weekly_ref.strip() or len(weekly_ref)>500:
            blockers.append('Separate weekly export source reference is missing.')
    period=metadata.get('weekly_period')
    if not isinstance(period,str) or not period.strip() or len(period)>100:
        blockers.append('Weekly period/reset provenance is missing.')
    return dict(schema=1,source='amari-staging',migration_ready=False,
        metadata=dict(metadata,guild_id=guild),mappings=deepcopy(dict(totals=totals_mapping,weekly=weekly_mapping)),
        source_count=len(totals),member_count=len(users),
        excluded_ids=sorted(excluded),level_derived_from_total=derived,missing_weekly_ids=missing_weekly,
        raw_sha256=dict(totals=hashlib.sha256(totals_raw).hexdigest(),
            weekly=hashlib.sha256(weekly_raw).hexdigest() if weekly_raw is not None else None),
        blockers=blockers,users=users)
