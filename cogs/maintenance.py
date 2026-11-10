"""Stage 5: bounded reads, explicit baseline, private once-only alerts."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.storage_paths import DATA_DIR
from features.anti_scam_rules import ALERT_CHANNEL
from features.bot_health import storage_health
from features.maintenance import Store, differences, snapshot, digest
from features.permission_audit import overwrite_rows, permissions, role_permissions

log = logging.getLogger(__name__)
EXPECTED = ('Menu', 'Drink', 'Cheers', 'DailyBar', 'CommunityLevels', 'SquadCards',
            'TempVC', 'RoleManager', 'ActivityReminder', 'UpdatePublisher',
            'Confession', 'TwitchRelay', 'TitleRoles', 'BotHealth')
LABELS = {'roles': '角色權限', 'channels': '頻道設定', 'automod': 'AutoMod 設定', 'bots': '核心 Bot 角色'}


def private_destination(guild, roles, channel):
    """No Mod/Helper exception: destination must be admin-only (plus bots)."""
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        raise ValueError('提示目的地必須係本伺服器管理員專用文字頻道。')
    rows = [dict(id=str(r.id), permissions=permissions(r.permissions.value)) for r in roles]
    data = dict(overwrites=overwrite_rows(channel))
    for role in roles:
        if role.permissions.administrator or role.permissions.manage_guild or role.is_bot_managed():
            continue
        if role_permissions(rows, data, guild.id, [role.id]).view_channel:
            raise ValueError('提示頻道對非管理員角色開放；已停止送出。')
    for target, overwrite in channel.overwrites.items():
        if not isinstance(target, discord.Role) and overwrite.view_channel is True:
            raise ValueError('提示頻道有個人成員 Allow；請先人工覆核。')


def format_findings(findings):
    lines = []
    for kind, ids in findings.get('drift', {}).items():
        lines.append('{}：{} 項（ID {}{}）'.format(LABELS[kind], len(ids), '、'.join(ids[:4]), '…' if len(ids) > 4 else ''))
    lines.extend(findings.get('health', []))
    if findings.get('read_error'):
        lines.append('設定讀取未完成；目前狀態不明，請查看管理日誌。')
    return '\n'.join(lines) or '本次涵蓋項目未見差異或異常。'


class Maintenance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Store(DATA_DIR / 'maintenance.sqlite3')
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.poll.start()

    async def cog_unload(self):
        self.poll.cancel()

    async def authorize(self, interaction):
        if interaction.guild_id != config.GUILD_ID:
            return False
        member = await interaction.guild.fetch_member(interaction.user.id)
        roles = await interaction.guild.fetch_roles()
        if member.id == interaction.guild.owner_id:
            return True
        ids = set(member._roles) | {interaction.guild_id}
        mask = 0
        for role in roles:
            if role.id in ids:
                mask |= role.permissions.value
        perms = discord.Permissions(mask)
        return perms.administrator or perms.manage_guild

    async def destination(self, guild, channel_id):
        roles = await guild.fetch_roles()
        channel = await guild.fetch_channel(channel_id)
        private_destination(guild, roles, channel)
        return channel

    async def collect(self, guild):
        roles = await guild.fetch_roles()
        # Raw read preserves unsupported type 20; do not call fetch_channels().
        channels = await guild._state.http.get_all_guild_channels(guild.id)
        rules = await guild.fetch_automod_rules()
        previous = self.store.state(guild.id)['baseline']
        ids = set(previous['snapshot']['bots']) if previous else set()
        for role in roles:
            if role.is_bot_managed() and (role.name.casefold() in ('carl-bot', 'dyno', 'con9sole bartender')
                                         or (self.bot.user and role.tags.bot_id == self.bot.user.id)):
                ids.add(str(role.tags.bot_id))
        if len(ids) < 3:
            raise ValueError('未能識別三個核心 Bot，請人工覆核。')
        bots = {}
        for uid in sorted(ids):
            member = await guild.fetch_member(int(uid))
            bots[uid] = [r.id for r in member.roles]
        from utils import is_temp_vc_id
        temporary = [c['id'] for c in channels if c['type'] == 2 and is_temp_vc_id(int(c['id']))]
        return snapshot(roles, channels, [r.to_dict() for r in rules], bots, temporary)

    async def health(self, guild):
        findings = []
        for name in EXPECTED:
            cog = self.bot.get_cog(name)
            if cog is None:
                findings.append(name + '：未載入')
                continue
            loop = getattr(cog, 'voice_tick' if name == 'CommunityLevels' else 'tick', None)
            if name in ('CommunityLevels', 'SquadCards', 'TitleRoles') and (loop is None or not loop.is_running()):
                findings.append(name + '：背景循環已停止')
            if name == 'SquadCards' and getattr(cog, 'last_error', None):
                findings.append('SquadCards：有待查錯誤')
        levels = self.bot.get_cog('CommunityLevels')
        values = await asyncio.to_thread(storage_health, levels.ledger.path if levels else DATA_DIR / 'community_levels.sqlite3', guild.id)
        for label, checks in values.items():
            for key, value in checks.items():
                if key == 'status' and value != 'ok':
                    findings.append(label + '：' + str(value))
                elif key.startswith('待查') and isinstance(value, int) and value:
                    # Stable finding rather than recipient counts; no alert per new member.
                    findings.append(label + '：' + key + '需人工覆核')
                elif value == '未有資料表':
                    findings.append(label + '：' + key + '未能核對')
        return sorted(findings)

    async def check(self, guild, *, background):
        findings = {}
        try:
            async with asyncio.timeout(90):
                observed = await self.collect(guild)
                baseline = self.store.state(guild.id)['baseline']
                drift = differences(baseline['snapshot'], observed) if baseline else {}
                health = await self.health(guild)
                if drift:
                    findings['drift'] = drift
                    findings['configuration_digest'] = digest(observed)
                if health:
                    findings['health'] = health
        except Exception as exc:
            log.warning('Maintenance read incomplete guild=%s kind=%s', guild.id, type(exc).__name__)
            findings = {'read_error': True}
        fingerprint = await asyncio.to_thread(self.store.observe, guild.id, findings, background=background)
        if fingerprint:
            # Privacy is freshly validated before durable intent. Failure has no receipt
            # so a corrected destination can be checked again; never fall back publicly.
            try:
                async with asyncio.timeout(30):
                    channel = await self.destination(guild, self.store.state(guild.id)['channel'])
                    if not self.store.reserve(guild.id, fingerprint):
                        return findings
                    message = await channel.send('🛠️ 維護提示｜連續兩次檢查需覆核\n' + format_findings(findings)
                                                 + '\n用 /maintenance 核對；只提示，未自動修正或重試。',
                                                 allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
                    self.store.sent(guild.id, fingerprint, message.id)
            except Exception as exc:
                log.warning('Maintenance alert withheld/uncertain guild=%s kind=%s', guild.id, type(exc).__name__)
        return findings

    @tasks.loop(minutes=30)
    async def poll(self):
        try:
            guild = self.bot.get_guild(config.GUILD_ID)
            if guild and self.store.state(guild.id)['enabled']:
                async with self.lock:
                    await self.check(guild, background=True)
        except Exception as exc:
            log.warning('Maintenance poll failed kind=%s', type(exc).__name__)

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)  # allow existing startup reconciliation to finish

    def summary(self, guild):
        state = self.store.state(guild)
        baseline = state['baseline']
        last = state['last']
        receipts = state['receipts']
        lines = ['背景監察：' + ('已啟用（每 30 分鐘）' if state['enabled'] else '未啟用'),
                 '基準：' + ('#{}｜<t:{}:f>'.format(baseline['id'], int(baseline['stamp'])) if baseline else '未建立'),
                 '通知紀錄：已送出 {}｜結果不明 {}（不會自動重試）'.format(receipts.get('sent', 0), receipts.get('uncertain', 0))]
        if sum(receipts.values()) >= 1000:
            lines.append('通知紀錄已滿；已暫停新通知，需人工維護。')
        if last:
            detail = format_findings(last['findings'])
            if not baseline and not last['findings'].get('read_error'):
                detail = '未有基準，未能比較設定差異。\n' + detail
            lines.append('最近核對：<t:{}:f>\n{}'.format(int(last['stamp']), detail))
        else:
            lines.append('未完成首次核對；未能判斷目前狀態。')
        return '\n'.join(lines)

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='maintenance', description='管理員專用：設定基準、唯讀核對及維護提示')
    @app_commands.choices(action=[app_commands.Choice(name=n, value=v) for n, v in (
        ('狀態', 'status'), ('立即核對（不發通知）', 'check'), ('預覽新基準', 'preview'),
        ('確認新基準', 'accept'), ('啟用背景提示', 'enable'), ('停用背景提示', 'disable'))])
    @app_commands.describe(code='確認基準時填入預覽確認碼', channel='預覽基準時選擇管理員專用文字頻道')
    async def maintenance(self, interaction: discord.Interaction, action: str = 'status',
                          code: str = '', channel: discord.TextChannel | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self.authorize(interaction):
            await interaction.followup.send('只限本伺服器管理員。', ephemeral=True)
            return
        async with self.lock:
            try:
                async with asyncio.timeout(100):
                    state = self.store.state(interaction.guild_id)
                    if action == 'check':
                        await self.check(interaction.guild, background=False)
                    elif action == 'preview':
                        destination = channel.id if channel else state['channel'] or ALERT_CHANNEL
                        await self.destination(interaction.guild, destination)
                        observed = await self.collect(interaction.guild)
                        if not await self.authorize(interaction):
                            raise ValueError('管理員權限已改變。')
                        token = self.store.preview(interaction.guild_id, interaction.user.id, observed, destination)
                        drift = differences(state['baseline']['snapshot'], observed) if state['baseline'] else {}
                        text = '基準預覽｜{} 個角色、{} 個頻道、{} 條 AutoMod、{} 個核心 Bot。\n{}\n目的地：<#{}>\n確認碼：`{}`（10 分鐘內由你確認；只接受現況，未改 Discord 設定）'.format(
                            len(observed['roles']), len(observed['channels']), len(observed['automod']), len(observed['bots']),
                            format_findings({'drift': drift}) if state['baseline'] else '首次建立：請先核對既有設定及 Stage 4 驗收紀錄。', destination, token)
                        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
                        return
                    elif action == 'accept':
                        observed = await self.collect(interaction.guild)
                        # Re-read destination and authority before committing local configuration.
                        await self.destination(interaction.guild, self.store.candidate_channel(interaction.guild_id))
                        if not await self.authorize(interaction):
                            raise ValueError('管理員權限已改變。')
                        self.store.accept(interaction.guild_id, interaction.user.id, code, observed)
                    elif action in ('enable', 'disable'):
                        if action == 'enable':
                            await self.destination(interaction.guild, state['channel'])
                        if not await self.authorize(interaction):
                            raise ValueError('管理員權限已改變。')
                        self.store.enable(interaction.guild_id, action == 'enable')
                    elif action != 'status':
                        raise ValueError('未知操作。')
                    text = self.summary(interaction.guild_id)
                    if state['channel']:
                        try:
                            await self.destination(interaction.guild, state['channel'])
                            text += '\n目的地私隱核對：通過（每次通知前再核對）。'
                        except Exception:
                            text += '\n目的地私隱核對：未通過／讀取失敗；不會送出提示。'
                    await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            except (ValueError, discord.HTTPException, TimeoutError) as exc:
                text = str(exc) if isinstance(exc, ValueError) else '讀取未完成；請稍後重新核對，未自動重試。'
                await interaction.followup.send(text, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Maintenance(bot))
