from __future__ import annotations

import logging
from typing import Union

import discord
from discord.ext import commands

import config
from utils import emb, role_mention_safe, send_log

log = logging.getLogger("con9sole-bartender.welcome")


async def mention_or_id(
    guild: discord.Guild,
    user_or_id: Union[int, discord.abc.User, discord.Member, None],
) -> str:
    if user_or_id is None:
        return "（未知成員）"
    if isinstance(user_or_id, discord.Member):
        return user_or_id.mention
    if isinstance(user_or_id, discord.User):
        uid = user_or_id.id
    elif isinstance(user_or_id, int):
        uid = user_or_id
    else:
        return f"User ID: {getattr(user_or_id, 'id', '未知')}"

    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except (discord.NotFound, discord.HTTPException):
            member = None
    return member.mention if member else f"User ID: {uid}"


class WelcomeLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if isinstance(channel, discord.TextChannel):
                rules_channel = member.guild.get_channel(config.RULES_CHANNEL_ID)
                rules_mention = (
                    rules_channel.mention
                    if isinstance(rules_channel, discord.TextChannel)
                    else "#rules"
                )
                bot_mention = self.bot.user.mention if self.bot.user else "@Con9sole-Bartender"

                message = (
                    f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！\n\n"
                    f"📜 請先前往 {rules_mention} 閱讀伺服器規則，了解基本守則及使用方式。\n\n"
                    "🎭 如想尋找遊戲專區、加入相關身份組，或瀏覽遊戲以外的公海話題，"
                    "可前往 <id:customize> 選擇合適的身份。\n\n"
                    "🌊 除了遊戲內容外，也歡迎在公海集中討論區開設新帖，"
                    "分享寵物、飲食、音樂、電影等不同話題。\n\n"
                    f"🍸 如不確定應從哪裏開始，或想查看伺服器功能，可直接提及 {bot_mention}。"
                )
                await channel.send(message)
        except Exception as exc:
            log.exception("Failed to send welcome message: member=%s guild=%s", member.id, member.guild.id)

        member_text = await mention_or_id(member.guild, member)
        await send_log(member.guild, emb("Member Join", f"👋 {member_text} 加入伺服器。", 0x57F287))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        member_text = await mention_or_id(member.guild, member)
        await send_log(member.guild, emb("Member Leave", f"👋 {member_text} 離開伺服器。", 0xED4245))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            member_text = await mention_or_id(after.guild, after)
            description = (
                f"🪪 {member_text} 暱稱變更：\n"
                f"**Before**：{before.nick or '（無）'}\n"
                f"**After**：{after.nick or '（無）'}"
            )
            await send_log(after.guild, emb("Nickname Change", description, 0x5865F2))

        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}
        added_roles = [
            role for role in after.roles
            if role.id not in before_ids and role.name != "@everyone"
        ]
        removed_roles = [
            role for role in before.roles
            if role.id not in after_ids and role.name != "@everyone"
        ]

        if added_roles:
            member_text = await mention_or_id(after.guild, after)
            text = "➕ " + member_text + " 新增角色： " + ", ".join(
                role_mention_safe(role) for role in added_roles
            )
            await send_log(after.guild, emb("Member Role Add", text, 0x57F287))

        if removed_roles:
            member_text = await mention_or_id(after.guild, after)
            text = "➖ " + member_text + " 移除角色： " + ", ".join(
                role_mention_safe(role) for role in removed_roles
            )
            await send_log(after.guild, emb("Member Role Remove", text, 0xED4245))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        member_text = await mention_or_id(guild, user)
        await send_log(guild, emb("Member Ban", f"🔨 封鎖：{member_text}", 0xED4245))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        member_text = await mention_or_id(guild, user)
        await send_log(guild, emb("Member Unban", f"🕊️ 解除封鎖：{member_text}", 0x57F287))


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLog(bot))
