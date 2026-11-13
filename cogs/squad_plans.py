"""One form, one card: future squads without voice presence or subscription pings."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from features.wording import modal_copy as wording_modal
from core.permissions import is_server_admin, is_verified_member
from core.storage_paths import DATA_DIR
from core.ui import SafeModal, SafeView
from features.squad_plans import HK, PlanBook, counts, parse_start

log = logging.getLogger(__name__)
TARGET = discord.Object(id=config.GUILD_ID)
NONE = discord.AllowedMentions.none()


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
                            ('Monster Hunter', 'Monster Hunter'), ('Battlefield', 'Battlefield 6')]:
        if fragment.casefold() in name.casefold():
            return label
    return ''


def squad_channel(channel):
    return isinstance(channel, discord.TextChannel) and (
        channel.name.endswith('-吹水組隊') or channel.name == '公海吹水'
        or ('測試' in getattr(getattr(channel, 'category', None), 'name', '')
            and channel.name.endswith('體驗交流'))
    )


class PlanChannelView(SafeView):
    """Choose only a destination the member and bot can currently use."""
    def __init__(self, cog, owner_id, channels):
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
                    await interaction.response.send_message('請用 /menu 開啟自己嘅約局選單。', ephemeral=True)
                    return
                channel = interaction.guild.get_channel(int(select.values[0])) if interaction.guild else None
                if not squad_channel(channel) or not allowed(interaction, channel):
                    await interaction.response.send_message('你已無法喺呢個頻道約局，請重新開啟 /menu。', ephemeral=True)
                    return
                await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self.cog, channel)))
            select.callback = choose
            self.add_item(select)


def card(plan):
    total = plan['party'] + len(plan['members'])
    state = {'open': '召集中', 'started': '已到開始時間', 'cancelled': '已取消'}[plan['status']]
    if plan['status'] == 'open' and plan['capacity'] is not None and total >= plan['capacity']:
        state = '已滿人'
    safe = discord.utils.escape_markdown
    embed = discord.Embed(title=f"📅 {safe(plan['game'])} · {state}", colour=0x5865F2)
    embed.description = f"🕙 <t:{plan['start']}:F> · <t:{plan['start']}:R>\n🎮 {safe(plan['mode']) if plan['mode'] else '模式未定'}"
    target = f"／{plan['capacity']}" if plan['capacity'] is not None else ''
    embed.add_field(name=f'👥 已有 {total}{target} 人',
                    value=f"發起人原有 {plan['party']} 人（包括自己）\n按卡加入 {len(plan['members'])} 人", inline=False)
    members = '、'.join(f'<@{uid}>' for uid in plan['members'])
    # Discord caps field values at 1024; show the complete roster privately instead.
    embed.add_field(name='發起人', value=f"<@{plan['owner']}>", inline=True)
    if members:
        embed.add_field(name='按卡加入', value=members if len(members) <= 900 else f"共 {len(plan['members'])} 人；按「名單／管理」查看。", inline=False)
    embed.set_footer(text='時間以你嘅 Discord 時區顯示 · 原有隊友毋須重複加入 · 到點只結束報名，不會自動開語音')
    return embed


class PlanForm(SafeModal):
    def __init__(self, cog, channel, plan=None):
        super().__init__(title='約一局' if plan is None else '修改約局')
        self.cog, self.channel_id, self.plan_id = cog, channel.id, plan and plan['id']
        self.game = discord.ui.TextInput(label='玩咩遊戲？', default=plan['game'] if plan else game_hint(channel), max_length=80)
        self.start = discord.ui.TextInput(label='幾點？（24小時制）', placeholder='今晚22:00／明天22:00',
            default=datetime.fromtimestamp(plan['start'], HK).strftime('%Y-%m-%d %H:%M') if plan else None, max_length=30)
        self.mode = discord.ui.TextInput(label='模式（選填）', placeholder='例如 Clubs、REC、自由模式',
            default=plan['mode'] if plan else '', required=False, max_length=80)
        self.party = discord.ui.TextInput(label='已有幾人？（包括自己）', default=str(plan['party']) if plan else '1', max_length=2)
        self.missing = discord.ui.TextInput(label='仲差幾人？（選填，留空不限）', required=False, max_length=2,
            default=str(plan['capacity'] - plan['party']) if plan and plan['capacity'] else '')
        for item in (self.game, self.start, self.mode, self.party, self.missing):
            self.add_item(item)

    async def on_submit(self, interaction):
        channel = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
        if channel is None or not allowed(interaction, channel) or (self.plan_id and interaction.channel_id != self.channel_id):
            await interaction.response.send_message('請喺你可以發言嘅遊戲文字頻道使用。', ephemeral=True)
            return
        try:
            party, capacity = counts(self.party.value, self.missing.value)
            game = self.game.value.strip()
            if not game:
                raise ValueError('請填遊戲名稱。')
            changes = dict(game=game, mode=self.mode.value.strip(), start=parse_start(self.start.value), party=party, capacity=capacity)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                if self.plan_id:
                    p = self.cog.book.get(self.plan_id)
                    if not p or p['channel'] != channel.id:
                        raise ValueError('搵唔到呢個約局。')
                    p = self.cog.book.act(self.plan_id, interaction.user.id, 'edit', changes=changes)
                    refreshed = await self.cog.refresh(p)
                else:
                    perms = channel.permissions_for(interaction.guild.me)
                    if not all((perms.view_channel, perms.send_messages, perms.embed_links, perms.read_message_history)):
                        raise ValueError('Bot 需要查看、發訊息、嵌入連結及讀取歷史權限。')
                    p = self.cog.book.create(guild=interaction.guild_id, channel=channel.id, owner=interaction.user.id, **changes)
                    # Persist the posting attempt first. An ambiguous send is never replayed.
                    posted = dict(p, status='open')
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
            await interaction.followup.send('資料已儲存；卡片暫時更新唔到，稍後會重試。', ephemeral=True)


class PlanView(SafeView):
    def __init__(self, cog, plan):
        super().__init__(timeout=None)
        self.cog, self.key = cog, plan['id']
        for action, label, style in [('join', '🙋 我參加', discord.ButtonStyle.success),
                                     ('leave', '退出', discord.ButtonStyle.secondary),
                                     ('manage', '名單／管理', discord.ButtonStyle.secondary)]:
            button = discord.ui.Button(label=label, style=style, custom_id=f"plan:{self.key}:{action}",
                                       disabled=plan['status'] != 'open')
            async def callback(interaction, action=action):
                await self.handle(interaction, action)
            button.callback = callback
            self.add_item(button)

    async def handle(self, interaction, action):
        p = self.cog.book.get(self.key)
        if (not allowed(interaction) or not p or p['guild'] != interaction.guild_id
                or p['channel'] != interaction.channel_id or p['message'] != interaction.message.id):
            await interaction.response.send_message('你無法操作呢張約局卡。', ephemeral=True)
            return
        if action == 'manage':
            if p['status'] != 'open' or p['start'] <= self.cog.book.clock():
                await interaction.response.send_message('約局已結束。', ephemeral=True)
                return
            roster = '、'.join(f'<@{uid}>' for uid in p['members']) or '暫時未有人按卡加入。'
            # Chunk into private messages without ever pinging the listed members.
            await interaction.response.send_message(f"原有 {p['party']} 人（包括發起人）；按卡加入 {len(p['members'])} 人。",
                view=ManageView(self.cog, self.key, interaction.user.id == p['owner'], is_server_admin(interaction.user)),
                ephemeral=True, allowed_mentions=NONE)
            for offset in range(0, len(roster), 1800):
                await interaction.followup.send(roster[offset:offset + 1800], ephemeral=True, allowed_mentions=NONE)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.cog.lock:
            try:
                p = self.cog.book.act(self.key, interaction.user.id, action)
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            refreshed = await self.cog.refresh(p)
        await interaction.followup.send(('已加入。原本已計入發起人隊伍嘅朋友，請勿重複加入。' if action == 'join' else '已退出。')
            + ('' if refreshed else '資料已儲存，卡片稍後更新。'), ephemeral=True)


class ManageView(SafeView):
    def __init__(self, cog, key, owner, admin):
        super().__init__(timeout=120)
        self.cog, self.key = cog, key
        self.edit.disabled = not owner
        self.cancel.disabled = not (owner or admin)

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
        await interaction.response.send_modal(PlanForm(self.cog, interaction.channel, p))

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
        if not allowed(interaction):
            await interaction.response.send_message('已驗證成員可喺可發言嘅文字頻道約局。', ephemeral=True)
            return
        await interaction.response.send_modal(PlanForm(self.cog, interaction.channel))


class SquadPlans(commands.Cog):
    def __init__(self, bot):
        self.bot, self.lock = bot, asyncio.Lock()
        self.book = PlanBook(DATA_DIR / 'squad_plans.json')

    async def menu_entry(self, interaction):
        if not allowed(interaction):
            await interaction.response.send_message('已驗證成員可喺可發言嘅文字頻道約局。', ephemeral=True)
            return
        if squad_channel(interaction.channel):
            await interaction.response.send_modal(wording_modal(interaction.user, PlanForm(self, interaction.channel)))
            return
        channels = [channel for channel in interaction.guild.text_channels
                    if squad_channel(channel) and allowed(interaction, channel)
                    and all(getattr(channel.permissions_for(interaction.guild.me), name)
                            for name in ('view_channel', 'send_messages', 'embed_links', 'read_message_history'))]
        if not channels:
            await interaction.response.send_message('暫時未有可用嘅組隊頻道；請先到「頻道及身份組」選擇遊戲。', ephemeral=True)
            return
        await interaction.response.send_message('📅 想喺邊個頻道約一局？',
            view=PlanChannelView(self, interaction.user.id, channels[:125]), ephemeral=True)

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
            self.book.clean(p['id'])
            return True
        except discord.NotFound:
            self.book.clean(p['id'])
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
        if not allowed(interaction):
            await interaction.response.send_message('已驗證成員可喺可發言嘅文字頻道約局。', ephemeral=True)
            return
        await interaction.response.send_modal(PlanForm(self, interaction.channel))

    @app_commands.command(name='約局面板', description='管理員：喺目前文字頻道放置約局按鈕')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(lambda i: is_server_admin(i.user))
    async def panel(self, interaction: discord.Interaction):
        if not allowed(interaction) or not is_server_admin(interaction.user):
            await interaction.response.send_message('只有管理員可設定入口。', ephemeral=True)
            return
        await interaction.response.send_message('📅 **幾點有空？約一局！**\n填時間、模式同已有人數；其他人按卡加入。',
            view=PlanEntry(self), allowed_mentions=NONE)


async def setup(bot):
    await bot.add_cog(SquadPlans(bot), guild=TARGET)
