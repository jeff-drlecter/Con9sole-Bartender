"""03 source-authorized queries and personal consent API; no browsing telemetry."""
from copy import copy
from types import SimpleNamespace
import discord
import config
from features.squad_plans import ACTIVE, confirmed, deadline, public_status


class AccessError(Exception):
    def __init__(self, reason): self.reason = reason


async def fresh_source(guild, actor, channel_id):
    from cogs.squad_plans import can_read
    if guild.id != config.GUILD_ID: raise AccessError('wrong_guild')
    try:
        member = copy(await guild.fetch_member(actor))
    except (discord.NotFound,discord.Forbidden): raise AccessError('denied')
    except (discord.HTTPException,OSError):raise AccessError('temporary_failure')
    try:
        channel = copy(await guild.fetch_channel(channel_id))
        if channel.guild.id!=guild.id:raise AccessError('denied')
        snapshot = copy(guild)
        snapshot._roles = {r.id:r for r in await guild.fetch_roles()}
        member.guild = snapshot; channel.guild = snapshot
        if member.bot or not can_read(SimpleNamespace(guild_id=guild.id,user=member,channel=channel)):
            raise AccessError('denied')
        return member, channel
    except discord.NotFound: raise AccessError('source_deleted')
    except discord.Forbidden: raise AccessError('denied')
    except (discord.HTTPException, OSError): raise AccessError('temporary_failure')


async def source(cog, guild, actor, plan):
    if not plan or plan['guild'] != guild.id: raise AccessError('not_found')
    member, channel = await fresh_source(guild, actor, plan['channel'])
    if not plan.get('message'): raise AccessError('unknown_result')
    try:
        message = await channel.fetch_message(plan['message'])
        if message.author.id != cog.bot.user.id: raise AccessError('source_mismatch')
    except discord.NotFound: raise AccessError('card_deleted')
    except discord.Forbidden: raise AccessError('denied')
    except (discord.HTTPException, OSError): raise AccessError('temporary_failure')
    return member, channel


def contract(p):
    return dict(guild=p['guild'],plan=p['id'],session=p.get('session'),
        source=dict(channel=p['channel'],message=p.get('message')),
        origin=p.get('origin','legacy'),created_at=p.get('created_at'),test=p.get('analytics_test'))


class PersonalReminders:
    version = 1
    def __init__(self,cog): self.cog=cog

    async def read_for_member(self,guild,actor,key):
        p=self.cog.book.get(key)
        try:
            await source(self.cog,guild,actor,p)
            p=self.cog.book.get(key)
            if actor not in p['members']: raise AccessError('not_registered')
            active=p['status'] in {'open','due','gathering'} and self.cog.book.clock() <= deadline(p)
            enabled=actor in p.get('reminders',[])
            return dict(status='ok',row=dict(id=key,game=p['game'],start=p['start'],
                status='unconfirmed' if actor in p.get('unconfirmed',[]) else p['status'],
                enabled=enabled,can_enable=active and actor in confirmed(p),can_disable=enabled,
                version=str(p.get('revision',0)),url=f"https://discord.com/channels/{guild.id}/{p['channel']}/{p['message']}"))
        except AccessError as e:return dict(status='denied' if e.reason in {'denied','wrong_guild','not_registered','not_found'} else 'unavailable',reason=e.reason)
        except (discord.HTTPException,OSError):return dict(status='unavailable',reason='temporary_failure')

    async def list_for_member(self,guild,actor):
        if guild.id!=config.GUILD_ID:return dict(complete=False,rows=[],reason='wrong_guild')
        try:
            member=await guild.fetch_member(actor)
            if member.bot:return dict(complete=False,rows=[],reason='denied')
        except (discord.HTTPException,OSError):return dict(complete=False,rows=[],reason='unavailable')
        rows=[]
        for p in self.cog.book.all():
            if p['guild']!=guild.id or actor not in p['members']:continue
            result=await self.read_for_member(guild,actor,p['id'])
            if result['status']=='ok':rows.append(result['row'])
            elif result['status']=='unavailable':
                return dict(complete=False,rows=[],reason=result.get('reason','unknown_result'))
        return dict(complete=True,rows=rows)

    async def set_for_member(self,guild,actor,key,*,enabled,expected_version):
        if type(enabled) is not bool:return dict(status='denied',reason='invalid_choice')
        async with self.cog.lock:
            result=await self.read_for_member(guild,actor,key)
            if result['status']!='ok':return result
            row=result['row']
            if row['version']!=expected_version:return dict(status='conflict',reason='revision_changed')
            if row['enabled']==enabled:return dict(status='updated',reason='unchanged',version=row['version'])
            if not row['can_enable' if enabled else 'can_disable']:return dict(status='denied',reason='state_changed')
            try:
                p=self.cog.book.set_reminder(key,actor,enabled,expected_revision=int(expected_version))
            except ValueError as e:return dict(status='conflict',reason=str(e))
            return dict(status='updated',reason='saved',version=str(p['revision']))


async def query(cog,guild,actor,*,mine=False,game=''):
    rows=[]
    for p in cog.book.all():
        if p['guild']!=guild.id or (mine and actor not in {p['owner'],*p['members']}):continue
        if not mine and (p['status'] not in ACTIVE or (p['status']!='live' and cog.book.clock()>deadline(p))):continue
        if game and game.casefold() not in p['game'].casefold():continue
        availability='available'
        try:await source(cog,guild,actor,p)
        except AccessError as e:
            if e.reason in {'denied','wrong_guild'}:continue
            if e.reason == 'temporary_failure':
                raise
            if not mine:continue
            # Do not expose source metadata if access cannot be established.
            if e.reason in {'temporary_failure','source_deleted'}:
                rows.append(dict(id=p['id'],game='約局來源',mode='',start=0,status=e.reason,availability=e.reason,group=2,url=None))
                continue
            availability=e.reason
        p=cog.book.get(p['id'])
        total=p['party']+len(confirmed(p))
        row=public_status(p);row.update(mode=p['mode'],total=total,
            remaining=None if p['capacity'] is None else max(0,p['capacity']-total),availability=availability,
            group=0 if p['status'] in {'live','gathering'} else 1 if p['status'] in {'open','due'} else 2,
            url=f"https://discord.com/channels/{guild.id}/{p['channel']}/{p['message']}" if availability=='available' else None)
        rows.append(row)
    teams=cog.bot.get_cog('Teams') if mine else None
    if teams:
        for old in teams.states.values():
            if old.guild_id!=guild.id or actor not in {old.leader_id,*old.join_now,*old.join_later}:continue
            try:
                _,ch=await fresh_source(guild,actor,old.channel_id)
                await ch.fetch_message(old.message_id)
            except (AccessError,discord.HTTPException,OSError):continue
            rows.append(dict(id='legacy:'+str(old.message_id),game='舊版招募',mode=old.mode,start=0,
                status='history' if old.cancelled or teams.is_state_expired(old) else 'due',availability='available',
                group=2 if old.cancelled or teams.is_state_expired(old) else 0,
                url=f'https://discord.com/channels/{guild.id}/{old.channel_id}/{old.message_id}'))
    return sorted(rows,key=lambda r:(r['group'],r['start'] if r['group']==1 else -r['start'],r['id']))
