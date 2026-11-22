"""Deliver and maintain a scheduled plan's collection point in its source channel."""
from __future__ import annotations

import asyncio
import copy
import hashlib
from itertools import chain, islice
from types import SimpleNamespace

import discord

import config
from features.plan_assembly_state import room_available, unopened
from features.plan_delivery import card_url
from features.plan_services import AccessError
from features.squad_plans import confirmed, deadline

FIVE_MINUTES = 300
RETRY_READ = 60
CLOSED_TEXT = '這則集合提醒已結束。'
NONE = discord.AllowedMentions.none()
NETWORK_ERRORS = (discord.HTTPException, discord.RateLimited, OSError, asyncio.TimeoutError)


def _mode(p, now):
    if p.get('instant') or not p['start'] <= now <= deadline(p):
        return 'closed'
    if room_available(p):
        return 'voice'
    return 'waiting' if unopened(p) else 'closed'


def _text(p, mode):
    path = f"原約局：<{card_url(p)}>"
    if mode == 'voice':
        return f'約定時間到了，語音房已開放。請按「加入語音」。\n{path}'
    count = len(p['assembly']['waiting'])
    return f'約定時間到了。正在等候開房：{count} 人。\n{path}'


def _view(cog, p):
    from cogs.squad_plans import AssemblyView
    return AssemblyView(cog, p)


def _with_mentions(text, users):
    # Both API limits apply even when a plan has unlimited capacity.
    ids = []
    for uid in users:
        addition = f' <@{uid}>'
        if len(ids) == 100 or len(text) + len(addition) > 2000:
            break
        text += addition
        ids.append(discord.Object(id=uid))
    return text, discord.AllowedMentions(users=ids, roles=False, everyone=False, replied_user=False)


def _nonce(p, kind):
    identity = f"assembly/{p['id']}/{p['assembly']['generation']}/{kind}"
    return hashlib.blake2b(identity.encode(), digest_size=12).hexdigest()


class AssemblyDelivery:
    """The cog serializes tick and refresh with its plan lock."""

    def __init__(self, cog):
        self.cog = cog
        self.book = cog.book
        self.checked = {}  # message ID -> (rendered state, next source ACL check)
        self.retry_at = {}  # (plan, generation, kind) -> next preflight
        self.retire_retry = {}

    def _cas(self, p, kind, expected, new, **fields):
        return self.book.assembly_receipt(p['id'], p['assembly']['generation'], kind,
                                          expected, new, **fields)

    def _guild(self, p):
        guild = self.cog.bot.get_guild(p['guild'])
        if p['guild'] != config.GUILD_ID or (guild is not None and guild.id != p['guild']):
            raise AccessError('wrong_guild')
        if guild is None or guild.unavailable:
            raise AccessError('guild_unavailable')
        return guild

    async def _channel(self, p, *, sending=False):
        guild = self._guild(p)
        channel = copy.copy(await guild.fetch_channel(p['channel']))
        if (not isinstance(channel, discord.TextChannel) or channel.id != p['channel']
                or channel.guild.id != guild.id):
            raise AccessError('source_mismatch')
        # Discord computes member permissions from the guild role cache and channel overwrites.
        snapshot = copy.copy(guild)
        snapshot._roles = {r.id: r for r in await guild.fetch_roles()}
        channel.guild = snapshot
        bot_id = self.cog.bot.user.id
        bot = copy.copy(await guild.fetch_member(bot_id))
        if bot.id != bot_id or bot.guild.id != guild.id:
            raise AccessError('source_mismatch')
        bot.guild = snapshot
        perms = channel.permissions_for(bot)
        if not (perms.view_channel and perms.read_message_history) or (sending and not perms.send_messages):
            raise AccessError('denied')
        return channel

    def _owned(self, p, message, expected):
        return (type(expected) is int and expected > 0 and message.id == expected
                and message.guild is not None and message.guild.id == p['guild'] == config.GUILD_ID
                and message.channel.id == p['channel'] and message.author.id == self.cog.bot.user.id)

    async def _source_card(self, p, channel):
        if not p.get('message'):
            raise AccessError('card_missing')
        msg = await channel.fetch_message(p['message'])
        if not self._owned(p, msg, p['message']):
            raise AccessError('source_mismatch')

    async def _members(self, p, ids, channel, kind):
        guild = self._guild(p)

        async def get(uid):
            try:
                member = await guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden):
                return None
            if member.id == uid and member.guild.id == guild.id and not member.bot:
                return copy.copy(member)
            return None

        members = []
        size = len(_text(p, _mode(p, self.book.clock())))
        for offset in range(0, len(ids), 5):
            if kind == 'due' and self.book.clock() > p['start'] + FIVE_MINUTES:
                break
            batch = await asyncio.gather(*(get(uid) for uid in ids[offset:offset + 5]))
            for member in filter(None, batch):
                if not self._eligible(channel, [member]):
                    continue
                size += len(f' <@{member.id}>')
                if size > 2000:
                    return members
                members.append(member)
        return members

    @staticmethod
    def _eligible(channel, members):
        from cogs.squad_plans import allowed, can_read
        ids = []
        for member in members:
            member.guild = channel.guild
            actor = SimpleNamespace(guild_id=channel.guild.id, channel=channel, user=member)
            if allowed(actor) and can_read(actor):
                ids.append(member.id)
        return ids

    def _render_key(self, p, now):
        a = p['assembly']
        return (a['generation'], p.get('revision', 0), _mode(p, now), p.get('voice'),
                len(a['waiting']), a['host'], a['nudge'].get('state'),
                now >= p['start'] + FIVE_MINUTES, p.get('availability'))

    def _request_valid(self, p, now):
        a = p['assembly']
        n = a['nudge']
        return (_mode(p, now) == 'waiting' and a['host']
                and n.get('actor') in confirmed(p) and n['actor'] != p['owner']
                and p['start'] + FIVE_MINUTES <= now <= n.get('requested_at', p['start']) + FIVE_MINUTES)

    async def _dispatch(self, p, kind):
        a = p['assembly']
        expected = 'requested' if kind == 'nudge' else None
        if a[kind].get('state') != expected:
            return
        now = self.book.clock()
        mode = _mode(p, now)
        if kind == 'nudge' and not self._request_valid(p, now):
            self._cas(p, kind, expected, 'skipped')
            return
        if mode == 'closed':
            return
        attempt = (p['id'], a['generation'], kind)
        if now < self.retry_at.get(attempt, 0):
            return
        self.retry_at.pop(attempt, None)
        consent = set(a['members'])
        if kind == 'nudge':
            candidates = [p['owner'], a['nudge']['actor']]
        elif now <= p['start'] + FIVE_MINUTES:
            eligible = chain([p['owner']] if a['host'] else [], (u for u in confirmed(p) if u in consent))
            candidates = list(islice(eligible, 100))
        else:
            candidates = []
        try:
            channel = await self._channel(p, sending=True)
            await self._source_card(p, channel)
            members = []
            if candidates:
                members = await self._members(p, candidates, channel, kind)
                channel = await self._channel(p, sending=True)
                await self._source_card(p, channel)  # Re-authorize the source after the member scan.
            ids = self._eligible(channel, members)
        except AccessError as exc:
            if exc.reason == 'guild_unavailable':
                self.retry_at[attempt] = self.book.clock() + RETRY_READ
            else:
                self._cas(p, kind, expected, 'skipped')
            return
        except (discord.NotFound, discord.Forbidden):
            self._cas(p, kind, expected, 'skipped')
            return
        except NETWORK_ERRORS:
            self.retry_at[attempt] = self.book.clock() + RETRY_READ
            return
        now = self.book.clock()
        if self.book.get(p['id']) != p or _mode(p, now) != mode:
            return
        if kind == 'nudge':
            if not self._request_valid(p, now) or set(ids) != set(candidates):
                self._cas(p, kind, expected, 'skipped')
                return
            content = f'有隊友提醒發起人開啟約局語音。\n原約局：<{card_url(p)}>'
            content, mentions = _with_mentions(content, [p['owner']])
            view = None
        else:
            content, mentions = _with_mentions(_text(p, mode), ids if now <= p['start'] + FIVE_MINUTES else [])
            view = _view(self.cog, p)
        if not self._cas(p, kind, expected, 'sending'):
            return
        # In the pinned SDK an explicit nonce sets enforce_nonce=true even on internal HTTP retries.
        try:
            msg = await channel.send(content, allowed_mentions=mentions, view=view, nonce=_nonce(p, kind))
        except NETWORK_ERRORS as exc:
            definite = isinstance(exc, discord.HTTPException) and 400 <= exc.status < 500
            self._cas(p, kind, 'sending', 'failed' if definite else 'unknown')
            return
        if not self._owned(p, msg, msg.id) or msg.id == p['message']:
            self._cas(p, kind, 'sending', 'unknown')
            return
        if self._cas(p, kind, 'sending', 'sent', **({'message': msg.id} if kind == 'due' else {})):
            if kind == 'due':
                self.checked[msg.id] = (self._render_key(p, now), now + FIVE_MINUTES)
        elif kind == 'due':
            # An occurrence changed while Discord was acknowledging the POST.
            try:
                await msg.edit(content=CLOSED_TEXT, view=None, allowed_mentions=NONE)
            except NETWORK_ERRORS:
                pass

    async def _retire(self, p, mid):
        if self.book.clock() < self.retire_retry.get(mid, 0):
            return
        try:
            channel = await self._channel(p)
            msg = await channel.fetch_message(mid)
            latest = self.book.get(p['id'])
            if not latest or mid not in latest['assembly']['retired']:
                return
            if self._owned(p, msg, mid) and mid != p['message']:
                await msg.edit(content=CLOSED_TEXT, view=None, allowed_mentions=NONE)
        except discord.NotFound:
            pass  # Channel or message is gone.
        except (AccessError, *NETWORK_ERRORS):
            self.retire_retry[mid] = self.book.clock() + FIVE_MINUTES
            return
        self.book.assembly_retire_done(p['id'], mid)
        self.checked.pop(mid, None)
        self.retire_retry.pop(mid, None)

    async def refresh(self, p):
        if not p or not p.get('assembly'):
            return
        for mid in p['assembly']['retired']:
            await self._retire(p, mid)
        p = self.book.get(p['id'])
        due = p['assembly']['due']
        mid = due.get('message')
        now = self.book.clock()
        if due.get('state') != 'sent' or not mid or mid == p['message']:
            return
        if p['assembly'].get('closed') or now > deadline(p):
            self.checked.pop(mid, None)
            return  # Terminal due messages go through the durable retirement queue.
        signature = self._render_key(p, now)
        cached, next_check = self.checked.get(mid, (None, 0))
        if cached == signature and now < next_check:
            return
        try:
            channel = await self._channel(p)
            msg = await channel.fetch_message(mid)
            if not self._owned(p, msg, mid):
                raise AccessError('source_mismatch')
            mode = _mode(p, now)
            try:
                await self._source_card(p, channel)
            except (discord.NotFound, discord.Forbidden, AccessError):
                mode = 'closed'
            if self.book.get(p['id']) != p or self._render_key(p, self.book.clock()) != signature:
                return
            content = CLOSED_TEXT if mode == 'closed' else _text(p, mode)
            view = None if mode == 'closed' else _view(self.cog, p)
            components = view.to_components() if view else []
            if msg.content != content or [c.to_dict() for c in msg.components] != components:
                await msg.edit(content=content, view=view, allowed_mentions=NONE)
        except (AccessError, *NETWORK_ERRORS):
            self.checked[mid] = (signature, now + RETRY_READ)
            return
        self.checked[mid] = (signature, now + FIVE_MINUTES)

    async def tick(self, p):
        if not p or not p.get('assembly'):
            return
        for kind in ('due', 'nudge'):
            if p['assembly'][kind].get('state') == 'sending':
                # The previous process could have reached Discord before losing its reply.
                self._cas(p, kind, 'sending', 'unknown')
            else:
                await self._dispatch(p, kind)
            p = self.book.get(p['id'])
        await self.refresh(p)
