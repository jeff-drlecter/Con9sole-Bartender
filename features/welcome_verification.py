"""One self-grant per member, including across rejoins and process restarts."""
import asyncio
import sqlite3
from weakref import WeakValueDictionary

import discord

import config
from core.sqlite_storage import connect_sqlite
from core.storage_paths import STATS_DB

VERIFY_BUTTON = 'entry:verify:v1'
APPROVED_ROLE_ID = 1279040517451022419
REVIEW = '請搵 Helper 覆核你嘅會員驗證。'
UNAVAILABLE = '暫時確認唔到驗證設定或權限，請搵 Helper。'
RULES = '請先完成 Discord 入群守則確認，再按「我是活人」。'
# Treat future/unknown bits as unsafe by default, including channel overwrites.
MEMBER_PERMISSIONS = discord.Permissions(
    view_channel=True, read_message_history=True, send_messages=True,
    add_reactions=True, embed_links=True, attach_files=True, external_emojis=True, send_tts_messages=True,
    external_stickers=True, send_messages_in_threads=True, create_public_threads=True,
    create_private_threads=True, use_application_commands=True, use_embedded_activities=True,
    connect=True, speak=True, stream=True, use_voice_activation=True, request_to_speak=True,
    use_soundboard=True, use_external_sounds=True, send_voice_messages=True, send_polls=True,
    use_external_apps=True, change_nickname=True, create_instant_invite=True, bypass_slowmode=True,
)


class CheckFailed(Exception):
    """A private, member-facing outcome without operational details."""


def remember(member_id):
    """Commit before any role write. A crash or uncertain result requires staff review."""
    with connect_sqlite(STATS_DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS welcome_verification_used '
                   '(member_id INTEGER PRIMARY KEY)')
        return db.execute('INSERT OR IGNORE INTO welcome_verification_used VALUES (?)',
                          (member_id,)).rowcount == 1


def staff_role(role):
    return (role.id in {*config.HELPER_ROLE_IDS, *config.ADMIN_ROLE_IDS, config.MOD_ROLE_ID}
            or role.name.strip().casefold() in {n.strip().casefold() for n in config.HELPER_ROLE_NAMES})


def staff_member(member):
    p = member.guild_permissions
    return (p.administrator or p.manage_guild or p.manage_roles or p.moderate_members
            or p.ban_members or p.kick_members or p.manage_channels or p.manage_messages
            or any(staff_role(role) for role in member.roles))


async def screening_member(guild, member_id):
    # discord.py Member.pending defaults to False when Discord omits the field.
    # Only an explicit REST value can authorize this role grant.
    data = await guild._state.http.get_member(guild.id, member_id)
    if data.get('pending') is not False or type(data.get('flags')) is not int:
        raise CheckFailed(RULES)
    member = discord.Member(data=data, guild=guild, state=guild._state)
    if member.id != member_id or member.bot or member.flags.bypasses_verification:
        raise CheckFailed(RULES)
    return member


def safe_role(guild):
    role = guild.get_role(config.VERIFIED_ROLE_ID)
    if (not role or role.id != APPROVED_ROLE_ID or role.guild.id != config.GUILD_ID
            or role.is_default() or role.managed or staff_role(role)
            or role.permissions.value & ~MEMBER_PERMISSIONS.value):
        raise CheckFailed(UNAVAILABLE)
    return role


def require_resolved_roles(member):
    # Member.roles silently skips IDs absent from its guild snapshot. A role
    # created between REST requests must not disappear from a hierarchy check.
    if not member.guild.default_role or any(member.guild.get_role(r) is None for r in member._roles):
        raise CheckFailed(UNAVAILABLE)


class WelcomeVerification:
    def __init__(self):
        self.locks = WeakValueDictionary()

    async def respond(self, interaction, target_id=None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if (interaction.guild_id != config.GUILD_ID or not interaction.guild
                    or interaction.guild.id != config.GUILD_ID or interaction.user.bot):
                raise CheckFailed(UNAVAILABLE)
            member_id = interaction.user.id if target_id is None else target_id
            async with self.locks.setdefault(member_id, asyncio.Lock()):
                content = await self.change(interaction, target_id)
        except CheckFailed as exc:
            content = str(exc)
        except (discord.DiscordException, OSError, sqlite3.Error, KeyError, ValueError, TypeError):
            content = UNAVAILABLE
        await interaction.edit_original_response(content=content, allowed_mentions=discord.AllowedMentions.none())

    async def change(self, interaction, target_id):
        grant = target_id is None
        if grant and (interaction.channel_id != config.WELCOME_CHANNEL_ID or not interaction.message):
            raise CheckFailed('請喺自己嘅歡迎訊息使用呢個按鈕。')
        guild = await interaction.client.fetch_guild(config.GUILD_ID, with_counts=False)
        if guild.id != config.GUILD_ID or not guild.owner_id or guild.unavailable:
            raise CheckFailed(UNAVAILABLE)
        if grant and 'MEMBER_VERIFICATION_GATE_ENABLED' not in guild.features:
            raise CheckFailed('社群嘅入群守則確認暫時未能使用，請搵 Helper。')

        # The REST guild already contains fresh roles. Channels and members fetched
        # from this object therefore also resolve permissions against those roles.
        role = safe_role(guild)
        channel = await guild.fetch_channel(interaction.channel_id)
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id
                or channel.id != interaction.channel_id):
            raise CheckFailed('請喺你睇到嘅社群文字頻道使用。')

        if grant:
            message = await channel.fetch_message(interaction.message.id)
            ids = {getattr(item, 'custom_id', None) for row in message.components for item in row.children}
            if (message.author.id != interaction.client.user.id or message.webhook_id is not None
                    or VERIFY_BUTTON not in ids
                    or not message.content.startswith(f'🎉 歡迎 <@{interaction.user.id}> 加入 **')):
                raise CheckFailed('請喺自己今次入群嘅歡迎訊息使用呢個按鈕。')
            channels = await guild.fetch_channels()
            if not any(c.id == channel.id for c in channels):
                raise CheckFailed(UNAVAILABLE)
            # PermissionOverwrite.from_pair drops bits unknown to discord.py.
            # Inspect the REST bitfield so new moderation powers fail closed.
            if any(c.guild.id != guild.id or any(
                    ow.is_role() and ow.id == role.id and ow.allow & ~MEMBER_PERMISSIONS.value
                    for ow in c._overwrites) for c in channels):
                raise CheckFailed(UNAVAILABLE)

        bot = await guild.fetch_member(interaction.client.user.id)
        require_resolved_roles(bot)
        if (bot.id != interaction.client.user.id or not bot.bot or not bot.guild_permissions.manage_roles
                or role >= bot.top_role):
            raise CheckFailed(UNAVAILABLE)
        if grant:
            actor = await screening_member(guild, interaction.user.id)
        else:
            actor = await guild.fetch_member(interaction.user.id)
        require_resolved_roles(actor)
        if actor.id != interaction.user.id or actor.bot or actor.pending or actor.is_timed_out():
            raise CheckFailed(UNAVAILABLE)
        p = channel.permissions_for(actor)
        if not p.view_channel or not p.read_message_history:
            raise CheckFailed(UNAVAILABLE)

        if grant:
            target = actor
            if not target.joined_at or message.created_at < target.joined_at:
                raise CheckFailed('請喺自己今次入群嘅歡迎訊息使用呢個按鈕。')
            if role in target.roles:
                await asyncio.to_thread(remember, target.id)
                return '你已經有會員驗證，可以使用完整會員功能。'
        else:
            helper_roles = [r for r in actor.roles if r.id in config.HELPER_ROLE_IDS]
            admin = actor.guild_permissions.administrator or actor.guild_permissions.manage_guild
            if not (admin or helper_roles):
                raise CheckFailed('只限社群 Helper 或管理員撤回會員驗證。')
            target = await guild.fetch_member(target_id)
            require_resolved_roles(target)
            authority = actor.top_role if admin else max(helper_roles)
            if (target.id != target_id or target.bot or target.id in {guild.owner_id, actor.id}
                    or staff_member(target) or (actor.id != guild.owner_id and
                        any(r >= authority for r in target.roles if r != role))):
                raise CheckFailed('呢個成員唔適用於 Helper 撤回驗證。')

        if target.id == guild.owner_id or target.top_role >= bot.top_role:
            raise CheckFailed(UNAVAILABLE)
        if grant:
            if not await asyncio.to_thread(remember, target.id):
                raise CheckFailed(REVIEW)
            await target.add_roles(role, reason='Member accepted welcome self-verification', atomic=True)
            return '已完成會員驗證，你可以使用完整會員功能。'

        # Persist the hold even if the role was already manually removed or the
        # subsequent Discord response is lost. Staff can still restore it natively.
        await asyncio.to_thread(remember, target.id)
        if role in target.roles:
            await target.remove_roles(role, reason=f'Welcome verification revoked by {actor.id}', atomic=True)
        return '已停用呢位成員嘅自行驗證，並已撤回會員驗證身份組。'
