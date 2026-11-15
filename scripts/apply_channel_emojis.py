"""Name-only migration for Jeff's approved emoji proposal. No messages or role edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from core.channel_names import plain_channel_name, is_squad_chat_name
from core.json_storage import atomic_write_json
from scripts.apply_approved_community import API, GUILD, digest, channel_guard, apply

PROPOSED={
 '如何加入不同遊戲分區':'🧭', 'rules':'📜', '公告-伺服器更新':'📣',
 '官方資訊-discord':'ℹ️', '新成員-加入-打招呼':'👋', '留game-tag（非聊天）':'🆔',
 '站務-意見箱':'📮', '感謝金主':'💛', '家用夠の成員等級日誌':'🏅',
 'ps-news':'🔵', 'xbox-news':'🟢', '電腦-news':'🖥️',
 '成員直播':'📺', '友台直播':'🤝', '直播相關':'💬', '家用夠資源區':'📚',
 '由此開始':'📍', '驗收手記':'🔍', '體驗交流':'💬', '問題回報':'🐛',
 '情報示範':'📰', 'helper示範':'🛠️',
}
KNOWN_IDS={
 '如何加入不同遊戲分區':str(config.GUIDE_CHANNEL_ID), 'rules':str(config.RULES_CHANNEL_ID),
 '新成員-加入-打招呼':str(config.WELCOME_CHANNEL_ID),
 # SUPPORT is a separate help destination, not the uniquely named suggestion box.
 'ps-news':'1364201334798290994','xbox-news':'1379699174668505098','電腦-news':'1364210080043630612',
}


def build_plan(snapshot,scope):
    if str(snapshot['guild']['id'])!=GUILD or scope not in ('chats','all'):raise ValueError('Wrong guild/scope')
    channels=snapshot['channels'];by_id={str(c['id']):c for c in channels}
    excluded={str(config.TEMPLATE_CATEGORY_ID)}
    for c in channels:
        if c['type']==4 and plain_channel_name(c['name']) in ('封存','存檔區','隱藏區域','sample-template'):
            excluded.add(str(c['id']))
    eligible=[c for c in channels if c['type'] in (0,5,15) and str(c.get('parent_id')) not in excluded]
    plan=dict(scope=scope,roles_digest=digest(snapshot['roles']),actions=[],blocked=[],unchanged=0,matched_chats=0)
    def add(c,name,kind):
        if str(c.get('guild_id'))!=GUILD:raise ValueError('Wrong channel guild')
        if len(name)>100:plan['blocked'].append(kind+': name too long');return
        if c['name']==name:plan['unchanged']+=1;return
        plan['actions'].append(dict(kind=kind,channel=str(c['id']),body=dict(name=name),before_channel=channel_guard(c)))
    for c in eligible:
        if c['type']==0 and is_squad_chat_name(c['name']):
            plan['matched_chats']+=1
            add(c,c['name'].removesuffix('💬').rstrip()+'💬','squad_chat')
    if scope=='all':
        for base,emoji in PROPOSED.items():
            matches=[c for c in eligible if c['name']==base+emoji or plain_channel_name(c['name'])==base]
            if len(matches)!=1:
                plan['blocked'].append(base+': missing or ambiguous');continue
            if base in KNOWN_IDS and str(matches[0]['id'])!=KNOWN_IDS[base]:
                plan['blocked'].append(base+': configured ID differs');continue
            add(matches[0],base+emoji,'fixed:'+base)
    return plan


def summary(plan):
    return dict(scope=plan['scope'],matched_chats=plan['matched_chats'],unchanged=plan['unchanged'],
      changes=[dict(kind=a['kind'],after=a['body']['name'] if a['kind'].startswith('fixed:') else 'existing-game-prefix-吹水組隊💬') for a in plan['actions']],blocked=plan['blocked'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--operation',choices=('audit','apply','status'),required=True)
    parser.add_argument('--scope',choices=('chats','all'),default='chats');parser.add_argument('--digest',default='')
    parser.add_argument('--script-sha',required=True);args=parser.parse_args()
    if args.script_sha!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('Deployed script differs from main')
    os.umask(0o077)
    folder=Path(os.getenv('DRINK_DATA_DIR','/data'))/'channel_emoji_suffixes';folder.mkdir(mode=0o700,exist_ok=True);folder.chmod(0o700)
    api=API()
    if args.operation=='audit':
        snapshot=dict(guild=api.call('GET','guilds/'+GUILD),roles=api.call('GET','guilds/'+GUILD+'/roles'),channels=api.call('GET','guilds/'+GUILD+'/channels'))
        plan=build_plan(snapshot,args.scope);key=digest(plan)
        atomic_write_json(folder/(key+'.json'),dict(created=time.time(),plan=plan,snapshot=snapshot))
        print(json.dumps(dict(digest=key,**summary(plan)),ensure_ascii=False));return
    if not re.fullmatch('[0-9a-f]{64}',args.digest):raise ValueError('Exact audit digest required')
    record=json.loads((folder/(args.digest+'.json')).read_text());plan=record['plan'];journal=folder/(args.digest+'.results.json')
    if digest(plan)!=args.digest or plan['scope']!=args.scope:raise ValueError('Changed digest/scope')
    if args.operation=='status':
        print(json.dumps(dict(results=json.loads(journal.read_text()) if journal.exists() else [],**summary(plan)),ensure_ascii=False));return
    if not 0<=time.time()-record['created']<1800 or journal.exists():raise ValueError('Stale/already attempted audit; inspect and audit again')
    # Fresh parent identity guards prevent moving a target into an excluded area after audit.
    current=api.call('GET','guilds/'+GUILD+'/channels');parents={str(c['id']):channel_guard(c) for c in current if c['type']==4}
    old_parents={str(c['id']):channel_guard(c) for c in record['snapshot']['channels'] if c['type']==4}
    if parents!=old_parents:raise ValueError('Categories changed; audit again')
    results=apply(api,plan,lambda r:atomic_write_json(journal,r))
    print(json.dumps(dict(results=results,name_only=True,private_backup=True),ensure_ascii=False))

if __name__=='__main__':main()
