"""Private GET-only audit for 06. No messages, role changes, migration or writes.

Offline: python scripts/audit_news_access.py --snapshot /private/snapshot.json
Live: python scripts/audit_news_access.py --live --member-id ID --member-id ID
Keep stdout private: it includes exact permission mappings and requested roles.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from features.news_access_audit import audit


def collect(get, member_ids=(), counts=False):
    base = f'guilds/{config.GUILD_ID}'
    snapshot = dict(captured_at=datetime.now(timezone.utc).isoformat(),
        guild=get(base), roles=get(base+'/roles'), channels=get(base+'/channels'),
        onboarding=get(base+'/onboarding'), members=[get(base+'/members/'+str(uid)) for uid in member_ids])
    if counts:
        totals = {}; after = '0'
        for _ in range(20):
            rows = get(base+'/members?limit=1000&after='+after)
            for member in rows:
                for role in member['roles']: totals[str(role)] = totals.get(str(role),0)+1
            if len(rows)<1000:
                snapshot['member_counts'] = totals
                break
            after = rows[-1]['user']['id']
        else:
            raise ValueError('Incomplete member count; no migration conclusion allowed')
    return snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot',type=Path)
    source.add_argument('--live',action='store_true')
    parser.add_argument('--member-id',action='append',default=[],type=int)
    parser.add_argument('--include-member-counts',action='store_true')
    args=parser.parse_args()
    if args.snapshot:
        snapshot=json.loads(args.snapshot.read_text())
    else:
        token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
        if not token: raise SystemExit('Bot credential unavailable; no request sent.')
        def get(path):
            request=urllib.request.Request('https://discord.com/api/v10/'+path, method='GET',
                headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/1.0'})
            with urllib.request.urlopen(request,timeout=20) as response:
                return json.load(response)
        snapshot=collect(get,args.member_id,args.include_member_counts)
    print(json.dumps(audit(snapshot),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
