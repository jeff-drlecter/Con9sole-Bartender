"""GET-only/private snapshot audit: no role/channel changes or messages.

python scripts/audit_helper_entry.py --snapshot /private/snapshot.json
python scripts/audit_helper_entry.py --live --member-id ID (repeatable)
"""
from copy import deepcopy
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from features.news_access_audit import permissions, access
from scripts.audit_news_access import collect

DASHBOARD = 1570639281225994301
DEMO = 1570093470666854411
VIEW_HISTORY = 1024 | 65536


def report(snapshot):
    if str(snapshot['guild']['id']) != str(config.GUILD_ID): raise ValueError('Unexpected guild')
    roles, channels = snapshot['roles'], snapshot['channels']
    testers = [r for r in roles if r['name'] == '🧪 Tester']
    problems = [c for c in channels if '問題回報' in c['name']]
    ids = {DASHBOARD, DEMO, config.WELCOME_CHANNEL_ID, config.GUIDE_CHANNEL_ID, config.SUPPORT_CHANNEL_ID}
    ids.update(int(c['id']) for c in problems)
    targets = [c for c in channels if int(c['id']) in ids]
    result = dict(guild=str(config.GUILD_ID), captured_at=snapshot.get('captured_at'),
        helper_roles=[str(r) for r in config.HELPER_ROLE_IDS], testers=testers,
        channels=targets, proposed_changes=[], limitations=[
            'No UI/member live pass. Age restriction intent cannot be inferred from a flag.',
            'Other roles/member overwrites may still grant Dashboard access; verify effective permissions.',
            'Draft only; compare current snapshot before applying; do not sync category permissions.'])
    if len(testers) == 1:
        tester = testers[0]['id']
        board = next((c for c in targets if int(c['id']) == DASHBOARD), None)
        overwrite = next((o for o in board.get('permission_overwrites', []) if str(o['id']) == str(tester) and int(o['type']) == 0), None) if board else None
        if overwrite:
            after = dict(overwrite, allow=str(int(overwrite['allow']) & ~VIEW_HISTORY))
            if after != overwrite:
                result['proposed_changes'].append(dict(channel=str(DASHBOARD), target=str(tester),
                    before=overwrite, after=after, reason='Remove Tester view/history grants only; preserve all deny/other bits.'))
    if len(problems) == 1:
        channel = problems[0]
        result['age_review'] = dict(channel=channel['id'], name=channel['name'], before=channel.get('nsfw', False),
            proposed_patch={'nsfw': False} if channel.get('nsfw') else {},
            condition='Only if Jeff confirms restriction is unnecessary; no permission/topic/category/type changes.')
    else:
        result['age_review'] = dict(blocked='Missing or ambiguous 問題回報 channel; do not guess ID.')
    role_sets = {'newcomer': [], 'verified': [config.VERIFIED_ROLE_ID], 'helper': [config.VERIFIED_ROLE_ID, *config.HELPER_ROLE_IDS]}
    if len(testers) == 1:
        role_sets.update(tester=[int(testers[0]['id'])], helper_tester=[config.VERIFIED_ROLE_ID, *config.HELPER_ROLE_IDS, int(testers[0]['id'])])
    result['simulated'] = {label: {str(c['id']): dict(access(permissions(config.GUILD_ID,roles,dict(user=dict(id='0'),roles=[str(r) for r in rr]),c)), nsfw=c.get('nsfw',False)) for c in targets} for label,rr in role_sets.items()}
    after_targets = deepcopy(targets)
    for change in result['proposed_changes']:
        target = next(c for c in after_targets if str(c['id']) == change['channel'])
        target['permission_overwrites'] = [change['after'] if o == change['before'] else o for o in target['permission_overwrites']]
    result['after_simulated'] = {label: {str(c['id']): access(permissions(config.GUILD_ID, roles, dict(user=dict(id='0'),roles=[str(r) for r in rr]),c)) for c in after_targets} for label,rr in role_sets.items()}
    result['accounts'] = [{ 'id':m['user']['id'], 'roles':m['roles'], 'channels':{str(c['id']):access(permissions(config.GUILD_ID,roles,m,c,owner_id=snapshot['guild'].get('owner_id'))) for c in targets}} for m in snapshot.get('members',[])]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path)
    source.add_argument('--live', action='store_true')
    parser.add_argument('--member-id',action='append',default=[],type=int)
    args=parser.parse_args()
    if args.snapshot:
        snapshot=json.loads(args.snapshot.read_text())
    else:
        token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
        if not token: raise SystemExit('No credential; no request sent.')
        def get(path):
            request=urllib.request.Request('https://discord.com/api/v10/'+path, method='GET', headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/1.0'})
            with urllib.request.urlopen(request,timeout=20) as response: return json.load(response)
        snapshot=collect(get,args.member_id)
    print(json.dumps(report(snapshot),ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
