from __future__ import annotations

import logging
from typing import Union

import discord
from discord.ext import commands

import config
from features.language_preferences import ROLE_NAMES

log = logging.getLogger("con9sole-bartender.welcome")


def welcome_message(member, rules_mention: str, bot_mention: str) -> str:
    """One short welcome for this newcomer; no preference means neutral copy."""
    names = {
        r.name for r in getattr(member, "roles", [])
        if not getattr(r, "managed", True)
        and getattr(getattr(r, "permissions", None), "value", None) == 0
    }
    selected = {code for code, name in ROLE_NAMES.items() if name in names}
    code = next(iter(selected)) if len(selected) == 1 else "neutral"
    lines = {
        "hk": (
            f"📜 先睇 {rules_mention}，再去 <id:customize> 揀遊戲同身份組。",
            "🎮 搵隊友打機，或者去公海傾下其他話題。",
            f"🍸 想睇有咩功能？提及 {bot_mention}；用 /language 可隨時轉用語。",
        ),
        "tw": (
            f"📜 先看 {rules_mention}，再到 <id:customize> 選擇遊戲與身分組。",
            "🎮 找隊友一起玩，或到公海聊聊其他話題。",
            f"🍸 想查看功能？提及 {bot_mention}；隨時可用 /language 切換用語。",
        ),
        "neutral": (
            f"📜 請先閱讀 {rules_mention}，再到 <id:customize> 選擇遊戲與身份組。",
            "🎮 尋找隊友，或到公海交流其他話題。",
            f"🍸 查看功能可提及 {bot_mention}；用 /language 設定香港／台灣用語。",
        ),
    }
    return "\n".join((f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！", *lines[code]))


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

                # Fetch current onboarding roles; the join payload can precede role updates.
                try:
                    preference_member = await member.guild.fetch_member(member.id)
                except discord.NotFound:
                    return
                except discord.HTTPException:
                    preference_member = member
                message = welcome_message(preference_member, rules_mention, bot_mention)
                await channel.send(message)
        except Exception as exc:
            log.exception("Failed to send welcome message: member=%s guild=%s", member.id, member.guild.id)



async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLog(bot))
