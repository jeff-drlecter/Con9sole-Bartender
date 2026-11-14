"""One-time, backed-up migration of the three existing news channels. No messages."""
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
import aiohttp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from features.news_channel_categories import CHANNELS,LABELS,ROLE_NAMES,LEGACY_PROMPT,VIEW,category_prompts,category_overwrites,can_view,overwrite_signature,prompt_signature,required_questions_ready
import config

ROOT=Path('/data/news_channel_categories')
STATE=ROOT/'applied.json'


async def main():
    if os.getenv('NEWS_CATEGORY_MIGRATION')!='20261114-v1': return
    if STATE.exists():
        print('News channel categories already applied; no settings rewritten.');return
    ROOT.mkdir(exist_ok=True)
    token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
    async with aiohttp.ClientSession(headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/1.0'},timeout=aiohttp.ClientTimeout(total=30)) as session:
        async def api(method,path,body=None):
            for attempt in range(5):
                async with session.request(method,'https://discord.com/api/v10/'+path,json=body,
                    headers={'X-Audit-Log-Reason':quote('Member-selected PS/Xbox/PC news categories')}) as r:
                    if r.status==429:
                        data=await r.json()
                        delay=float(data.get('retry_after',5))
                        if attempt==4 or delay>60: raise RuntimeError('Discord migration rate limit; state retained')
                        await asyncio.sleep(max(1,delay));continue
                    if r.status>=400: raise RuntimeError(f'Discord migration HTTP {r.status}')
                    return await r.json() if r.status!=204 else None
        base=f'guilds/{config.GUILD_ID}'
        guild=await api('GET',base)
        roles=await api('GET',base+'/roles')
        identity=await api('GET','users/@me')
        me=await api('GET',base+f"/members/{identity['id']}")
        permissions=0
        for role in roles:
            if role['id']==str(config.GUILD_ID) or role['id'] in me['roles']:
                permissions|=int(role['permissions'])
        if not (permissions & 8) and permissions & ((1<<28)|32|16)!=((1<<28)|32|16):
            raise ValueError('Bot lacks required onboarding/role/channel management permissions')
        before=await api('GET',base+'/onboarding')
        channels={k:await api('GET',f'channels/{cid}') for k,cid in CHANNELS.items()}
        if any(c['guild_id']!=str(config.GUILD_ID) or c['type'] not in (0,5) for c in channels.values()):
            raise ValueError('Unexpected target channels')
        existing={key:next((r['id'] for r in roles if r['name']==name and not r['managed'] and int(r['permissions'])==0),None)
                  for key,name in ROLE_NAMES.items()}
        already_categorized=all(existing.values()) and any(set(LABELS.values()) <= {o['title'] for o in p['options']} for p in before['prompts'])
        # A previous run may have completed the writes and stopped at strict metadata verification.
        if already_categorized:
            category_prompts(before['prompts'],existing)
            privileged={str(r['id']) for r in roles if int(r['permissions']) & (8|32)}|{str(config.MOD_ROLE_ID),*map(str,config.HELPER_ROLE_IDS)}
            ordinary=[r['id'] for r in roles if not r.get('managed') and r['id'] not in privileged|set(existing.values())]
            for key,channel in channels.items():
                for choice in ([],*[ [rid] for rid in existing.values()],list(existing.values())):
                    member=dict(user=dict(id='0'),roles=ordinary+choice)
                    if can_view(config.GUILD_ID,roles,member,channel)!=(existing[key] in choice):
                        raise ValueError('Previously written news permissions require review')
            all_channels=await api('GET',base+'/channels')
            if any(c['id'] not in set(map(str,CHANNELS.values())) and any(o['type']==0 and o['id'] in existing.values() for o in c.get('permission_overwrites',[])) for c in all_channels):
                raise ValueError('Category roles have unrelated channel access')
            original=json.loads((ROOT/'before.json').read_text())
            area_id=next(p['id'] for p in before['prompts'] if p['title']=='想開啟哪些區域？（選填，可複選）')
            differences=[]
            for prompt in original['onboarding']['prompts']:
                if prompt['id'] in (area_id,LEGACY_PROMPT): continue
                current=next((p for p in before['prompts'] if p['id']==prompt['id']),None)
                if current is None:
                    differences.append(prompt['title']);continue
                if prompt_signature(current)!=prompt_signature(prompt): differences.append(prompt['title'])
            if differences:
                # Keep diagnostics private: do not publish question text or role mappings.
                (ROOT/'unrelated-question-differences.json').write_text(json.dumps({'before':original['onboarding']['prompts'],'current':before['prompts']},ensure_ascii=False))
                # The historical backup predates independent optional-area/streaming edits.
                # Recovery is read-only: retain current unrelated questions, never restore that snapshot.
                # Current mandatory game/platform questions were inspected in the member UI.
                # IDs/history can be regenerated by upstream onboarding edits; do not restore them.
                if not required_questions_ready(before['prompts']):
                    raise ValueError('Current mandatory game/platform questions need review')
                print(json.dumps({'news_category_recovery':'preserved_current_unrelated_questions','historical_differences':len(differences)}),flush=True)
            temporary=STATE.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(version=1,role_ids=existing,channel_ids=CHANNELS),indent=2))
            temporary.replace(STATE)
            print(json.dumps({'news_categories':'verified_after_metadata_normalization','categories':list(LABELS.values()),'modeled_access':'pass','native_options':'verified','announcements_sent':0},ensure_ascii=False))
            return
        # Plan before any mutation, including exact optional-area/legacy question checks.
        category_prompts(before['prompts'],{k:'0' for k in CHANNELS})
        members=[]
        after='0'
        for _ in range(20):
            batch=await api('GET',base+f'/members?limit=1000&after={after}')
            members.extend(batch)
            if len(batch)<1000: break
            after=batch[-1]['user']['id']
        else: raise ValueError('Member snapshot exceeds bounded migration')
        rolemap={str(r['id']):r for r in roles}
        privileged={str(r['id']) for r in roles if int(r['permissions']) & (8|32)}|{str(config.MOD_ROLE_ID),*map(str,config.HELPER_ROLE_IDS)}
        current_readers={k:[m['user']['id'] for m in members if can_view(config.GUILD_ID,roles,m,c,guild['owner_id'])] for k,c in channels.items()}
        for c in channels.values():
            for o in c.get('permission_overwrites',[]):
                if o['type']==1 and int(o['allow']) & VIEW:
                    member=next((m for m in members if m['user']['id']==o['id']),None)
                    if member and not member['user'].get('bot') and not set(member['roles']) & privileged and member['user']['id']!=guild['owner_id']:
                        raise ValueError('Individual news access exception needs review')
        backup=ROOT/'before.json'
        if not backup.exists():
            backup.write_text(json.dumps(dict(onboarding=before,channels=channels,roles=roles,readers=current_readers),ensure_ascii=False,indent=2))
        selected={}
        for key,name in ROLE_NAMES.items():
            found=[r for r in roles if r['name']==name]
            if len(found)>1 or (found and (found[0]['managed'] or int(found[0]['permissions']))):
                raise ValueError('Unsafe or duplicate category role')
            role=found[0] if found else await api('POST',base+'/roles',dict(name=name,permissions='0',mentionable=False,hoist=False))
            selected[key]=role['id']
            (ROOT/'roles.json').write_text(json.dumps(selected))
        all_channels=await api('GET',base+'/channels')
        if any(c['id'] not in set(map(str,CHANNELS.values())) and any(o['type']==0 and o['id'] in selected.values() for o in c.get('permission_overwrites',[])) for c in all_channels):
            raise ValueError('Category roles have unrelated channel access; refusing assignments')
        fresh=await api('GET',base+'/onboarding')
        if fresh!=before: raise ValueError('Onboarding changed during preparation; not overwritten')
        wanted=category_prompts(before['prompts'],selected)
        planned=sum(1 for key,reader_ids in current_readers.items() for m in members
                    if m['user']['id'] in reader_ids and not m['user'].get('bot')
                    and not set(m['roles']) & privileged and m['user']['id']!=guild['owner_id']
                    and selected[key] not in m['roles'])
        print(json.dumps({'news_category_phase':'assignments','remaining':planned}),flush=True)
        completed=0
        # Bounded workers; reread each member once and only add missing roles.
        # Never replace a whole role list or replay completed assignments on resume.
        semaphore=asyncio.Semaphore(3)
        async def preserve_member(member):
            nonlocal completed
            if member['user'].get('bot') or set(member['roles']) & privileged or member['user']['id']==guild['owner_id']:
                return
            needed=[key for key,reader_ids in current_readers.items()
                    if member['user']['id'] in reader_ids and selected[key] not in member['roles']]
            if not needed: return
            async with semaphore:
                current_member=await api('GET',base+f"/members/{member['user']['id']}")
                for key in needed:
                    if not can_view(config.GUILD_ID,roles,current_member,channels[key],guild['owner_id']):
                        continue
                    if selected[key] not in current_member['roles']:
                        await api('PUT',base+f"/members/{member['user']['id']}/roles/{selected[key]}")
                    completed+=1
                    if completed%50==0:
                        print(json.dumps({'news_category_phase':'assignments','completed':completed,'planned':planned}),flush=True)
        await asyncio.gather(*(preserve_member(member) for member in members))
        print(json.dumps({'news_category_phase':'channel_permissions','assignments_completed':completed}),flush=True)
        for key,channel in channels.items():
            fresh=await api('GET',f"channels/{channel['id']}")
            if overwrite_signature(fresh['permission_overwrites'])!=overwrite_signature(channel['permission_overwrites']):
                raise ValueError('Channel overwrites changed; not overwritten')
            bot_roles=set()
            for member in members:
                if member['user'].get('bot') and member['user']['id'] in current_readers[key]:
                    bot_roles.update(rid for rid in member['roles'] if rolemap.get(rid,{}).get('tags',{}).get('bot_id'))
                elif member['user']['id'] in current_readers[key]:
                    bot_roles.update(set(member['roles']) & privileged)
            overwrites=category_overwrites(config.GUILD_ID,channel,selected[key],set(selected.values()),privileged,bot_roles)
            await api('PATCH',f"channels/{channel['id']}",dict(permission_overwrites=overwrites))
            actual=await api('GET',f"channels/{channel['id']}")
            ordinary=[r['id'] for r in roles if not r.get('managed') and r['id'] not in privileged|set(selected.values())]
            for combination in ([],*[ [rid] for rid in selected.values()],list(selected.values())):
                modeled=dict(user=dict(id='0'),roles=ordinary+combination)
                expected=selected[key] in combination
                if can_view(config.GUILD_ID,roles+[dict(id=rid,permissions='0') for rid in selected.values()],modeled,actual)!=expected:
                    raise ValueError('News permission model did not match selection')
        if (await api('GET',base+'/onboarding'))!=before:
            raise ValueError('Onboarding changed before final write; not overwritten')
        await api('PUT',base+'/onboarding',dict(prompts=wanted))
        actual=await api('GET',base+'/onboarding')
        category_prompts(actual['prompts'],selected)
        # Confirm every unrelated question is byte-equivalent at the JSON value level.
        target=next(p['id'] for p in wanted if p['title']=='想開啟哪些區域？（選填，可複選）')
        unchanged=[p for p in before['prompts'] if p['id'] not in (target,LEGACY_PROMPT)]
        if any(not any(prompt_signature(p)==prompt_signature(q) for q in actual['prompts']) for p in unchanged):
            (ROOT/'unrelated-question-differences.json').write_text(json.dumps({'before':before['prompts'],'current':actual['prompts']},ensure_ascii=False))
            raise ValueError('Unrelated editable onboarding question changed')
        temporary=STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(version=1,role_ids=selected,channel_ids=CHANNELS),indent=2))
        temporary.replace(STATE)
        print(json.dumps(dict(news_categories='applied',categories=list(LABELS.values()),
            prior_reader_assignments=sum(len(v) for v in current_readers.values()),
            modeled_access='pass',native_options='verified',announcements_sent=0),ensure_ascii=False))


if __name__=='__main__': asyncio.run(main())
