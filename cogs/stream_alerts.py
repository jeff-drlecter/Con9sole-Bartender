"""Twitch stream alerts, separate from the existing Twitch chat relay."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.permissions import is_server_admin
from core.storage_paths import DATA_DIR
from core.twitch_alerts import AlertStore, AUDIENCE_ROLE, default_state, normalize_login, transition
from core.ui import SafeView, SafeModal

log = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()


class TwitchAPI:
    def __init__(self, session, client_id, secret):
        self.session, self.client_id, self.secret = session, client_id, secret
        self.token, self.expires, self.validate_at, self.blocked_until = '', 0, 0, 0
        self.requests = 0

    async def request(self, method, url, **kwargs):
        if time.time() < self.blocked_until:
            raise RuntimeError('Twitch cooldown')
        self.requests += 1
        async with self.session.request(method, url, allow_redirects=False, **kwargs) as response:
            if response.status == 429:
                try:
                    reset = float(response.headers.get('Ratelimit-Reset', 0))
                    retry = float(response.headers.get('Retry-After', 60))
                except ValueError:
                    reset, retry = 0, 60
                self.blocked_until = max(time.time() + max(retry, 60), reset)
            if response.status != 200:
                # Do not include response bodies, headers, URLs or tokens in exceptions.
                raise RuntimeError(f'Twitch HTTP {response.status}')
            data = await response.json()
            if not isinstance(data, dict):
                raise RuntimeError('Invalid Twitch response')
            return data

    async def access_token(self):
        now = time.time()
        if self.token and now >= self.validate_at:
            try:
                validated = await self.request('GET', 'https://id.twitch.tv/oauth2/validate',
                                               headers={'Authorization': 'OAuth ' + self.token})
                if validated.get('client_id') != self.client_id:
                    raise RuntimeError('Unexpected Twitch client')
                self.validate_at = now + 3600
            except RuntimeError as exc:
                if str(exc) != 'Twitch HTTP 401':
                    raise
                self.token = ''
        if not self.token or now >= self.expires:
            data = await self.request('POST', 'https://id.twitch.tv/oauth2/token', data={
                'client_id': self.client_id, 'client_secret': self.secret,
                'grant_type': 'client_credentials'})
            if not data.get('access_token') or not isinstance(data.get('expires_in'), int) or data['expires_in'] <= 120:
                raise RuntimeError('Invalid Twitch token response')
            self.token = data['access_token']
            self.expires = now + max(0, data['expires_in'] - 120)
            self.validate_at = now  # Validate new tokens before first use.
            return await self.access_token()
        return self.token

    async def get(self, path, params):
        for attempt in range(2):
            token = await self.access_token()
            try:
                result = await self.request('GET', 'https://api.twitch.tv/helix/' + path,
                    params=params, headers={'Client-ID': self.client_id, 'Authorization': 'Bearer ' + token})
            except RuntimeError as exc:
                if str(exc) == 'Twitch HTTP 401' and attempt == 0:
                    self.token = ''
                    continue
                raise
            if not isinstance(result.get('data'), list):
                raise RuntimeError('Invalid Twitch data array')
            return result
        raise RuntimeError('Twitch authorization failed')

    async def streams(self, logins):
        # Explicit first=100 prevents a truncated first page being mistaken for offline.
        streams = {}
        cursor, seen = None, set()
        for _ in range(5):
            params = [('first', '100')] + [('user_login', x) for x in logins]
            if cursor:
                params.append(('after', cursor))
            result = await self.get('streams', params)
            for stream in result['data']:
                if not all(stream.get(key) for key in ('id', 'user_login', 'started_at')):
                    raise RuntimeError('Incomplete Twitch stream')
                name = stream['user_login'].lower()
                if name not in logins:
                    raise RuntimeError('Unexpected Twitch stream')
                datetime.fromisoformat(stream['started_at'].replace('Z', '+00:00'))
                streams[name] = stream  # Live rankings can repeat a stream between pages.
            cursor = result.get('pagination', {}).get('cursor')
            if not result['data'] or not cursor:
                return streams
            if cursor in seen:
                raise RuntimeError('Repeated Twitch pagination cursor')
            seen.add(cursor)
        raise RuntimeError('Twitch pagination safety limit exceeded')


async def authorized(inter):
    if inter.guild_id == config.GUILD_ID and is_server_admin(inter.user):
        return True
    if not inter.response.is_done():
        await inter.response.send_message('需要本伺服器管理權限。', ephemeral=True)
    else:
        await inter.followup.send('需要本伺服器管理權限。', ephemeral=True)
    return False


class AdminView(SafeView):
    async def interaction_check(self, inter):
        return await authorized(inter)


class StreamSelect(discord.ui.Select):
    def __init__(self, view):
        self.owner = view
        rows = list(view.cog.store.state['entries'].items())[view.page * 25:(view.page + 1) * 25]
        super().__init__(placeholder='選擇直播主', options=[discord.SelectOption(
            label=login, value=login, description=('成員' if e['group'] == 'member' else '友台') +
            (' · 啟用' if e['enabled'] else ' · 停用'), default=login == view.selected) for login, e in rows])

    async def callback(self, inter):
        await self.owner.cog.show(inter, self.values[0], self.owner.page)


class AddStream(SafeModal, title='新增 Twitch 直播主'):
    login = discord.ui.TextInput(label='Twitch 帳號或網址', max_length=80)
    group = discord.ui.TextInput(label='類別：成員／友台', default='友台', max_length=8)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, inter):
        if not await authorized(inter):
            return
        await inter.response.defer(ephemeral=True)
        try:
            login = normalize_login(str(self.login))
            group = {'成員': 'member', '友台': 'partner'}.get(str(self.group).strip())
            if not group:
                raise ValueError('類別請填 成員 或 友台。')
            if not self.cog.api:
                raise ValueError('Twitch 憑證未準備好。')
            async with self.cog.lock:
                result = await self.cog.api.get('users', [('login', login)])
                if not any(u.get('login', '').lower() == login for u in result['data']):
                    raise ValueError('Twitch 找不到這個帳號。')
                self.cog.store.add(login, group)
        except (ValueError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            text = str(exc) if isinstance(exc, ValueError) else '暫時無法核對 Twitch，未新增帳號。'
            await inter.followup.send(text, ephemeral=True, allowed_mentions=NONE)
            return
        await inter.followup.send(f'已新增 **{login}**；首次檢查只建立基準，不補發目前的直播。', ephemeral=True)
        await self.cog.show(inter, login)


class RemoveStream(AdminView):
    def __init__(self, cog, login):
        super().__init__(timeout=120)
        self.cog, self.login = cog, login

    @discord.ui.button(label='確認移除直播主', style=discord.ButtonStyle.danger)
    async def confirm(self, inter, button):
        await inter.response.defer()
        async with self.cog.lock:
            self.cog.store.state['entries'].pop(self.login, None)
            self.cog.store.save()
        await inter.edit_original_response(content=f'已移除 {self.login}；現有通知卡保留。', view=None)


class Cadence(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(placeholder='友台檢查頻率', options=[discord.SelectOption(label=f'友台每 {n} 分鐘',
            value=str(n), default=cog.store.state['partner_minutes'] == n) for n in (30, 60, 120)])

    async def callback(self, inter):
        await inter.response.defer()
        async with self.cog.lock:
            self.cog.store.state['partner_minutes'] = int(self.values[0])
            self.cog.store.save()
        await self.cog.show(inter)


class StreamAdmin(AdminView):
    def __init__(self, cog, selected=None, page=0):
        super().__init__(timeout=300)
        self.cog, self.selected = cog, selected
        self.page = min(max(0, page), max(0, (len(cog.store.state['entries']) - 1) // 25))
        if cog.store.state['entries']:
            self.add_item(StreamSelect(self))
        self.add_item(Cadence(cog))
        for child in self.children:
            if getattr(child, 'custom_id', '') in ('stream:toggle', 'stream:group', 'stream:remove'):
                child.disabled = selected not in cog.store.state['entries']

    @discord.ui.button(label='新增直播主', row=2)
    async def add(self, inter, button):
        await inter.response.send_modal(AddStream(self.cog))

    @discord.ui.button(label='啟用／停用帳號', custom_id='stream:toggle', row=2)
    async def toggle(self, inter, button):
        await inter.response.defer()
        async with self.cog.lock:
            e = self.cog.store.state['entries'].get(self.selected)
            if e:
                e['enabled'] = not e['enabled']
                e['initialized'], e['last_check'] = False, 0  # Resume silently, never backfill.
                e['pending'] = None
                self.cog.store.save()
        await self.cog.show(inter, self.selected, self.page)

    @discord.ui.button(label='轉換成員／友台', custom_id='stream:group', row=2)
    async def group(self, inter, button):
        await inter.response.defer()
        async with self.cog.lock:
            e = self.cog.store.state['entries'].get(self.selected)
            if e:
                e['group'] = 'partner' if e['group'] == 'member' else 'member'
                # Existing session card stays in its original channel until offline.
                self.cog.store.save()
        await self.cog.show(inter, self.selected, self.page)

    @discord.ui.button(label='移除帳號', style=discord.ButtonStyle.danger, custom_id='stream:remove', row=2)
    async def remove(self, inter, button):
        if self.selected not in self.cog.store.state['entries']:
            return await self.cog.show(inter)
        await inter.response.send_message(f'移除 **{self.selected}**？之後可重新新增。',
            view=RemoveStream(self.cog, self.selected), ephemeral=True)

    @discord.ui.button(label='暫停／恢復通知', row=3)
    async def delivery(self, inter, button):
        await inter.response.defer()
        async with self.cog.lock:
            s = self.cog.store.state
            if not s['enabled'] and not self.cog.api:
                await inter.followup.send('Twitch 憑證未準備好，未啟用。', ephemeral=True)
                return
            s['enabled'] = not s['enabled']
            for e in s['entries'].values():
                e['initialized'], e['last_check'], e['pending'] = False, 0, None
            self.cog.store.save()
        await self.cog.show(inter, self.selected, self.page)

    @discord.ui.button(label='成員直播提及：開／關', row=3)
    async def ping(self, inter, button):
        await inter.response.defer()
        async with self.cog.lock:
            s = self.cog.store.state
            s['member_ping'] = not s['member_ping']
            self.cog.store.save()
        await self.cog.show(inter, self.selected, self.page)

    @discord.ui.button(label='上一頁', row=4)
    async def previous(self, inter, button):
        await self.cog.show(inter, page=self.page - 1)

    @discord.ui.button(label='下一頁／重新整理', row=4)
    async def next_page(self, inter, button):
        count = len(self.cog.store.state['entries'])
        await self.cog.show(inter, page=(self.page + 1) if count > (self.page + 1) * 25 else 0)


class StreamPanel(AdminView):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label='管理直播名單', emoji='📺', custom_id='stream:admin:open')
    async def open(self, inter, button):
        await self.cog.menu_entry(inter)


class StreamAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot, self.lock = bot, asyncio.Lock()
        self.store, self.session, self.api = None, None, None
        self.last_error = ''
        self.last_success = 0

    async def cog_load(self):
        self.store = AlertStore(DATA_DIR / 'twitch_alerts.sqlite3', os.getenv('TWITCH_ALERT_BOOTSTRAP', ''))
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        client, secret = os.getenv('TWITCH_CLIENT_ID', ''), os.getenv('TWITCH_CLIENT_SECRET', '')
        if client and secret:
            self.api = TwitchAPI(self.session, client, secret)
        self.panel_view = StreamPanel(self)
        self.bot.add_view(self.panel_view)
        self.poll.start()

    async def cog_unload(self):
        self.bot.remove_view(self.panel_view)
        task = self.poll.get_task()
        self.poll.cancel()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        if self.session:
            await self.session.close()

    def channel(self, group):
        guild = self.bot.get_guild(config.GUILD_ID)
        channel = guild.get_channel(self.store.state[group + '_channel']) if guild else None
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError('Configured stream channel is unavailable')
        perms = channel.permissions_for(guild.me)
        if not all((perms.view_channel, perms.send_messages, perms.embed_links, perms.read_message_history)):
            raise RuntimeError('Stream channel permissions missing')
        return channel

    def card(self, login, stream, *, ended=False, vod=None):
        display = discord.utils.escape_markdown(stream.get('user_name', login))
        url = 'https://www.twitch.tv/' + login
        embed = discord.Embed(title=(f'{display} 直播已結束' if ended else (stream.get('title') or '直播中'))[:256],
            url=url, color=0x95a5a6 if ended else 0x9146ff,
            description=(f'📺 [重溫 VOD]({vod})' if vod else '直播已結束；VOD 暫未提供。') if ended else
                        f'**{display} 開始直播了！**\n🎥 [觀看直播]({url})', timestamp=datetime.now(timezone.utc))
        started = int(datetime.fromisoformat(stream['started_at'].replace('Z', '+00:00')).timestamp())
        embed.add_field(name='遊戲', value=(stream.get('game_name') or '未知')[:1024], inline=True)
        embed.add_field(name='開始時間', value=f'<t:{started}:f>', inline=True)
        if ended:
            embed.add_field(name='結束狀態', value='在本次檢查確認直播結束；非精確結束時間。', inline=False)
        else:
            embed.set_image(url=f'https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-640x360.jpg')
        embed.set_footer(text=f"Twitch • {login} • stream:{stream['id']}")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label='重溫 VOD' if ended and vod else '前往頻道' if ended else '觀看直播',
                                        url=vod if ended and vod else url))
        return embed, view

    async def recover_pending(self, channel, login, pending):
        marker = f"Twitch • {login} • stream:{pending['stream']['id']}"
        after = datetime.fromtimestamp(pending['reserved_at'], timezone.utc) - timedelta(seconds=10)
        scanned = 0
        async for message in channel.history(limit=100, after=after, oldest_first=True):
            scanned += 1
            if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                return message
        if scanned >= 100:
            raise RuntimeError('Pending stream recovery history limit reached')
        return None

    async def send_live(self, login, e, stream):
        pending = e.get('pending')
        if pending:
            channel = self.bot.get_channel(pending['channel'])
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != config.GUILD_ID:
                raise RuntimeError('Pending stream channel unavailable')
            message = await self.recover_pending(channel, login, pending)
            if message is None and (not stream or stream['id'] != pending['stream']['id']):
                # A failed/ambiguous old send must never backfill a session that's already over.
                e['pending'] = None
                self.store.save()
                return
            stream = pending['stream']
        else:
            channel = self.channel(e['group'])
            pending = {'stream': stream, 'channel': channel.id, 'reserved_at': time.time()}
            e['pending'] = pending
            self.store.save()  # Reserve before external side effects; recovery checks history after restart.
            message = None
        if message is None:
            embed, view = self.card(login, stream)
            role = channel.guild.get_role(AUDIENCE_ROLE)
            ping = e['group'] == 'member' and self.store.state['member_ping'] and role is not None
            message = await channel.send(content=role.mention if ping else '', embed=embed, view=view,
                allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False, replied_user=False) if ping else NONE,
                silent=not ping)
        e.update(stream_id=stream['id'], started_at=stream['started_at'], stream=stream,
                 message_id=message.id, message_channel=channel.id, pending=None)
        self.store.save()

    async def end_card(self, login, e):
        if e.get('message_id'):
            channel = self.bot.get_channel(e['message_channel'])
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != config.GUILD_ID:
                raise RuntimeError('Existing stream channel unavailable')
            vod = None
            try:
                data = await self.api.get('videos', [('user_id', e['stream']['user_id']), ('type', 'archive'), ('first', '1')])
                video = next(iter(data['data']), None)
                if video:
                    created = datetime.fromisoformat(video['created_at'].replace('Z', '+00:00'))
                    started = datetime.fromisoformat(e['started_at'].replace('Z', '+00:00'))
                    if abs((created - started).total_seconds()) <= 1800 and video['url'].startswith('https://www.twitch.tv/videos/'):
                        vod = video['url']
            except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                pass  # Optional VOD must not prevent closing the card.
            embed, view = self.card(login, e['stream'], ended=True, vod=vod)
            try:
                message = await channel.fetch_message(e['message_id'])
                await message.edit(content='', embed=embed, view=view, allowed_mentions=NONE)
            except discord.NotFound:
                pass  # Deleted cards are never reposted.
        e.update(stream_id=None, started_at=None, message_id=None, message_channel=None, pending=None)
        self.store.save()

    @tasks.loop(seconds=30)
    async def poll(self):
        try:
            async with self.lock:
                if not self.store.state['enabled'] or not self.api:
                    return
                now = time.time()
                due = self.store.due(now)
                if not due:
                    return
                self.channel('member')
                self.channel('partner')
                streams = await self.api.streams(due)
                for login in due:
                    e, stream = self.store.state['entries'][login], streams.get(login)
                    action = transition(e, stream)
                    try:
                        if action == 'baseline':
                            # Migration/new/resumed entries do not backfill already-live sessions.
                            if e.get('message_id') and (not stream or stream['id'] != e.get('stream_id')):
                                await self.end_card(login, e)
                            e.update(initialized=True, stream_id=stream['id'] if stream else None,
                                     started_at=stream['started_at'] if stream else None)
                            if stream:
                                e['stream'] = stream
                        elif action == 'pending':
                            await self.send_live(login, e, stream)
                        elif action == 'live':
                            if e.get('stream_id'):
                                await self.end_card(login, e)
                            await self.send_live(login, e, stream)
                        elif action == 'offline':
                            await self.end_card(login, e)
                        e['last_check'] = now
                        self.store.save()
                    except (discord.HTTPException, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
                        # Each account retries on its own cadence; no hot retry loop or false offline.
                        e['last_check'] = now
                        self.store.save()
                        self.last_error = f'{login}: 通知更新失敗，會按原頻率重試。'
                        log.warning('Stream delivery deferred for %s', login)
                self.last_success = now
                self.store.state['metrics'] = {'last_success': now, 'requests_session': self.api.requests,
                                               'roster': len(self.store.state['entries'])}
                self.store.save()
        except Exception as exc:
            self.last_error = f'直播檢查失敗：{type(exc).__name__}（未改為已結束）'
            log.warning('Stream check failed: %s', type(exc).__name__)
            await asyncio.sleep(30)  # A failing API is never polled more frequently than once per minute.

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    def embed(self, selected=None):
        s = self.store.state
        rows = s['entries']
        member = sum(e['group'] == 'member' for e in rows.values())
        lines = [f"狀態：{'運行中' if s['enabled'] else '已暫停'}｜Twitch：{'已設定' if self.api else '未設定'}",
                 f"名單：{member} 位成員／{len(rows) - member} 位友台",
                 f"成員每 5 分鐘｜友台每 {s['partner_minutes']} 分鐘",
                 f"成員提及：{'開' if s['member_ping'] else '關'}｜友台不提及成員",
                 f"成員：<#{s['member_channel']}>｜友台：<#{s['partner_channel']}>",
                 '每場一張卡；直播結束時更新原卡，已刪除的卡片不補發。',
                 '新增／恢復／切換首次檢查只建立基準，不補發已開始的直播。']
        if selected in rows:
            e = rows[selected]
            lines.append(f"\n已選：**{selected}**｜{'成員' if e['group'] == 'member' else '友台'}｜{'啟用' if e['enabled'] else '停用'}")
        if self.last_success:
            lines.append(f'最後成功檢查：<t:{int(self.last_success)}:R>')
        if self.last_error:
            lines.append('最近錯誤：' + self.last_error)
        lines.append(f"本次程序 Twitch 請求：{self.api.requests if self.api else 0}")
        return discord.Embed(title='📺 直播名單管理', description='\n'.join(lines), color=0x9146ff)

    async def show(self, inter, selected=None, page=0):
        if not await authorized(inter):
            return
        kwargs = dict(embed=self.embed(selected), view=StreamAdmin(self, selected, page), allowed_mentions=NONE)
        if inter.response.is_done():
            if inter.response.type == discord.InteractionResponseType.deferred_message_update:
                await inter.edit_original_response(**kwargs)
            else:
                await inter.followup.send(**kwargs, ephemeral=True)
        elif inter.type == discord.InteractionType.component:
            await inter.response.edit_message(**kwargs)
        else:
            await inter.response.send_message(**kwargs, ephemeral=True)

    async def menu_entry(self, inter):
        if not await authorized(inter):
            return
        await inter.response.send_message(embed=self.embed(), view=StreamAdmin(self), ephemeral=True, allowed_mentions=NONE)

    @app_commands.command(name='stream_demo', description='在測試公告示範直播開始、去重及結束時更新原卡')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def demo(self, inter: discord.Interaction):
        if not await authorized(inter):
            return
        if inter.channel_id != STREAM_SANDBOX_CHANNEL:
            return await inter.response.send_message(f'請在 <#{STREAM_SANDBOX_CHANNEL}> 執行；示範只會發到沙盤。', ephemeral=True)
        await inter.response.defer(ephemeral=True)
        session = StreamDemoSession(self.bot, inter.channel, inter.id)
        async with session.lock:
            await session.check()
        view = StreamDemoView(session)
        message = await inter.channel.send(session.summary(), view=view, allowed_mentions=NONE, silent=True)
        await inter.followup.send(f'沙盤示範已建立：{message.jump_url}', ephemeral=True)

    @app_commands.command(name='stream_admin', description='管理直播名單、檢查頻率及通知狀態')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def admin(self, inter: discord.Interaction):
        await self.menu_entry(inter)

    @app_commands.command(name='stream_channels', description='管理員：設定成員及友台直播通知頻道')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def channels(self, inter: discord.Interaction, member: discord.TextChannel, partner: discord.TextChannel):
        if not await authorized(inter):
            return
        if any(c.guild.id != config.GUILD_ID for c in (member, partner)):
            return await inter.response.send_message('只可用本伺服器頻道。', ephemeral=True)
        for channel in (member, partner):
            perms = channel.permissions_for(inter.guild.me)
            if not all((perms.view_channel, perms.send_messages, perms.embed_links, perms.read_message_history)):
                return await inter.response.send_message('Bot 需要查看、發送、嵌入連結及讀取歷史權限。', ephemeral=True)
        await inter.response.defer(ephemeral=True)
        async with self.lock:
            self.store.state.update(member_channel=member.id, partner_channel=partner.id)
            self.store.save()
        await self.show(inter)

    @app_commands.command(name='stream_panel', description='管理員：建立固定直播管理按鈕')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self, inter: discord.Interaction, channel: discord.TextChannel):
        if not await authorized(inter):
            return
        if channel.guild.id != config.GUILD_ID or channel.permissions_for(inter.guild.default_role).view_channel:
            return await inter.response.send_message('請選擇管理員專用頻道。', ephemeral=True)
        await inter.response.defer(ephemeral=True)
        message = await channel.send('📺 **直播通知管理**\n成員 5 分鐘／友台 30 分鐘起；每場一張卡，直播結束時更新原卡。\n按鈕只限管理員；名單及設定只會向操作者顯示。',
                                     view=StreamPanel(self), allowed_mentions=NONE)
        await inter.followup.send(message.jump_url, ephemeral=True)


STREAM_SANDBOX_CHANNEL = 1564479766013149286


class DemoStore:
    def __init__(self):
        self.state = default_state()
        self.state['member_ping'] = False

    def save(self):
        pass  # Deliberately isolated in memory; never touches the production database.


class DemoAPI:
    async def get(self, *args, **kwargs):
        return {'data': []}  # No Twitch network calls, including optional VOD lookups.


class StreamDemoSession(StreamAlerts):
    """Exercises real send_live/end_card paths with a fixed sandbox-only route."""
    def __init__(self, bot, channel, session_id):
        if channel.id != STREAM_SANDBOX_CHANNEL or channel.guild.id != config.GUILD_ID:
            raise ValueError('Stream demo is restricted to the sandbox')
        self.bot, self.sandbox, self.lock = bot, channel, asyncio.Lock()
        self.store, self.api = DemoStore(), DemoAPI()
        self.ended, self.checks = False, 0
        self.sent_ids = []
        started = datetime.now(timezone.utc).isoformat()
        self.streams = {}
        for login, group, display in [('jeff_con9sole', 'member', '成員台（模擬）'),
                                      ('fatboychiu', 'partner', '友台（模擬）')]:
            self.store.state['entries'][login] = {
                'group': group, 'enabled': True, 'initialized': True, 'last_check': 0,
                'stream_id': None, 'started_at': None, 'message_id': None,
                'message_channel': None, 'pending': None}
            self.streams[login] = {'id': f'demo-{session_id}-{login}', 'user_login': login,
                'user_name': display, 'user_id': 'demo', 'started_at': started,
                'title': '【沙盤模擬】一齊打機，測試直播通知', 'game_name': '測試遊戲（模擬資料）'}

    def channel(self, group):
        return self.sandbox

    def card(self, login, stream, *, ended=False, vod=None):
        embed, view = super().card(login, stream, ended=ended, vod=vod)
        embed.title = ('【沙盤模擬・成員】' if self.store.state['entries'][login]['group'] == 'member'
                       else '【沙盤模擬・友台】') + ('直播已結束' if ended else '直播通知')
        embed.description = '🧪 **模擬資料，並非實際直播；此測試不會提及成員。**\n' + embed.description
        embed.set_image(url=None)
        embed.add_field(name='檢查頻率', value='每 5 分鐘' if self.store.state['entries'][login]['group'] == 'member' else '每 30 分鐘', inline=True)
        return embed, view

    async def check(self, *, close=False):
        if close:
            self.ended = True
        actions = []
        for login, e in self.store.state['entries'].items():
            stream = None if self.ended else self.streams[login]
            action = transition(e, stream)
            if action == 'live':
                await self.send_live(login, e, stream)
                self.sent_ids.append(e['message_id'])
            elif action == 'offline':
                await self.end_card(login, e)
            actions.append(action)
        self.checks += 1
        return actions

    def summary(self):
        links = '｜'.join(f'[第 {i} 張卡](https://discord.com/channels/{config.GUILD_ID}/{self.sandbox.id}/{mid})'
                         for i, mid in enumerate(self.sent_ids, 1))
        return ('🧪 **直播通知沙盤示範**\n'
                f"狀態：{'直播已結束（原卡已更新）' if self.ended else '模擬直播中'}｜直播卡 {len(self.sent_ids)} 張｜檢查 {self.checks} 輪\n"
                '成員 5 分鐘／友台 30 分鐘；兩類模擬通知都不提及成員。\n'
                '「重複檢查」應保持原有卡數；「模擬直播結束」會改原卡，不另發結束通知。\n'
                '正式名單／狀態不變；Twitch API 呼叫 0。按鈕有效 20 分鐘。\n' + links)


class StreamDemoView(AdminView):
    def __init__(self, session):
        super().__init__(timeout=1200)
        self.session = session

    @discord.ui.button(label='重複檢查（不新增卡）', style=discord.ButtonStyle.secondary)
    async def repeat(self, inter, button):
        await inter.response.defer()
        async with self.session.lock:
            await self.session.check()
            await inter.edit_original_response(content=self.session.summary(), view=self, allowed_mentions=NONE)

    @discord.ui.button(label='模擬直播結束（更新原卡）', style=discord.ButtonStyle.primary)
    async def close(self, inter, button):
        await inter.response.defer()
        async with self.session.lock:
            await self.session.check(close=True)
            button.disabled = True
            await inter.edit_original_response(content=self.session.summary(), view=self, allowed_mentions=NONE)


async def setup(bot):
    await bot.add_cog(StreamAlerts(bot))
