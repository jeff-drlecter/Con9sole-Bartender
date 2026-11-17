"""Default-off, exact-scope trial configuration in the existing squad JSON.

No names, URLs, environment secrets, or server-wide enable switch grant access.
Cached checks only hide controls/fail closed; permission decisions use fresh REST
objects through voice_invites.authorize and the admin configuration command.
"""
from __future__ import annotations

import time
import uuid
import discord

_UNSET = object()
_KEYS = {'schema', 'enabled', 'guild', 'category', 'destination', 'testers', 'revision'}


class TrialDenied(ValueError):
    pass


def settings(cog):
    value = getattr(cog, 'state', {}).get('voice_invite_trial')
    if not isinstance(value, dict) or set(value) != _KEYS:
        return None
    if type(value['schema']) is not int or value['schema'] != 1 or value['enabled'] is not True:
        return None
    if any(type(value[key]) is not int or value[key] <= 0 for key in ('guild','category','destination')):
        return None
    users = value['testers']
    if (not isinstance(users, list) or not 1 <= len(users) <= 2
            or any(type(uid) is not int or uid <= 0 for uid in users) or len(set(users)) != len(users)):
        return None
    revision = value['revision']
    if not isinstance(revision, str) or len(revision) != 32 or any(c not in '0123456789abcdef' for c in revision):
        return None
    return value


def route(cog, category_id):
    value = cog.state.get('settings', {})
    routes = value.get('routes', {})
    return routes.get(str(category_id), value.get('destination') if value.get('category') == category_id else None)


def require(cog, voice, destination, user_id, *, guild_id=None, revision=_UNSET):
    value = settings(cog)
    if value is None:
        raise TrialDenied('語音邀請試行未啟用；原有房控及招募卡照常使用。')
    if (guild_id is not None and guild_id != value['guild']
            or getattr(getattr(voice, 'guild', None), 'id', None) != value['guild']
            or getattr(getattr(destination, 'guild', None), 'id', None) != value['guild']
            or getattr(voice, 'category_id', None) != value['category']
            or getattr(destination, 'category_id', None) != value['category']
            or getattr(destination, 'id', None) != value['destination']
            or route(cog, value['category']) != value['destination']):
        raise TrialDenied('呢間房或目的頻道唔屬於已核准嘅精確試行範圍。')
    if user_id not in value['testers']:
        raise TrialDenied('只限已登記嘅試行帳號使用招人入隊。')
    if revision is not _UNSET and revision != value['revision']:
        raise TrialDenied('本局分享所用嘅試行設定已失效，未建立新邀請。')
    return value


def visible(cog, voice, user_id):
    if cog is None or voice is None or user_id is None:
        return False
    value = settings(cog)
    if value is None:
        return False
    try:
        require(cog, voice, cog.bot.get_channel(value['destination']), user_id)
    except TrialDenied:
        return False
    return True


async def configuration(cog, guild, interaction, category, destination, testers):
    """Called under the squad lock, after a fresh server-admin check."""
    if category is None or destination is None or not testers:
        raise TrialDenied('啟用需要指定分類、同分類目的文字頻道及一至兩個試行帳號。')
    if interaction.channel_id != destination.id:
        raise TrialDenied('請喺指定試行目的文字頻道內設定，唔會由其他頻道啟用。')
    fresh_category = await guild.fetch_channel(category.id)
    fresh_destination = await guild.fetch_channel(destination.id)
    if (not isinstance(fresh_category, discord.CategoryChannel)
            or not isinstance(fresh_destination, discord.TextChannel)
            or fresh_category.guild.id != guild.id or fresh_destination.guild.id != guild.id
            or fresh_destination.category_id != fresh_category.id
            or route(cog, fresh_category.id) != fresh_destination.id):
        raise TrialDenied('分類、目的頻道及既有招募 route 必須完全相符；未修改 route 或頻道權限。')
    ids = list(dict.fromkeys(member.id for member in testers))
    if not 1 <= len(ids) <= 2:
        raise TrialDenied('請指定一至兩個試行帳號。')
    actors = [await guild.fetch_member(uid) for uid in ids]
    if any(actor.bot for actor in actors):
        raise TrialDenied('試行帳號必須係真人會員。')
    actors.append(await guild.fetch_member(cog.bot.user.id))
    for actor in actors:
        vp, dp = fresh_category.permissions_for(actor), fresh_destination.permissions_for(actor)
        if not all((vp.view_channel, vp.connect, vp.create_instant_invite, dp.view_channel, dp.send_messages)):
            raise TrialDenied('試行帳號或 Bot 缺少指定分類／目的頻道所需權限；未改動任何權限。')
    permissions = fresh_destination.permissions_for(actors[-1])
    if not permissions.embed_links or not permissions.read_message_history:
        raise TrialDenied('Bot 需要目的頻道嵌入連結及讀取歷史權限。')
    from features.voice_invites import compatible_audience
    if not compatible_audience(guild, fresh_category, fresh_destination):
        raise TrialDenied('未能證明指定分類與目的頻道 audience 相容，未啟用試行。')
    return dict(schema=1, enabled=True, guild=guild.id, category=fresh_category.id,
                destination=fresh_destination.id, testers=ids, revision=uuid.uuid4().hex)


def stop(cog, session, reason):
    invite = session.get('voice_invite')
    if not invite:
        return
    invite['scope_stopped'] = True
    invite['error'] = reason
    session.pop('share_waiting', None)
    cog.save()


async def withdraw(cog, session):
    """Stop only this opt-in URL; retain the original card, view and notification policy."""
    from features import voice_invites
    await voice_invites.revoke(cog, session)
    cleanup = session.setdefault('voice_scope_cleanup', dict(state='pending', retry_at=0, deadline=time.time()+300))
    if cleanup['state'] in {'done', 'deferred'} or cleanup['retry_at'] > time.time():
        return
    if time.time() >= cleanup['deadline']:
        cleanup['state'] = 'deferred'
    else:
        cleanup['retry_at'] = time.time()+60
        cog.save()
        try:
            if session.get('message'):
                destination = cog.bot.get_channel(session['destination'])
                if destination is None:
                    raise RuntimeError('Destination unavailable')
                message = await destination.fetch_message(session['message'])
                if message.author.id != cog.bot.user.id:
                    raise RuntimeError('Card author mismatch')
                await message.edit(content=voice_invites.content(message.content, session, ended=True),
                                   allowed_mentions=discord.AllowedMentions.none())
            cleanup['state'] = 'done'
        except discord.NotFound:
            cleanup['state'] = 'done'
        except Exception as exc:
            cleanup['error'] = type(exc).__name__
            if isinstance(exc, discord.Forbidden):
                cleanup['state'] = 'deferred'
    if cleanup['state'] == 'deferred':
        cog.state.setdefault('voice_invite_cleanup_pending', {})[session['id']+':scope'] = dict(
            id=session['id'], destination=session.get('destination'), message=session.get('message'),
            cleanup=dict(cleanup))
    cog.save()


async def enforce(cog, channel, session):
    invite = session.get('voice_invite')
    if not invite:
        return
    if not invite.get('scope_stopped'):
        try:
            require(cog, channel, cog.bot.get_channel(session['destination']), invite['requester'],
                    revision=invite.get('trial_revision'))
        except TrialDenied as exc:
            stop(cog, session, str(exc))
    if invite.get('scope_stopped'):
        await withdraw(cog, session)
