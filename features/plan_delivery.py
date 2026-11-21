"""Plan Event and host-notice delivery. Durable intent, no unknown-result replay."""
from __future__ import annotations

import asyncio
import copy
import uuid
import math
from datetime import datetime, timezone

import discord

from features.squad_plans import confirmed

_DEFAULT_MINIMUM = object()


def options(party, capacity, *, instant=False, minimum=_DEFAULT_MINIMUM, auto=None, notices=True):
    # Only a new draft's omitted threshold inherits capacity. A cleared threshold stays empty.
    if minimum is _DEFAULT_MINIMUM:
        minimum = capacity
    if minimum is not None and (type(minimum) is not int or not 1 <= minimum <= 198
            or capacity is not None and minimum > capacity):
        raise ValueError('成局人數須為 1 至 198，並且不超過最高人數。')
    enabled = minimum is not None and not instant if auto is None else auto
    if type(enabled) is not bool or type(notices) is not bool:
        raise ValueError('設定無效，請重新開啟。')
    if enabled and (instant or minimum is None):
        raise ValueError('自動活動需要未來時間及成局人數。')
    return dict(minimum=minimum, auto_event=enabled, host_notices=notices)


def new_delivery(settings):
    return dict(settings=copy.deepcopy(settings), event={}, notices=[], seen=[])


def validate_delivery(p):
    """Reject corrupt new fields without rewriting the original plan book."""
    d = p['delivery']
    try:
        s = d['settings']
        options(p['party'], p['capacity'], instant=p.get('instant', False),
                minimum=s['minimum'], auto=s['auto_event'], notices=s['host_notices'])
        if not isinstance(d['event'], dict) or not isinstance(d['seen'], list) or not isinstance(d['notices'], list):
            raise ValueError('Invalid delivery shape')
        if any(type(u) is not int or u <= 0 for u in d['seen']):
            raise ValueError('Invalid delivery users')
        for n in d['notices']:
            if (not isinstance(n['id'], str) or not isinstance(n['boot'], str)
                    or n['state'] not in {'queued','sending','sent','unknown','failed','skipped',
                        'skipped_disabled','skipped_restart','skipped_access'}
                    or not isinstance(n['users'], list) or any(type(u) is not int or u <= 0 for u in n['users'])
                    or type(n['due']) not in (float, int) or not math.isfinite(n['due'])):
                raise ValueError('Invalid delivery receipt')
        e = d['event']
        if e and e.get('state') not in {'creating','unknown','linked','syncing','unknown_sync',
                'blocked','failed','conflict','deleted','cancelled','completed'}:
            raise ValueError('Invalid Event receipt')
        if e.get('id') is not None and (type(e['id']) is not int or e['id'] <= 0):
            raise ValueError('Invalid Event ID')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError('Invalid plan delivery state; original file preserved') from exc


def record_join(plan, user, *, new, clock, boot):
    """Called inside PlanBook's RSVP write. Existing plans stay opt-out."""
    d = plan.get('delivery')
    if not d or not new or user in d['seen']:
        return
    d['seen'].append(user)  # Returning and reconfirming never produce a second ping.
    if not d['settings']['host_notices']:
        return
    pending = next((n for n in d['notices'] if n['state'] == 'queued' and n['boot'] == boot), None)
    if pending is None:
        pending = dict(id=uuid.uuid4().hex, state='queued', boot=boot,
                       due=clock + 30, users=[], created=clock)
        d['notices'].append(pending)
    pending['users'].append(user)


def card_url(p):
    return f"https://discord.com/channels/{p['guild']}/{p['channel']}/{p['message']}"


def event_url(p):
    e = p.get('delivery', {}).get('event', {})
    if e.get('id') and e.get('state') in {'linked', 'syncing', 'unknown_sync'}:
        return f"https://discord.com/events/{p['guild']}/{e['id']}"
    return None


def view_acl(channel):
    """Compare the actual REST overwrite bits, including unresolved targets."""
    bit = discord.Permissions.view_channel.flag
    return sorted((o.id, o.type, o.allow & bit, o.deny & bit)
                  for o in channel._overwrites if (o.allow | o.deny) & bit)


def same_audience(source, voice):
    return (isinstance(source, discord.TextChannel) and isinstance(voice, discord.VoiceChannel)
            and source.guild.id == voice.guild.id and source.category_id == voice.category_id
            and view_acl(source) == view_acl(voice))


def fingerprint(event):
    return dict(name=event.name, description=event.description,
                start=int(event.start_time.timestamp()), channel=event.channel_id,
                entity=int(event.entity_type.value))


class PlanDelivery:
    def __init__(self, cog):
        self.cog, self.book = cog, cog.book
        self.boot = self.book.delivery_boot

    def unchanged(self, p):
        latest = self.book.get(p['id'])
        return latest is not None and latest.get('revision', 0) == p.get('revision', 0)

    def update(self, key, change):
        with self.book.lock:
            state = copy.deepcopy(self.book.state)
            p = state['plans'][key]
            change(p['delivery'])
            p['dirty'] = True
            self.book._write(state)
            return copy.deepcopy(p)

    def event_state(self, key, state, **values):
        return self.update(key, lambda d: d['event'].update(state=state, **values))

    def recover(self):
        # Reads can reconcile Events; old enrollment notices are never replayed.
        for p in self.book.all():
            if not p.get('delivery'):
                continue
            d = p['delivery']
            if (d['event'].get('state') not in {'creating', 'syncing'} and not any(
                    n['state'] == 'sending' or n['state'] == 'queued' and n['boot'] != self.boot
                    for n in d['notices'])):
                continue
            def recover_one(d):
                for n in d['notices']:
                    if n['state'] == 'queued' and n['boot'] != self.boot:
                        n['state'] = 'skipped_restart'
                    elif n['state'] == 'sending':
                        n['state'] = 'unknown'
                if d['event'].get('state') == 'creating':
                    d['event']['state'] = 'unknown'
                elif d['event'].get('state') == 'syncing':
                    d['event']['state'] = 'unknown_sync'
            self.update(p['id'], recover_one)

    async def access(self, p):
        from features.plan_services import source, AccessError
        from cogs.squad_plans import allowed
        from types import SimpleNamespace
        guild = self.cog.bot.get_guild(p['guild'])
        if guild is None:
            raise AccessError('guild_unavailable')
        member, channel = await source(self.cog, guild, p['owner'], p)
        if not allowed(SimpleNamespace(guild_id=guild.id, user=member, channel=channel)):
            raise AccessError('denied')
        bot_member = copy.copy(await guild.fetch_member(self.cog.bot.user.id))
        bot_member.guild = channel.guild
        perms = channel.permissions_for(bot_member)
        if not (perms.view_channel and perms.send_messages and perms.read_message_history):
            raise AccessError('bot_denied')
        return guild, channel, bot_member

    async def destination(self, guild, source, bot_member, p):
        from features.tempvc_settings import get_hub_channel_name
        channels = await guild.fetch_channels()
        if p.get('voice') and p['status'] == 'live':
            candidates = [c for c in channels if c.id == p['voice']]
        else:
            candidates = [c for c in channels if isinstance(c, discord.VoiceChannel)
                          and c.category_id == source.category_id and c.name.strip() == get_hub_channel_name()]
        for voice in candidates:
            voice.guild = source.guild
        candidates = [c for c in candidates if same_audience(source, c)]
        if len(candidates) != 1:
            return None
        voice = candidates[0]
        perms = voice.permissions_for(bot_member)
        if not (perms.view_channel and perms.connect and (perms.create_events or perms.manage_events)):
            return None
        return voice

    async def valid_members(self, guild, channel, p):
        from features.plan_services import AccessError
        from cogs.squad_plans import allowed
        from types import SimpleNamespace
        semaphore = asyncio.Semaphore(5)
        async def one(uid):
            async with semaphore:
                try:
                    member = copy.copy(await guild.fetch_member(uid))
                    member.guild = channel.guild  # Fresh source role/overwrite snapshot.
                    if not member.bot and allowed(SimpleNamespace(guild_id=guild.id, user=member, channel=channel)):
                        return uid
                except (discord.NotFound, discord.Forbidden):
                    return None
                except (discord.HTTPException, OSError) as exc:
                    raise AccessError('temporary_failure') from exc
        return [uid for uid in await asyncio.gather(*(one(uid) for uid in confirmed(p))) if uid is not None]

    def payload(self, p, voice, count):
        safe = lambda s: discord.utils.escape_mentions(str(s)).replace('\n', ' ')
        return dict(name=f"{safe(p['game'])} · 約定開局"[:100],
                    description=(f"平台／模式：{safe(p['mode']) or '未填'}\n"
                        f"預計 {count} 人（申報隊友及確認報名，不代表到場）；稍後到 {len(set(confirmed(p)) & set(p.get('late', [])))} 人。\n"
                        "正式報名、退出及稍後到請用原卡；活動有興趣不算報名或 Bot 提醒。\n"
                        "活動語音先連到本區小隊入口；實際開局後才連接本局房間。\n"
                        f"原約局：{card_url(p)}\n[Con9sole plan:{p['id']}]")[:1000],
                    start_time=datetime.fromtimestamp(p['start'], timezone.utc), channel=voice)

    async def close_lost_source(self, p):
        """Only close our unchanged linked Event; never overwrite a manual edit."""
        e = p['delivery']['event']
        if not e.get('id') or e.get('state') not in {'linked', 'unknown_sync', 'syncing'}:
            return
        guild = self.cog.bot.get_guild(p['guild'])
        if guild is None:
            return
        try:
            event = await guild.fetch_scheduled_event(e['id'])
            if event.creator_id != self.cog.bot.user.id or fingerprint(event) != e.get('snapshot'):
                self.event_state(p['id'], 'conflict', reason='lost_source_manual_change'); return
            if event.status in {discord.EventStatus.completed, discord.EventStatus.cancelled}:
                self.event_state(p['id'], 'cancelled', reason='source_unavailable'); return
            self.update(p['id'], lambda d: d['settings'].update(auto_event=False))
            self.event_state(p['id'], 'syncing', operation='source_close', wanted=fingerprint(event))
            status = discord.EventStatus.completed if event.status == discord.EventStatus.active else discord.EventStatus.cancelled
            await event.edit(status=status, reason='Linked plan source no longer available')
            self.event_state(p['id'], 'cancelled', reason='source_unavailable')
        except discord.NotFound:
            self.event_state(p['id'], 'deleted')
        except (discord.HTTPException, OSError, asyncio.TimeoutError):
            self.event_state(p['id'], 'unknown_sync', operation='source_close')

    async def reconcile_event(self, p):
        """Caller holds cog.lock. Never send another create after an ambiguous attempt."""
        from features.plan_services import AccessError
        d = p.get('delivery')
        if not d:
            return
        settings, e, key = d['settings'], d['event'], p['id']
        if e.get('state') in {'failed', 'conflict', 'deleted', 'cancelled', 'completed'}:
            return
        if not e and (not settings['auto_event'] or p.get('instant') or p['start'] <= self.book.clock()
                or p['status'] not in {'open', 'gathering'}):
            return
        if not e and settings['minimum'] is not None and p['party'] + len(confirmed(p)) < settings['minimum']:
            return
        if not e.get('id') and e.get('state') == 'blocked' and not settings['auto_event']:
            return
        try:
            guild, channel, bot_member = await self.access(p)
            if e.get('state') in {'unknown', 'creating'}:
                matches = [v for v in await guild.fetch_scheduled_events()
                           if v.creator_id == self.cog.bot.user.id
                           and f"[Con9sole plan:{key}]" in (v.description or '')]
                if len(matches) != 1:
                    return  # No match is not evidence that create was never committed.
                event = matches[0]
                if fingerprint(event) != e.get('wanted'):
                    self.event_state(key, 'conflict', id=event.id, reason='recovered_event_changed')
                    return
                p = self.event_state(key, 'linked', id=event.id, snapshot=fingerprint(event))
                e = p['delivery']['event']
            if e.get('id'):
                try:
                    event = await guild.fetch_scheduled_event(e['id'])
                except discord.NotFound:
                    self.event_state(key, 'deleted'); return
                if event.creator_id != self.cog.bot.user.id or f"[Con9sole plan:{key}]" not in (event.description or ''):
                    self.event_state(key, 'conflict', reason='event_identity'); return
                current = fingerprint(event)
                if current != e.get('snapshot'):
                    if e.get('state') == 'unknown_sync' and current == e.get('wanted'):
                        p = self.event_state(key, 'linked', snapshot=current)
                        e = p['delivery']['event']
                    else:
                        self.event_state(key, 'conflict', reason='manual_change'); return
                if event.status in {discord.EventStatus.cancelled, discord.EventStatus.completed}:
                    self.event_state(key, 'cancelled' if event.status == discord.EventStatus.cancelled else 'completed'); return
                if event.status == discord.EventStatus.active and p['status'] not in {'live', 'ended', 'cancelled', 'expired'}:
                    self.event_state(key, 'conflict', reason='manual_start'); return
            else:
                event = None
            if event and (p['status'] in {'cancelled', 'expired', 'ended'} or not settings['auto_event']):
                if not self.unchanged(p):
                    return
                status = discord.EventStatus.completed if event.status == discord.EventStatus.active else discord.EventStatus.cancelled
                self.event_state(key, 'syncing', wanted=current, operation='close')
                try:
                    await event.edit(status=status, reason='Linked plan closed or Event disabled')
                except Exception as exc:
                    self.event_state(key, 'failed' if isinstance(exc, discord.Forbidden) else 'unknown_sync', operation='close')
                    return
                self.event_state(key, 'completed' if status == discord.EventStatus.completed else 'cancelled'); return
            if not event and not settings['auto_event']:
                return
            valid = await self.valid_members(guild, channel, p)
            count = p['party'] + len(valid)
            if not event and (settings['minimum'] is None or count < settings['minimum']):
                return
            voice = await self.destination(guild, channel, bot_member, p)
            if not self.unchanged(p):
                return
            if voice is None:
                # Do not fall back to guild-visible EXTERNAL events for a private source.
                self.event_state(key, 'blocked', reason='source_visibility_or_event_permission')
                self.update(key, lambda d: d['settings'].update(auto_event=False))
                if event:
                    status = discord.EventStatus.completed if event.status == discord.EventStatus.active else discord.EventStatus.cancelled
                    self.event_state(key, 'syncing', wanted=current, operation='privacy_close')
                    try:
                        await event.edit(status=status, reason='Linked source visibility no longer matches')
                    except (discord.HTTPException, OSError, asyncio.TimeoutError):
                        self.event_state(key, 'unknown_sync', operation='privacy_close'); return
                    self.event_state(key, 'cancelled', reason='source_visibility_or_event_permission')
                return
            payload = self.payload(p, voice, count)
            wanted = dict(name=payload['name'], description=payload['description'],
                          start=p['start'], channel=voice.id, entity=discord.EntityType.voice.value)
            if not event:
                if p['start'] <= self.book.clock() or p['status'] not in {'open', 'gathering'}:
                    return
                self.event_state(key, 'creating', attempt=self.book.clock(), wanted=wanted)
                try:
                    event = await guild.create_scheduled_event(**payload, entity_type=discord.EntityType.voice,
                        privacy_level=discord.PrivacyLevel.guild_only, reason='Confirmed plan threshold reached')
                except (discord.HTTPException, OSError, asyncio.TimeoutError) as exc:
                    definite = isinstance(exc, discord.HTTPException) and 400 <= exc.status < 500 and exc.status != 429
                    self.event_state(key, 'failed' if definite else 'unknown'); return
                self.event_state(key, 'linked', id=event.id, snapshot=fingerprint(event))
            else:
                status = discord.EventStatus.active if p['status'] == 'live' else event.status
                if current == wanted and event.status == status:
                    return
                # Discord rejects a past start_time; do not resubmit an unchanged one.
                if current['start'] == wanted['start']:
                    payload.pop('start_time')
                elif wanted['start'] <= self.book.clock():
                    self.event_state(key, 'conflict', reason='past_reschedule'); return
                self.event_state(key, 'syncing', wanted=wanted, operation='update')
                try:
                    event = await event.edit(**payload, status=status, reason='Sync linked plan')
                except (discord.HTTPException, OSError, asyncio.TimeoutError) as exc:
                    self.event_state(key, 'failed' if isinstance(exc, discord.Forbidden) else 'unknown_sync'); return
                self.event_state(key, 'linked', snapshot=fingerprint(event))
        except AccessError as exc:
            if exc.reason in {'denied', 'source_deleted', 'card_deleted', 'source_mismatch'}:
                await self.close_lost_source(p)
            return
        except (discord.HTTPException, OSError, asyncio.TimeoutError):
            # Source access failures are not a successful empty roster or permission change.
            return

    async def flush_notices(self, p):
        from features.plan_services import AccessError
        d = p.get('delivery')
        if not d:
            return
        for item in d['notices']:
            if item['state'] != 'queued' or item['boot'] != self.boot or item['due'] > self.book.clock():
                continue
            key, notice_id = p['id'], item['id']
            def set_state(state, **kw):
                self.update(key, lambda current: next(n for n in current['notices'] if n['id'] == notice_id).update(state=state, **kw))
            p = self.book.get(key)
            if not p['delivery']['settings']['host_notices'] or p['status'] not in {'open', 'due', 'gathering', 'live'}:
                set_state('skipped'); continue
            try:
                guild, channel, _ = await self.access(p)
                valid = set(await self.valid_members(guild, channel, p))
                users = sorted(valid & set(item['users']))
                if not users:
                    set_state('skipped'); continue
                _, channel, _ = await self.access(p)
                if not self.unchanged(p):
                    continue
                late = len(set(users) & set(p.get('late', [])))
                text = f"<@{p['owner']}> 新增 {len(users)} 人報名" + (f"（{late} 人稍後到）" if late else '')
                text += f"；預計 {p['party'] + len(valid)} 人。[查看約局]({card_url(p)})"
                url = event_url(p)
                if url:
                    text += f" · [活動已建立]({url})"
                set_state('sending', attempted=self.book.clock(), recipients=[p['owner']])
                try:
                    message = await channel.send(text, allowed_mentions=discord.AllowedMentions(
                        users=[discord.Object(id=p['owner'])], roles=False, everyone=False, replied_user=False),
                        suppress_embeds=True)
                except (discord.HTTPException, OSError, asyncio.TimeoutError) as exc:
                    definite = isinstance(exc, discord.HTTPException) and 400 <= exc.status < 500 and exc.status != 429
                    set_state('failed' if definite else 'unknown'); continue
                set_state('sent', message=message.id, delivered=self.book.clock())
            except (AccessError, discord.HTTPException, OSError, asyncio.TimeoutError):
                set_state('skipped_access')  # No delayed ping after loss of access.
