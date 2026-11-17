"""Opt-in, bounded voice invites; caller holds SquadCards.lock across each operation.

The session JSON is the write-ahead journal. An uncertain create is never replayed.
Only a known code returned by this session's unique bot create may be revoked.
"""
from __future__ import annotations

import time
import discord
from features import voice_invite_transport as transport, voice_invite_trial as trial

MAX_AGE = 3600
RETRY_SECONDS = 60
PREFIX = '📣 本局語音邀請：'


class ShareDenied(ValueError):
    pass


class PresenceChanged(ShareDenied):
    pass


def presence_token(cog, voice_id):
    return (getattr(cog, '_invite_connection_epoch', 0),
            getattr(cog, '_invite_voice_epochs', {}).get(voice_id, 0))


def observe_voice(cog, before, after):
    """Called before the listener's first await; cache may already show a rejoin.

    A human departure conservatively restarts an unpublished room's qualification,
    even if other people stayed. Never erase that event using the final cache roster.
    """
    epochs = cog.__dict__.setdefault('_invite_voice_epochs', {})
    starts = cog.__dict__.setdefault('_invite_presence_starts', {})
    departures = cog.__dict__.setdefault('_invite_departed', set())
    if before:
        epochs[before.id] = epochs.get(before.id, 0) + 1
        starts[before.id] = time.time()
        departures.add(before.id)
    if after:
        epochs[after.id] = epochs.get(after.id, 0) + 1
        if after.id in departures or after.id not in starts:
            starts[after.id] = time.time()
        departures.discard(after.id)


def observe_connection(cog, *, connected):
    cog._invite_connection_epoch = getattr(cog, '_invite_connection_epoch', 0) + 1
    cog._invite_connected_since = time.time() if connected else None


def sync_presence(cog, channel, session):
    if session.get('message') and not session.get('share_waiting'):
        return
    previous = session.get('qualified')
    if (not cog.bot.is_ready() or not any(not m.bot for m in channel.members)
            or (hasattr(cog, '_invite_connected_since') and cog._invite_connected_since is None)):
        session['qualified'] = None
    else:
        cutoff = max(getattr(cog, '_invite_presence_starts', {}).get(channel.id, 0),
                     getattr(cog, '_invite_connected_since', 0) or 0)
        if previous is None:
            session['qualified'] = max(session.get('started', 0), cutoff) if cutoff else time.time()
        elif cutoff > previous:
            session['qualified'] = cutoff
    if session.get('qualified') != previous:
        cog.save()


def checkpoint(cog, channel, session, token, *, qualified=False):
    if session is not None:
        sync_presence(cog, channel, session)
    if (presence_token(cog, channel.id) != token or not cog.bot.is_ready()
            or not any(not m.bot for m in channel.members)
            or (hasattr(cog, '_invite_connected_since') and cog._invite_connected_since is None)):
        raise PresenceChanged('在場或連線狀態已改變；已保留設定，請連續留滿30秒後再試。')
    if qualified and (session.get('qualified') is None or time.time() - session['qualified'] < 30):
        raise PresenceChanged('未連續留滿30秒；已保留設定，等候出卡。')


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
    # Discord masks connect when @everyone cannot view. Once view implication
    # is proven, raw everyone connect plus no deny is sufficient for viewers.
    raw_connect = guild.default_role.permissions.connect
    for target, overwrite in voice.overwrites.items():
        if target.id == guild.default_role.id and overwrite.connect is not None:
            raw_connect = overwrite.connect
    for bit in ('view_channel', 'connect'):
        universal = (raw_connect if bit == 'connect' else getattr(default, bit)) and not any(
            getattr(overwrite, bit) is False for overwrite in voice.overwrites.values())
        if not universal and _signature(guild, voice, bit) != _signature(guild, destination, 'view_channel'):
            return False
    return True


async def authorize(bot, guild_id, voice_id, destination_id, requester_id, *, check=lambda: None, trial_cog=None, trial_revision=None):
    # fetch_guild includes fresh roles; fetched channels/members share that snapshot.
    # Cache is used only for live gateway presence, never for permission calculations.
    trial.require(trial_cog, bot.get_channel(voice_id), bot.get_channel(destination_id), requester_id, guild_id=guild_id)
    if not bot.is_ready():
        raise ShareDenied('Bot 連線正在恢復，請稍後再試；離線時間唔計入30秒。')
    guild = await bot.fetch_guild(guild_id)
    check()
    member = await guild.fetch_member(requester_id)
    check()
    me = await guild.fetch_member(bot.user.id)
    check()
    voice = await guild.fetch_channel(voice_id)
    check()
    destination = await guild.fetch_channel(destination_id)
    check()
    if not isinstance(voice, discord.VoiceChannel) or not isinstance(destination, discord.TextChannel):
        raise ShareDenied('房間或招募頻道不存在，請重新開啟房控。')
    trial.require(trial_cog, voice, destination, requester_id, guild_id=guild_id, revision=trial_revision)
    from cogs.tempvc import tempvc_storage
    from core.permissions import is_server_admin
    if member.id != tempvc_storage.creator_id(voice_id) and not is_server_admin(member):
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
    if not invite.get('scope_stopped') and invite.get('state') == 'active' and invite.get('expires', 0) > time.time() and session.get('ended') is None:
        return 'https://discord.gg/' + invite['code']
    return None


def content(original, session, *, ended=False):
    # The dedicated line is ours; preserve the original prompt/Plan content.
    lines = [line for line in (original or '').splitlines() if not line.startswith(PREFIX)]
    link = None if ended else url(session)
    if link:
        lines.append(PREFIX + link)
    return '\n'.join(lines) or None


async def prepare(cog, channel, session, *, check=lambda: None):
    invite = session.get('voice_invite')
    if invite:
        await trial.enforce(cog, channel, session)
    if not invite or invite.get('scope_stopped') or invite['state'] not in {'requested', 'active'}:
        return
    if invite['state'] == 'active' and invite['expires'] <= time.time():
        invite['state'] = 'expired'
        cog.save()
        return
    try:
        voice, destination = await authorize(cog.bot, channel.guild.id, channel.id,
                                   session['destination'], invite['requester'], check=check,
                                   trial_cog=cog, trial_revision=invite.get('trial_revision'))
        check()
    except PresenceChanged:
        raise
    except trial.TrialDenied as exc:
        trial.stop(cog, session, str(exc))
        await trial.withdraw(cog, session)
        return
    except (ShareDenied, discord.HTTPException, OSError, TimeoutError) as exc:
        invite['error'] = str(exc) if isinstance(exc, ShareDenied) else '暫時無法核實房間權限。'
        # Retain a known code for revocation, but never publish after access changes.
        invite['state'] = 'revoking' if invite.get('code') else 'denied'
        cog.save()
        return
    invite['check_at'] = time.time() + RETRY_SECONDS
    if invite['state'] == 'active':
        return
    def before_send():
        check()
        trial.require(cog, cog.bot.get_channel(channel.id), cog.bot.get_channel(session['destination']),
                      invite['requester'], revision=invite.get('trial_revision'))
        trial.require(cog, voice, destination, invite['requester'], revision=invite.get('trial_revision'))
        # Gates may wait arbitrarily long. Journal immediately before the only POST.
        # Unknown result's horizon is deliberately conservative, not server expiry.
        invite.update(state='uncertain', expires=time.time() + MAX_AGE + transport.REQUEST_TIMEOUT)
        cog.save()
    try:
        created = await transport.create_once(voice, max_age=MAX_AGE,
            reason='Squad session ' + session['id'], before_send=before_send)
    except trial.TrialDenied as exc:
        trial.stop(cog, session, str(exc))
        await trial.withdraw(cog, session)
        return
    except transport.TransportUnavailable:
        if invite['state'] != 'uncertain':
            invite.update(state='denied', error='邀請傳送介面需要維護核對；未發送建立邀請請求。')
            cog.save()
        raise
    except transport.InviteRateLimited as exc:
        invite.update(state='rate_limited', retry_at=exc.retry_at,
                      error='Discord 暫時限制建立邀請；請等候後再按，未自動重送。')
        cog.save()
        return
    except discord.HTTPException as exc:
        if 400 <= exc.status < 500 and exc.status not in {408, 429}:
            invite.update(state='denied', error='Discord 拒絕建立邀請；請核對權限後重按。')
            cog.save()
        raise
    # Save a known result before any presence fence can abort publication.
    invite.update(state='active', code=created['code'], creator=cog.bot.user.id,
                  expires=time.time() + MAX_AGE)
    cog.save()
    try:
        trial.require(cog, cog.bot.get_channel(channel.id), cog.bot.get_channel(session['destination']),
                      invite['requester'], revision=invite.get('trial_revision'))
    except trial.TrialDenied as exc:
        trial.stop(cog, session, str(exc))
        await trial.withdraw(cog, session)
        return
    check()


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
    cleanup = session.get('voice_cleanup', {})
    if cleanup.get('state') == 'deferred':
        evidence = {key: session.get(key) for key in ('id', 'destination', 'message', 'ended', 'footprint')}
        evidence['cleanup'] = dict(cleanup)
        cog.state.setdefault('voice_invite_cleanup_pending', {})[session['id']] = evidence
    if invite.get('state') == 'uncertain':
        history = cog.state.setdefault('voice_invite_uncertain', {})
        history[session['id']] = dict(invite)
        # A code we never received is bounded by MAX_AGE; retain one day of evidence.
        for key, item in list(history.items()):
            if item.get('expires', 0) + 86400 < time.time():
                del history[key]


async def close_session(cog, channel, session):
    """Revocation is independent of inaccessible public-message finalization.

    Only message cleanup has a five-minute deadline. Known invite revocation keeps
    its existing bounded backoff until success/expiry. After both gates settle the
    live session can retire; unresolved message evidence stays private in JSON.
    """
    revoked = await revoke(cog, session)
    cleanup = session.setdefault('voice_cleanup', dict(state='pending', attempts=0,
        retry_at=0, deadline=session['ended'] + 300))
    if cleanup['state'] in {'done', 'deferred'}:
        return revoked
    now = time.time()
    if now >= cleanup['deadline']:
        cleanup['state'] = 'deferred'
        cog.save()
        return revoked
    if cleanup['retry_at'] > now:
        return False
    cleanup['attempts'] += 1
    # Persist the next window before awaiting; even cancellation/restart backs off.
    cleanup['retry_at'] = now + RETRY_SECONDS
    cog.save()
    try:
        if session.get('message'):
            await cog.render(channel, session, ended=True)
    except Exception as exc:
        cleanup['error'] = type(exc).__name__
        cleanup['status'] = getattr(exc, 'status', None)
        if isinstance(exc, discord.Forbidden):
            cleanup['state'] = 'deferred'  # Known lost access: retain evidence, no hot loop.
        cog.save()
        return revoked and cleanup['state'] == 'deferred'
    cleanup['state'] = 'done'
    cog.save()
    return revoked
