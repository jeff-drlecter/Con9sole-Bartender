"""Opt-in, bounded voice invites; caller holds SquadCards.lock across each operation.

The session JSON is the write-ahead journal. An uncertain create is never replayed.
Only a known code returned by this session's unique bot create may be revoked.
"""
from __future__ import annotations

import time
import discord

MAX_AGE = 3600
RETRY_SECONDS = 60
PREFIX = '📣 本局語音邀請：'


class ShareDenied(ValueError):
    pass


def _signature(guild, channel, bit):
    return (
        tuple(sorted((r.id, bool(getattr(r.permissions, bit))) for r in guild.roles)),
        tuple(sorted((target.id, getattr(overwrite, bit))
                     for target, overwrite in channel.overwrites.items()
                     if getattr(overwrite, bit) is not None)),
    )


def compatible_audience(guild, voice, destination):
    """Sufficient permission implication for *all* role combinations, not a cache sample.

    Each required voice bit must either be universal or have exactly the destination
    view predicate. Unprovable private layouts fail closed without changing access.
    """
    default = voice.permissions_for(guild.default_role)
    for bit in ('view_channel', 'connect'):
        universal = getattr(default, bit) and not any(
            getattr(overwrite, bit) is False for overwrite in voice.overwrites.values())
        if not universal and _signature(guild, voice, bit) != _signature(guild, destination, 'view_channel'):
            return False
    return True


async def authorize(bot, guild_id, voice_id, destination_id, requester_id):
    # fetch_guild includes fresh roles; fetched channels/members share that snapshot.
    # Cache is used only for live gateway presence, never for permission calculations.
    if not bot.is_ready():
        raise ShareDenied('Bot 連線正在恢復，請稍後再試；離線時間唔計入30秒。')
    guild = await bot.fetch_guild(guild_id)
    member = await guild.fetch_member(requester_id)
    me = await guild.fetch_member(bot.user.id)
    voice = await guild.fetch_channel(voice_id)
    destination = await guild.fetch_channel(destination_id)
    if not isinstance(voice, discord.VoiceChannel) or not isinstance(destination, discord.TextChannel):
        raise ShareDenied('房間或招募頻道不存在，請重新開啟房控。')
    from cogs.tempvc import user_can_admin_teardown, tempvc_storage
    if member.id != tempvc_storage.creator_id(voice_id) and not user_can_admin_teardown(member):
        raise ShareDenied('招人入隊只限開房者或管理員。')
    if not bot.is_ready():
        raise ShareDenied('Bot 連線正在恢復，請稍後再試。')
    current = bot.get_channel(voice_id)
    if current is None or requester_id not in {m.id for m in current.members if not m.bot}:
        raise ShareDenied('你已離開呢間小隊房，請喺目前房間重新開啟房控。')
    if voice.user_limit and len(current.members) >= voice.user_limit:
        raise ShareDenied('房間已滿；請先騰出位置或調整人數上限。')
    for actor in (member, me):
        vp, dp = voice.permissions_for(actor), destination.permissions_for(actor)
        if not all((vp.view_channel, vp.connect, vp.create_instant_invite,
                    dp.view_channel, dp.send_messages)):
            raise ShareDenied('你或 Bot 缺少語音查看、連接、建立邀請，或招募頻道查看／發送權限。')
    dp = destination.permissions_for(me)
    if not dp.embed_links or not dp.read_message_history:
        raise ShareDenied('Bot 需要招募頻道嵌入連結及讀取歷史權限。')
    if not compatible_audience(guild, voice, destination):
        raise ShareDenied('呢間私人房嘅權限未能確認適合該招募頻道；未發布邀請，亦冇更改權限。')
    return voice, destination


def url(session):
    invite = session.get('voice_invite', {})
    if invite.get('state') == 'active' and invite.get('expires', 0) > time.time() and session.get('ended') is None:
        return 'https://discord.gg/' + invite['code']
    return None


def content(original, session, *, ended=False):
    # The dedicated line is ours; preserve the original prompt/Plan content.
    lines = [line for line in (original or '').splitlines() if not line.startswith(PREFIX)]
    link = None if ended else url(session)
    if link:
        lines.append(PREFIX + link)
    return '\n'.join(lines) or None


async def prepare(cog, channel, session):
    invite = session.get('voice_invite')
    if not invite or invite['state'] not in {'requested', 'active'}:
        return
    if invite['state'] == 'active' and invite['expires'] <= time.time():
        invite['state'] = 'expired'
        cog.save()
        return
    try:
        voice, _ = await authorize(cog.bot, channel.guild.id, channel.id,
                                   session['destination'], invite['requester'])
    except (ShareDenied, discord.HTTPException, OSError, TimeoutError) as exc:
        invite['error'] = str(exc) if isinstance(exc, ShareDenied) else '暫時無法核實房間權限。'
        # Retain a known code for revocation, but never publish after access changes.
        invite['state'] = 'revoking' if invite.get('code') else 'denied'
        cog.save()
        return
    invite['check_at'] = time.time() + RETRY_SECONDS
    if invite['state'] == 'active':
        return
    invite.update(state='uncertain', expires=time.time() + MAX_AGE)
    cog.save()  # Fence cancellation, timeout and success followed by process death.
    try:
        created = await voice.create_invite(max_age=MAX_AGE, max_uses=0,
            temporary=False, unique=True, reason='Squad session ' + session['id'])
    except discord.HTTPException as exc:
        if 400 <= exc.status < 500 and exc.status != 408:
            invite.update(state='denied', error='Discord 拒絕建立邀請；請核對權限後重按。')
            cog.save()
        raise
    # Start our cleanup horizon after success, so request latency never makes us
    # assume server expiry early and skip revoking a still-live code.
    invite.update(state='active', code=created.code, creator=cog.bot.user.id,
                  expires=time.time() + MAX_AGE)
    cog.save()


async def revoke(cog, session):
    """Return False while a known-code cleanup needs a bounded retry."""
    invite = session.get('voice_invite')
    if not invite or not invite.get('code') or invite.get('state') in {'revoked', 'expired'}:
        return True
    if invite.get('expires', 0) <= time.time():
        invite['state'] = 'expired'
        cog.save()
        return True
    if invite.get('retry_at', 0) > time.time():
        return False
    invite['state'] = 'revoking'
    cog.save()
    try:
        found = await cog.bot.fetch_invite(invite['code'])
        if (getattr(getattr(found, 'inviter', None), 'id', None) != invite.get('creator')
                or invite.get('creator') != cog.bot.user.id
                or getattr(getattr(found, 'channel', None), 'id', None) != invite['voice']):
            raise ShareDenied('Invite identity mismatch; no unrelated invite was deleted')
        await found.delete(reason='Squad session ended or access changed: ' + session['id'])
    except discord.NotFound:
        pass
    except (discord.HTTPException, OSError, TimeoutError, ShareDenied):
        invite['retry_at'] = time.time() + RETRY_SECONDS
        cog.save()
        return False
    invite['state'] = 'revoked'
    cog.save()
    return True


def retire(cog, session):
    """Keep uncertain-create evidence after the room disappears; never replay it."""
    invite = session.get('voice_invite', {})
    if invite.get('state') == 'uncertain':
        history = cog.state.setdefault('voice_invite_uncertain', {})
        history[session['id']] = dict(invite)
        # A code we never received is bounded by MAX_AGE; retain one day of evidence.
        for key, item in list(history.items()):
            if item.get('expires', 0) + 86400 < time.time():
                del history[key]
