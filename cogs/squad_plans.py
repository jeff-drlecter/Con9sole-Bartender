"""One form, one card: future squads without voice presence or subscription pings."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from features.wording import modal_copy as wording_modal, view_copy as wording_view
from core.permissions import is_server_admin, is_verified_member
from core.storage_paths import DATA_DIR
from core.ui import SafeModal, SafeView
from features.squad_plans import ACTIVE, HK, PlanBook, confirmed, counts, deadline, parse_start

log = logging.getLogger(__name__)
TARGET = discord.Object(id=config.GUILD_ID)
NONE = discord.AllowedMentions.none()
PANEL_COPY = '🎮 **約一局**\n現在玩或約定時間，填好遊戲、模式及人數，讓其他人按卡加入。'


def can_read(interaction, channel=None):
    channel = interaction.channel if channel is None else channel
    return (interaction.guild_id == config.GUILD_ID
            and isinstance(channel, discord.TextChannel)
            and (is_verified_member(interaction.user) or is_server_admin(interaction.user))
            and channel.permissions_for(interaction.user).view_channel
            and channel.permissions_for(interaction.user).read_message_history)


def allowed(interaction, channel=None):
    channel = interaction.channel if channel is None else channel
    return (interaction.guild_id == config.GUILD_ID
            and isinstance(channel, discord.TextChannel)
            and (is_verified_member(interaction.user) or is_server_admin(interaction.user))
            and channel.permissions_for(interaction.user).view_channel
            and channel.permissions_for(interaction.user).send_messages)


def game_hint(channel):
    name = getattr(getattr(channel, 'category', None), 'name', '')
    for fragment, label in [('GTA', 'GTA'), ('NBA 2K', 'NBA 2K'),
                            ('EA SPORTS FC', 'EA SPORTS FC'), ('Helldivers', 'Helldivers 2'),
                            ('Monster Hunter', 'Monster Hunter'), ('Battlefield', 'Battlefield 6'),
                            ('Delta Force', 'Delta Force'), ('Apex', 'Apex Legends'),
                            ('First Descendant', 'The First Descendant'), ('Where Winds Meet', 'Where Winds Meet')]:
        if fragment.casefold() in name.casefold():
            return label
    return ''


def squad_channel(channel):
    return isinstance(channel, discord.TextChannel) and getattr(channel, 'category_id', None) != config.TEMPLATE_CATEGORY_ID and (
        channel.name.endswith('-吹水組隊') or channel.name == '公海吹水'
        or ('測試' in getattr(getattr(channel, 'category', None), 'name', '')
            and channel.name.endswith('體驗交流'))
    )


class PlanChannelView(SafeView):
    """Choose only a destination the member and bot can currently use."""
    def __init__(self, cog, owner_id, channels, *, instant=False):
        super().__init__(timeout=180)
        self.cog, self.owner_id = cog, owner_id
        # Discord permits 25 options per select; use separate rows if needed.
        for offset in range(0, len(channels), 25):
            select = discord.ui.Select(placeholder='選擇組隊頻道', options=[
                discord.SelectOption(label=channel.name[:100], value=str(channel.id))
                for channel in channels[offset:offset + 25]
            ])
            async def choose(interaction, select=select):
                if interaction.user.id != self.owner_id:
                    await interaction.response.send_message('請用 /menu 開啟自己的約局選單。', ephemeral=True)
                    return
                channel = interaction.guild.get_channel(int(select.values[0])) if interaction.guild else None
                if not squad_channel(channel) or not allowed(interaction, channel):
                    await interaction.response.send_message('此頻道已無法使用，請重新開啟 /menu。', ephemeral=True)
                    return
                await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self.cog, channel, instant=instant)))
            select.callback = choose
            self.add_item(select)


def card(plan):
    accepted = confirmed(plan)
    total = plan['party'] + len(accepted)
    state = {'open': '預約中', 'due': '招募中' if plan.get('instant') else '待開局',
             'gathering': '集合中', 'live': '進行中', 'history': '歷史預約・開局情況未核實',
             'expired': '未開局', 'ended': '已結束', 'started': '已到開始時間', 'cancelled': '已取消'}[plan['status']]
    if plan['status'] in {'open', 'due'} and plan['capacity'] is not None and total >= plan['capacity']:
        state += '・名額已滿'
    safe = discord.utils.escape_markdown
    embed = discord.Embed(title=f"📅 {safe(plan['game'])} · {state}", colour=0x5865F2)
    embed.description = f"🕙 <t:{plan['start']}:F> · <t:{plan['start']}:R>\n🎮 平台／模式：{safe(plan['mode']) if plan['mode'] else '未填寫'}"
    target = f"／{plan['capacity']}" if plan['capacity'] is not None else ''
    if plan['status'] in ACTIVE:
        remaining = max(0, plan['capacity'] - total) if plan['capacity'] is not None else None
        embed.description += f'\n🙋 尚欠 {remaining} 人' if remaining is not None else '\n🙋 招募人數不限'
    embed.add_field(name=f'👥 已有 {total}{target} 人',
                    value=f"發起人原有 {plan['party']} 人（包括自己）\n按卡確認 {len(accepted)} 人 · 稍後到 {len(set(accepted) & set(plan.get('late', [])))} 人"
                    + (f"\n待重新確認 {len(plan.get('unconfirmed', []))} 人" if plan.get('unconfirmed') else ''), inline=False)
    # Keep the participant roster behind the private list button.
    embed.add_field(name='發起人', value=f"<@{plan['owner']}>", inline=True)
    if plan.get('voice') and plan['status'] in {'gathering', 'live'}:
        embed.add_field(name='本局語音', value=f"<#{plan['voice']}>", inline=False)
    if plan.get('footprint'):
        url = f"https://discord.com/channels/{plan['guild']}/{plan['channel']}/{plan['footprint']}"
        embed.add_field(name='本局足跡', value=f'[查看實際參與紀錄]({url})', inline=False)
    embed.set_footer(text='原有隊友無需重複報名 · 報名不等於到場 · 發起人從名單／選項開局')
    return embed


class PlanForm(SafeModal):
    def __init__(self, cog, channel, plan=None, *, instant=False, seed=None):
        super().__init__(title='約一局' if plan is None else '修改約局')
        self.cog, self.channel_id, self.plan_id = cog, channel.id, plan and plan['id']
        self.instant = instant or bool(plan and plan.get('instant'))
        self.game = discord.ui.TextInput(label='遊戲', default=plan['game'] if plan else game_hint(channel), max_length=80)
        self.start = discord.ui.TextInput(label='開始時間（24小時制）', placeholder='今晚22:00／明天22:00',
            default=datetime.fromtimestamp(plan['start'], HK).strftime('%Y-%m-%d %H:%M') if plan else None, max_length=30)
        self.mode = discord.ui.TextInput(label='平台／模式（選填）', placeholder='例如 PS5／Clubs、PC／征服、跨平台／REC',
            default=plan['mode'] if plan else '', required=False, max_length=80)
        if seed and not plan:
            self.game.default, self.mode.default = seed['game'], seed['mode']
        self.party = discord.ui.TextInput(label='已有人數（包括自己）', default=str(plan['party']) if plan else '1', max_length=2)
        self.missing = discord.ui.TextInput(label='尚欠人數（選填，留空不限）', required=False, max_length=2,
            default=str(plan['capacity'] - plan['party']) if plan and plan['capacity'] else '')
        items = (self.game, self.mode, self.party, self.missing) if instant and not plan else (self.game, self.start, self.mode, self.party, self.missing)
        for item in items:
            self.add_item(item)

    async def on_submit(self, interaction):
        channel = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
        if channel is None or not allowed(interaction, channel) or (self.plan_id and interaction.channel_id != self.channel_id):
            await interaction.response.send_message('請在可發言的遊戲文字頻道使用。', ephemeral=True)
            return
        try:
            party, capacity = counts(self.party.value, self.missing.value)
            game = self.game.value.strip()
            if not game:
                raise ValueError('請填遊戲名稱。')
            old = self.cog.book.get(self.plan_id) if self.plan_id else None
            unchanged = old and self.start.value == datetime.fromtimestamp(old['start'], HK).strftime('%Y-%m-%d %H:%M')
            start = old['start'] if unchanged else int(self.cog.book.clock()) if self.instant and not self.plan_id else parse_start(self.start.value)
            changes = dict(game=game, mode=self.mode.value.strip(), start=start, party=party, capacity=capacity)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                if self.plan_id:
                    p = self.cog.book.get(self.plan_id)
                    if not p or p['channel'] != channel.id:
                        raise ValueError('找不到此約局。')
                    p = self.cog.book.act(self.plan_id, interaction.user.id, 'edit', changes=changes)
                    refreshed = await self.cog.refresh(p)
                else:
                    perms = channel.permissions_for(interaction.guild.me)
                    if not all((perms.view_channel, perms.send_messages, perms.embed_links, perms.read_message_history)):
                        raise ValueError('Bot 需要查看、發訊息、嵌入連結及讀取歷史權限。')
                    teams = self.cog.bot.get_cog('Teams') if getattr(self.cog, 'bot', None) else None
                    if self.instant and teams and any(s.leader_id == interaction.user.id and not s.cancelled
                            and not teams.is_state_expired(s) for s in teams.states.values()):
                        raise ValueError('你仍有舊版即時招募，請先完成該局；原有卡片仍可使用。')
                    p = self.cog.book.create(guild=interaction.guild_id, channel=channel.id, owner=interaction.user.id, instant=self.instant, **changes)
                    # Persist the posting attempt first. An ambiguous send is never replayed.
                    posted = dict(p, status='due' if self.instant else 'open')
                    view = PlanView(self.cog, posted)
                    message = await channel.send(embed=card(posted), view=view, allowed_mentions=NONE)
                    self.cog.book.publish(p['id'], message.id)
                    refreshed = True
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
        await interaction.followup.send('已更新約局。' if self.plan_id else f'約局已發到 {channel.mention}，其他人可以按卡加入。', ephemeral=True,
            allowed_mentions=NONE)
        if not refreshed:
            await interaction.followup.send('資料已儲存；卡片暫時無法更新，稍後會重試。', ephemeral=True)
        if not self.plan_id and getattr(self.cog, 'bot', None):
            from features.member_activity import complete_task
            await complete_task(self.cog.bot, interaction, 'team')


class PlanView(SafeView):
    def __init__(self, cog, plan):
        super().__init__(timeout=None)
        self.cog, self.key = cog, plan['id']
        for action, label, style in [('join', '🙋 我參加', discord.ButtonStyle.success),
                                     ('late', '稍後到', discord.ButtonStyle.secondary),
                                     ('manage', '名單／管理', discord.ButtonStyle.secondary)]:
            if action == 'manage' and plan['status'] not in ACTIVE:
                label = '查看名單'
            button = discord.ui.Button(label=label, style=style, custom_id=f"plan:{self.key}:{action}",
                                       disabled=action != 'manage' and plan['status'] not in ACTIVE)
            async def callback(interaction, action=action):
                await self.handle(interaction, action)
            button.callback = callback
            self.add_item(button)
        # Keep the previous public leave custom ID routable on old posted cards.
        leave = discord.ui.Button(label='退出', custom_id=f'plan:{self.key}:leave', row=1,
                                  disabled=plan['status'] not in ACTIVE)
        leave.callback = lambda interaction: self.handle(interaction, 'leave')
        self.add_item(leave)
        if plan.get('voice') and plan['status'] in {'gathering', 'live'}:
            self.add_item(discord.ui.Button(label='🎧 加入語音', style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{plan['guild']}/{plan['voice']}", row=0))
        if plan['status'] not in ACTIVE:
            again = discord.ui.Button(label='再約一局', custom_id=f'plan:{self.key}:again', row=1)
            again.callback = lambda interaction: self.handle(interaction, 'again')
            self.add_item(again)

    async def handle(self, interaction, action):
        p = self.cog.book.get(self.key)
        permitted = can_read(interaction) if action == 'manage' else allowed(interaction)
        if (not permitted or not p or p['guild'] != interaction.guild_id
                or p['channel'] != interaction.channel_id or p['message'] != interaction.message.id):
            await interaction.response.send_message('你無法操作此約局卡。', ephemeral=True)
            return
        if action == 'manage':
            active = p['status'] in ACTIVE
            roster = '\n'.join(f"<@{uid}> · {'待重新確認' if uid in p.get('unconfirmed', []) else '稍後到' if uid in p.get('late', []) else '已確認'}" for uid in p['members']) or '暫無成員按卡加入。'
            # Chunk into private messages without ever pinging the listed members.
            controls = {'view': ManageView(self.cog, self.key, interaction.user.id == p['owner'], is_server_admin(interaction.user))} if active else {}
            await interaction.response.send_message(f"原有 {p['party']} 人（包括發起人）；按卡加入 {len(p['members'])} 人。",
                **controls, ephemeral=True, allowed_mentions=NONE)
            for offset in range(0, len(roster), 1800):
                await interaction.followup.send(roster[offset:offset + 1800], ephemeral=True, allowed_mentions=NONE)
            return
        if action == 'again':
            await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self.cog, interaction.channel, seed=p)))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                p = self.cog.book.act(self.key, interaction.user.id, action)
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            refreshed = await self.cog.refresh(p)
        await interaction.followup.send(('已加入。原有隊友請勿重複報名；本局暫不另發開局提醒。' if action == 'join' else '已登記稍後到；本局暫不另發開局提醒。' if action == 'late' else '已退出。')
            + ('' if refreshed else '資料已儲存，卡片稍後更新。'), ephemeral=True)


class ManageView(SafeView):
    def __init__(self, cog, key, owner, admin):
        super().__init__(timeout=120)
        self.cog, self.key = cog, key
        self.edit.disabled = not owner
        self.cancel.disabled = not (owner or admin)
        self.start.disabled = not owner

    async def interaction_check(self, interaction):
        p = self.cog.book.get(self.key)
        return bool(allowed(interaction) and p and p['channel'] == interaction.channel_id
                    and (p['owner'] == interaction.user.id or is_server_admin(interaction.user)))

    @discord.ui.button(label='修改時間／模式／人數')
    async def edit(self, interaction, button):
        p = self.cog.book.get(self.key)
        if p['owner'] != interaction.user.id:
            await interaction.response.send_message('只有發起人可以修改。', ephemeral=True)
            return
        await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self.cog, interaction.channel, p)))

    @discord.ui.button(label='開局／連接語音', style=discord.ButtonStyle.primary)
    async def start(self, interaction, button):
        p = self.cog.book.get(self.key)
        if not p or p['owner'] != interaction.user.id or p['status'] not in {'open', 'due', 'gathering'}:
            await interaction.response.send_message('只有發起人可為尚未開始的約局開局。', ephemeral=True)
            return
        await interaction.response.send_message('🎧 **開局確認**\n將使用本遊戲的小隊語音房；不會移動其他成員。\n原卡會提供加入入口；本局暫不新增報名者開局提醒。',
            view=StartView(self.cog, self.key, interaction.user.id), ephemeral=True, allowed_mentions=NONE)

    @discord.ui.button(label='取消約局', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                p = self.cog.book.act(self.key, interaction.user.id, 'cancel', admin=is_server_admin(interaction.user))
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            await self.cog.refresh(p)
        await interaction.followup.send('已取消約局。', ephemeral=True)


class PlanEntry(SafeView):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label='📅 約一局', style=discord.ButtonStyle.primary, custom_id='plan:new:v1')
    async def create(self, interaction, button):
        await self.cog.menu_entry(interaction)


class StartView(SafeView):
    def __init__(self, cog, key, owner):
        super().__init__(timeout=120)
        self.cog, self.key, self.owner = cog, key, owner

    @discord.ui.button(label='確認開局', style=discord.ButtonStyle.primary)
    async def start(self, interaction, button):
        p = self.cog.book.get(self.key)
        if (interaction.user.id != self.owner or not p or p['owner'] != self.owner
                or p['guild'] != interaction.guild_id or p['channel'] != interaction.channel_id
                or not allowed(interaction)):
            await interaction.response.send_message('此開局面板已無法使用，請重新開啟原卡。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                p = self.cog.book.get(self.key)
                if not p or p['status'] not in {'open', 'due', 'gathering'} or self.cog.book.clock() > deadline(p):
                    raise ValueError('此約局已無法開局，請重新開啟原卡。')
                tempvc = self.cog.bot.get_cog('TempVC')
                if tempvc is None:
                    raise ValueError('語音功能暫時未能使用，約局紀錄仍保留。')
                cards = self.cog.bot.get_cog('SquadCards')
                settings = cards.state.get('settings', {}) if cards else {}
                routes = dict(settings.get('routes', {}))
                if 'category' in settings:
                    routes.setdefault(str(settings['category']), settings['destination'])
                if str(getattr(interaction.channel, 'category_id', None)) not in routes:
                    raise ValueError('此遊戲區尚未設定場次記錄，請由管理員核對；現有約局保留。')
                room = await tempvc.room_for_plan(interaction,
                    before_create=lambda: self.cog.book.begin_voice_attempt(self.key, self.owner))
                session = cards.state.get('sessions', {}).get(str(room.id))
                if session and session.get('ended') is not None:
                    raise ValueError('上一局仍在整理足跡，請稍後重新開局；不會重複綁定。')
                p = self.cog.book.link_voice(self.key, self.owner, room.id)
                await self.cog.refresh(p)
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
        url = f'https://discord.com/channels/{interaction.guild_id}/{room.id}'
        await interaction.followup.send(f'本局語音已備妥：[加入語音]({url})。原卡已提供相同入口；有人加入後才開始記錄實際場次。', ephemeral=True, allowed_mentions=NONE)


class PlanMenu(SafeView):
    def __init__(self, cog, owner):
        super().__init__(timeout=180)
        self.cog, self.owner = cog, owner

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner and can_read(interaction):
            return True
        await interaction.response.send_message('請重新開啟自己的「約一局」選單。', ephemeral=True)
        return False

    @discord.ui.button(label='現在玩', style=discord.ButtonStyle.primary)
    async def now(self, interaction, button):
        await self.cog.choose_destination(interaction, instant=True)

    @discord.ui.button(label='約定時間')
    async def scheduled(self, interaction, button):
        await self.cog.choose_destination(interaction)

    @discord.ui.button(label='我的約局')
    async def mine(self, interaction, button):
        await self.cog.my_plans(interaction)


class SquadPlans(commands.Cog):
    def __init__(self, bot):
        self.bot, self.lock = bot, asyncio.Lock()
        self.book = PlanBook(DATA_DIR / 'squad_plans.json')

    async def menu_entry(self, interaction):
        if not can_read(interaction):
            await interaction.response.send_message('請完成驗證，並在可查看的社群文字頻道使用。', ephemeral=True)
            return
        from features.language_preferences import language
        view = PlanMenu(self, interaction.user.id)
        content = '🎮 **約一局**\n現在找隊友、約定時間，或繼續已有的約局。'
        if language(interaction.user) == 'hk':
            content = '🎮 **約一局**\n而家搵隊友、約定時間，或者繼續已有嘅約局。'
            view.now.label, view.mine.label = '而家玩', '我嘅約局'
        await interaction.response.send_message(content, view=view, ephemeral=True)

    async def choose_destination(self, interaction, *, instant=False):
        if not can_read(interaction):
            await interaction.response.send_message('請在可查看的社群文字頻道開啟自己的約局選單。', ephemeral=True)
            return
        if squad_channel(interaction.channel) and allowed(interaction):
            await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self, interaction.channel, instant=instant)))
            return
        channels = [channel for channel in interaction.guild.text_channels
                    if squad_channel(channel) and allowed(interaction, channel)
                    and all(getattr(channel.permissions_for(interaction.guild.me), name)
                            for name in ('view_channel', 'send_messages', 'embed_links', 'read_message_history'))]
        if not channels:
            await interaction.response.send_message('暫無可用的組隊頻道；請到 <id:customize> 選擇遊戲，或向 Helper 查詢。', ephemeral=True)
            return
        await interaction.response.send_message('📅 選擇要發起約局的頻道：',
            view=PlanChannelView(self, interaction.user.id, channels[:125], instant=instant), ephemeral=True)

    async def my_plans(self, interaction):
        if not can_read(interaction):
            await interaction.response.send_message('請重新開啟自己的「約一局」選單。', ephemeral=True)
            return
        plans = [p for p in self.book.all() if p['guild'] == interaction.guild_id
                 and (p['owner'] == interaction.user.id or interaction.user.id in p['members'])
                 and p.get('message') and interaction.guild.get_channel(p['channel']) is not None
                 and can_read(interaction, interaction.guild.get_channel(p['channel']))]
        plans.sort(key=lambda p: (p['status'] not in ACTIVE, -p['start']))
        view = SafeView(timeout=180)
        for p in plans[:20]:
            view.add_item(discord.ui.Button(label=f"{p['game']} · {datetime.fromtimestamp(p['start'], HK):%m/%d %H:%M}"[:80],
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{p['guild']}/{p['channel']}/{p['message']}"))
        teams = self.bot.get_cog('Teams') if getattr(self, 'bot', None) else None
        if teams:
            for old in teams.states.values():
                destination = interaction.guild.get_channel(old.channel_id)
                if (len(view.children) >= 24 or old.cancelled or teams.is_state_expired(old)
                        or old.guild_id != interaction.guild_id or not destination
                        or not can_read(interaction, destination)
                        or interaction.user.id not in {old.leader_id, *old.join_now, *old.join_later}):
                    continue
                view.add_item(discord.ui.Button(label=f'舊版即時招募 · {old.mode}'[:80], style=discord.ButtonStyle.link,
                    url=f'https://discord.com/channels/{old.guild_id}/{old.channel_id}/{old.message_id}'))
        await interaction.response.send_message('你的約局及報名紀錄（活動約局優先）：' if view.children else '暫時沒有你發起或按卡報名的約局。',
            view=view, ephemeral=True, allowed_mentions=NONE)

    async def cog_load(self):
        self.bot.add_view(PlanEntry(self))
        for p in self.book.all():
            if p['message']:
                self.bot.add_view(PlanView(self, p), message_id=p['message'])
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    async def refresh(self, p):
        channel = self.bot.get_channel(p['channel'])
        if not channel or not p['message']:
            return False
        try:
            message = await channel.fetch_message(p['message'])
            if message.author.id != self.bot.user.id:
                return False
            await message.edit(embed=card(p), view=PlanView(self, p), allowed_mentions=NONE)
            self.book.clean(p['id'], p.get('revision', 0))
            return True
        except discord.NotFound:
            self.book.clean(p['id'], p.get('revision', 0))
            return False
        except discord.HTTPException:
            log.exception('Scheduled squad card refresh failed: %s', p['id'])
            return False

    @tasks.loop(seconds=30)
    async def tick(self):
        if not self.bot.is_ready():
            return
        try:
            async with self.lock:
                self.book.expire()
                for p in self.book.all():
                    if p['status'] == 'gathering' and not self.bot.get_channel(p.get('voice')):
                        self.book.release_voice(p['id'])
                        p = self.book.get(p['id'])
                    if p['dirty']:
                        await self.refresh(p)
        except Exception:
            log.exception('Scheduled squad reconciliation failed')

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='約局', description='約定時間玩遊戲：填時間、模式及已有幾人')
    @app_commands.guild_only()
    async def plan(self, interaction: discord.Interaction):
        await self.menu_entry(interaction)

    @app_commands.command(name='約局面板', description='管理員：喺目前文字頻道放置約局按鈕')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(lambda i: is_server_admin(i.user))
    async def panel(self, interaction: discord.Interaction):
        if not allowed(interaction) or not is_server_admin(interaction.user):
            await interaction.response.send_message('只有管理員可設定入口。', ephemeral=True)
            return
        await interaction.response.send_message(PANEL_COPY,
            view=PlanEntry(self), allowed_mentions=NONE)

    @app_commands.command(name='約局整理', description='管理員：更新現有約局卡及已置頂入口；不新增通知')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def refresh_cards(self, interaction: discord.Interaction):
        if interaction.guild_id != config.GUILD_ID or not is_server_admin(await interaction.guild.fetch_member(interaction.user.id)):
            await interaction.response.send_message('只限本社群管理員。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        updated, failed = 0, 0
        async with self.lock:
            self.book.expire()
            for plan in self.book.all():
                if plan['guild'] == interaction.guild_id and plan['message']:
                    if await self.refresh(plan):
                        updated += 1
                    else:
                        failed += 1
            seen = set()
            async def update_entry(message):
                nonlocal updated
                if message.id in seen:
                    return
                seen.add(message.id)
                ids = {getattr(item, 'custom_id', None) for row in message.components for item in row.children}
                if message.author.id == self.bot.user.id and 'plan:new:v1' in ids:
                    await message.edit(content=PANEL_COPY, view=PlanEntry(self), allowed_mentions=NONE)
                    updated += 1
            for channel in interaction.guild.text_channels:
                if not squad_channel(channel):
                    continue
                try:
                    async for message in channel.pins():
                        await update_entry(message)
                    async for message in channel.history(limit=50):
                        await update_entry(message)
                except discord.HTTPException:
                    failed += 1
        await interaction.followup.send(f'已更新 {updated} 張現有卡片／入口；未完成 {failed} 項。沒有新增通知。', ephemeral=True)


async def setup(bot):
    await bot.add_cog(SquadPlans(bot), guild=TARGET)
