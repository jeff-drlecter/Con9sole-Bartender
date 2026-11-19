"""Jeff-approved, bounded maintenance. Audit first; apply only a reviewed digest.

No POST, DELETE, new messages, role assignments, bulk overwrites or category sync.
Raw snapshots/backups stay in /data (0600); stdout contains only redacted changes.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from core.json_storage import atomic_write_json
from features.news_access_audit import permissions, access

GUILD=str(config.GUILD_ID)
CATEGORY='1424877575850692719'
BOARD='1570639281225994301'
DEMO='1570093470666854411'
GUIDE=str(config.GUIDE_CHANNEL_ID)
WELCOME=str(config.WELCOME_CHANNEL_ID)
# The November 15 approval covered this specific channel overwrite.
SUPPORT='1362781427287986407'
NEWS={'1364201334798290994':'PlayStation','1379699174668505098':'Xbox','1364210080043630612':'PC'}
VIEW_HISTORY=1024|65536
SUPPORT_BITS=VIEW_HISTORY|2048
NONE={'parse':[], 'users':[], 'roles':[], 'replied_user':False}
NEW_ENTRY='🎮 **找隊友，約一局**\n選擇遊戲後約一局；找不到合適遊戲可按「求助／建議」，或先觀望。\n下方操作只向自己顯示；提交約局後才會在所選頻道公開。'
DEMO_COPY='🧪 **Helper 虛構示範**\n這裡是虛構示例，可查看歷史。正式 Helper 活動資料只供有權限的 Helpers。\n回饋請使用你可存取的「求助／建議」入口；按下方按鈕查看示例。'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def controls(message):
    return {c.get('custom_id') for row in message.get('components',[]) for c in row.get('components',[])}


def channel_guard(c):
    keys=('id','guild_id','type','name','parent_id','position','nsfw','topic','permission_overwrites')
    result={k:c.get(k) for k in keys}
    result['permission_overwrites']=sorted(c.get('permission_overwrites',[]),key=lambda o:(str(o['id']),o['type']))
    return result


def message_guard(m):
    return dict(id=m['id'],channel_id=m['channel_id'],author=m['author']['id'],
                **{k:m.get(k) for k in ('content','embeds','components','attachments','flags')})


def entry_components():
    groups=((('games','🎮 選擇遊戲'),('menu','🍸 開啟功能')),
            (('plan','📅 約一局'),('language','🌐 語言設定')),
            (('help','求助／建議'),('observe','先觀望')))
    return [dict(type=1,components=[dict(type=2,style=2,label=label,custom_id=f'entry:{key}:v1') for key,label in row]) for row in groups]


def build_plan(snapshot, bot_id, messages, panel_ids):
    if str(snapshot['guild']['id'])!=GUILD:raise ValueError('Unexpected guild')
    channels={str(c['id']):c for c in snapshot['channels']}
    roles=snapshot['roles']
    plan=dict(actions=[],blocked=[],checks={},roles_digest=digest(roles))
    def add(kind,cid,body,message=None,overwrite=None):
        c=channels[cid]
        if str(c.get('guild_id'))!=GUILD:raise ValueError('Wrong target guild')
        action=dict(kind=kind,channel=cid,body=body,before_channel=channel_guard(c))
        if message is not None:
            if str(message['author']['id'])!=str(bot_id) or str(message['channel_id'])!=cid:raise ValueError('Not owned message')
            action.update(message=str(message['id']),before_message=message_guard(message))
        if overwrite is not None:action['overwrite']=str(overwrite)
        plan['actions'].append(action)
    c=channels.get(CATEGORY)
    if c and c['type']==4 and c['name'].count('即時情報站')==1:
        add('news_name',CATEGORY,dict(name=c['name'].replace('即時情報站','遊戲情報站')))
    elif not c or c['type']!=4 or '遊戲情報站' not in c['name']:
        plan['blocked'].append('news_name: unexpected category identity/name')
    for cid,label in NEWS.items():
        wanted=panel_ids.get(cid)
        candidates=[m for m in messages.get(cid,[]) if str(m['id'])==str(wanted) and str(m['author']['id'])==str(bot_id)]
        ids={'rss:card:news:v1','rss:card:preferences:v1','rss:card:channels:v1'}
        if cid not in channels or len(candidates)!=1 or controls(candidates[0])!=ids:
            plan['blocked'].append('news_panel:'+cid+': missing exact owned panel');continue
        m=candidates[0];components=deepcopy(m['components'])
        for row in components:
            for button in row['components']:
                if button.get('custom_id')=='rss:card:preferences:v1':button['label']='情報設定'
        content=f'📰 **{label} 情報**\n每日香港時間 19:00 摘要，每類最多 8 篇；沒有內容便不發送。\n按「我的情報」查看個人結果；「情報設定」分開管理頻道顯示與個人篩選。\n手機推播由 Discord 通知設定控制。\n操作結果只有你看得到，無需輸入指令。'
        if m.get('content')!=content or m['components']!=components:
            add('news_panel',cid,dict(content=content,components=components,allowed_mentions=NONE),message=m)
    # Only a unique owned functional card. Welcome requires pinned/non-personal copy.
    for cid in (GUIDE,WELCOME):
        candidates=[m for m in messages.get(cid,[]) if str(m['author']['id'])==str(bot_id)
                    and controls(m).intersection({'entry:menu:v1', 'entry:menu:v2'}) and not m.get('mentions')
                    and (cid!=WELCOME or m.get('pinned'))]
        if len(candidates)!=1:
            plan['blocked'].append('entry:'+cid+': no unique non-personal fixed card');continue
        m=candidates[0]
        if 'entry:menu:v2' in controls(m):
            continue  # Newer entry cards are outside this historical migration.
        if m.get('content')!=NEW_ENTRY or controls(m)!={f'entry:{k}:v1' for k in ('games','menu','plan','language','help','observe')}:
            add('entry',cid,dict(content=NEW_ENTRY,components=entry_components(),allowed_mentions=NONE),message=m)
    candidates=[m for m in messages.get(DEMO,[]) if str(m['author']['id'])==str(bot_id)
                and 'helper:sandbox:create:v1' in controls(m)]
    if len(candidates)==1:
        m=candidates[0]
        body=dict(content=DEMO_COPY,components=[dict(type=1,components=[dict(type=2,style=1,label='查看虛構示例',custom_id='helper:sandbox:create:v1')])],allowed_mentions=NONE)
        if m.get('content')!=DEMO_COPY or controls(m)!={'helper:sandbox:create:v1'}:
            add('demo',DEMO,body,message=m)
    else:plan['blocked'].append('demo: no unique owned example card')
    # Permission changes follow content updates, and preserve all unrelated bits.
    testers=[r for r in roles if r['name']=='🧪 Tester' and not r.get('managed')]
    if len(testers)==1 and BOARD in channels:
        role=str(testers[0]['id']);board=channels[BOARD]
        ow=next((o for o in board.get('permission_overwrites',[]) if str(o['id'])==role and o['type']==0),None)
        after_board=deepcopy(board)
        for item in after_board.get('permission_overwrites',[]):
            if str(item['id'])==role and item['type']==0:item['allow']=str(int(item['allow'])&~VIEW_HISTORY)
        for label,ids in [('tester',[role]),('verified_tester',[str(config.VERIFIED_ROLE_ID),role]),('helper_tester',[str(config.VERIFIED_ROLE_ID),role,*map(str,config.HELPER_ROLE_IDS)])]:
            member=dict(user=dict(id='0'),roles=ids)
            plan['checks'][label+'_board_after']=access(permissions(GUILD,roles,member,after_board))['summary_visible']
        if ow and int(ow['allow'])&VIEW_HISTORY:
            if not plan['checks']['helper_tester_board_after']:
                plan['blocked'].append('tester_scope: Helper visibility would be lost')
            else:
                after=dict(type=0,allow=str(int(ow['allow'])&~VIEW_HISTORY),deny=str(ow['deny']))
                add('tester_scope',BOARD,after,overwrite=role)
    else:plan['blocked'].append('tester_scope: ambiguous role or missing dashboard')
    problems=[c for c in channels.values() if '問題回報' in c['name']]
    if len(problems)==1:
        c=problems[0]
        if c.get('nsfw'):
            if re.search(r'18\+|NSFW|成人|R18',c.get('topic') or '',re.I):
                plan['blocked'].append('problem_age: explicit age-restricted topic requires review')
            else:add('problem_age',str(c['id']),dict(nsfw=False))
        plan['checks']['problem_age_before']=bool(c.get('nsfw'))
        plan['checks']['problem_channel_identified']=True
    else:plan['blocked'].append('problem_age: ambiguous target')
    if SUPPORT in channels:
        c=channels[SUPPORT]
        for label,ids in [('newcomer',[]),('verified_no_game',[str(config.VERIFIED_ROLE_ID)])]:
            a=access(permissions(GUILD,roles,dict(user=dict(id='0'),roles=ids),c))
            plan['checks'][label+'_support_permissions']=a['view'] and a['history'] and a['send']
        # Do not bypass unverified membership gates. Only Verified gets a minimal grant if needed.
        if not plan['checks']['verified_no_game_support_permissions']:
            if c['type'] not in (0,15) or c.get('nsfw'):
                plan['blocked'].append('support: type/age gate requires post-age-change audit')
            else:
                role=str(config.VERIFIED_ROLE_ID)
                ow=next((o for o in c.get('permission_overwrites',[]) if str(o['id'])==role and o['type']==0),dict(allow='0',deny='0'))
                add('support',SUPPORT,dict(type=0,allow=str(int(ow['allow'])|SUPPORT_BITS),deny=str(int(ow['deny'])&~SUPPORT_BITS)),overwrite=role)
        plan['checks']['support_age_restricted']=bool(c.get('nsfw'))
    else:plan['blocked'].append('support: missing configured target')
    return plan


class API:
    def __init__(self):
        token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
        if not token:raise RuntimeError('Bot credential unavailable')
        self.headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/approved-maintenance'}
    def call(self,method,path,body=None):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect prohibited')
        if method not in ('GET','PATCH','PUT'):raise ValueError('Method prohibited')
        if not re.fullmatch(r'(users/@me|guilds/\d+(/roles|/channels)?|channels/\d+(/messages(/\d+|/pins)?|/permissions/\d+)?)(\?limit=100)?',path):raise ValueError('Route prohibited')
        if method != 'GET' and (body is None or not re.fullmatch(r'channels/\d+(/messages/\d+|/permissions/\d+)?',path)):
            raise ValueError('Write route prohibited')
        request=urllib.request.Request('https://discord.com/api/v10/'+path,method=method,
             headers={**self.headers,'Content-Type':'application/json'},data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=20) as response:
                payload=response.read();return json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:raise RuntimeError(f'Discord request failed ({exc.code}); no automatic retry') from None


def collect(api,root):
    snap=dict(guild=api.call('GET','guilds/'+GUILD),roles=api.call('GET','guilds/'+GUILD+'/roles'),channels=api.call('GET','guilds/'+GUILD+'/channels'))
    me=api.call('GET','users/@me')['id'];messages={};panels={}
    path=root/'rss_sandbox_preferences.sqlite3'
    if path.is_file():
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            panels={str(cid):str(mid) for cid,mid in db.execute("SELECT channel_id,message_id FROM panels WHERE state='posted'")}
    for cid in NEWS:
        try:messages[cid]=[api.call('GET',f'channels/{cid}/messages/{panels[cid]}')] if cid in panels else []
        except RuntimeError:messages[cid]=[]
    for cid in (GUIDE,WELCOME,DEMO):
        try:messages[cid]=api.call('GET',f'channels/{cid}/messages?limit=100')
        except RuntimeError:messages[cid]=[]
        try:
            pins=api.call('GET',f'channels/{cid}/messages/pins')
            if pins.get('has_more'):
                # Do not infer uniqueness from a truncated fixed-card inventory.
                messages[cid]=[];continue
            combined={str(m['id']):m for m in messages[cid]}
            for item in pins['items']:
                m=item['message'];combined[str(m['id'])]={**m,'pinned':True}
            messages[cid]=list(combined.values())
        except RuntimeError:
            if cid==WELCOME:messages[cid]=[]
    return snap,me,messages,panels


def summary(plan):
    result=[]
    for a in plan['actions']:
        item=dict(kind=a['kind'])
        if a['kind']=='news_name':item.update(before=a['before_channel']['name'],after=a['body']['name'])
        elif a['kind']=='tester_scope':item['change']='remove only Tester View/History allow; preserve deny and other bits'
        elif a['kind']=='support':item['change']='Verified only: add View/History/Send; preserve other bits'
        elif a['kind']=='problem_age':item.update(before=True,after=False)
        else:item['change']='edit existing owned fixed card, no ping/new message'
        result.append(item)
    return dict(actions=result,checks=plan['checks'],blocked=plan['blocked'])


def apply(api,plan,save):
    if digest(api.call('GET','guilds/'+GUILD+'/roles'))!=plan['roles_digest']:raise ValueError('Roles changed; audit again')
    results=[]
    for a in plan['actions']:
        cid=a['channel'];current=api.call('GET','channels/'+cid)
        if channel_guard(current)!=a['before_channel']:
            results.append(dict(kind=a['kind'],state='blocked: channel changed'));continue
        if 'message' in a:
            path=f"channels/{cid}/messages/{a['message']}";current_message=api.call('GET',path)
            if message_guard(current_message)!=a['before_message']:
                results.append(dict(kind=a['kind'],state='blocked: message changed'));continue
            method='PATCH'
        elif 'overwrite' in a:path=f"channels/{cid}/permissions/{a['overwrite']}";method='PUT'
        else:path='channels/'+cid;method='PATCH'
        results.append(dict(kind=a['kind'],state='uncertain'))
        save(results) # durable before any write; unknown writes are never blindly replayed
        api.call(method,path,a['body'])
        after=api.call('GET',f"channels/{cid}/messages/{a['message']}" if 'message' in a else 'channels/'+cid)
        if 'message' in a:
            good=all(after.get(k)==v for k,v in a['body'].items() if k not in ('allowed_mentions','components'))
            # Discord can assign component numeric IDs; compare semantic fields.
            def semantic(value):
                if isinstance(value,dict):
                    value={k:semantic(v) for k,v in value.items() if k!='id'}
                    if value.get('type')==2:value.setdefault('disabled',False)
                    return value
                if isinstance(value,list):return [semantic(v) for v in value]
                return value
            good=good and semantic(after.get('components'))==semantic(a['body']['components'])
            after_guard=message_guard(after)
            good=good and all(after_guard.get(k)==v for k,v in a['before_message'].items()
                              if k not in ('content','components'))
        elif 'overwrite' in a:
            ow=next((o for o in after.get('permission_overwrites',[]) if str(o['id'])==a['overwrite'] and o['type']==0),{})
            good=all(str(ow.get(k))==str(v) for k,v in a['body'].items())
        else:good=all(after.get(k)==v for k,v in a['body'].items())
        if 'message' not in a:
            expected=deepcopy(a['before_channel'])
            if 'overwrite' in a:
                expected['permission_overwrites']=[o for o in expected['permission_overwrites']
                    if not (str(o['id'])==a['overwrite'] and o['type']==0)]
                expected['permission_overwrites'].append(dict(id=a['overwrite'],**a['body']))
            else:expected.update(a['body'])
            good=good and channel_guard(after)==channel_guard(expected)
        if not good:raise RuntimeError('Readback differs; inspect private journal before proceeding')
        results[-1]['state']='verified';save(results)
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--operation',choices=('audit','apply','status'),required=True)
    parser.add_argument('--digest',default='');parser.add_argument('--script-sha',required=True);args=parser.parse_args()
    if args.script_sha!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('Deployed maintenance script differs from reviewed main')
    root=Path(os.getenv('DRINK_DATA_DIR','/data')).resolve();folder=root/'approved_community_20261115'
    folder.mkdir(mode=0o700,exist_ok=True);folder.chmod(0o700);os.umask(0o077)
    api=API()
    if args.operation=='audit':
        snap,me,messages,panels=collect(api,root);plan=build_plan(snap,me,messages,panels)
        key=digest(plan);record=dict(created=time.time(),plan=plan,snapshot=snap,messages=messages)
        path=folder/(key+'.json');atomic_write_json(path,record);path.chmod(0o600)
        print(json.dumps(dict(digest=key,**summary(plan)),ensure_ascii=False))
    else:
        if not re.fullmatch('[0-9a-f]{64}',args.digest):raise ValueError('Exact audit digest required')
        record=json.loads((folder/(args.digest+'.json')).read_text());plan=record['plan']
        if args.operation=='status':
            path=folder/(args.digest+'.results.json')
            print(json.dumps(dict(results=json.loads(path.read_text()) if path.exists() else [], **summary(plan)),ensure_ascii=False))
            return
        if digest(plan)!=args.digest or not 0<=time.time()-record['created']<1800:raise ValueError('Stale/changed review; audit again')
        journal=folder/(args.digest+'.results.json')
        if journal.exists():raise ValueError('Already attempted; inspect results and audit current state instead of replaying')
        results=apply(api,plan,lambda r:atomic_write_json(journal,r))
        print(json.dumps(dict(results=results,private_backup=True,no_new_messages=True),ensure_ascii=False))

if __name__=='__main__':main()
