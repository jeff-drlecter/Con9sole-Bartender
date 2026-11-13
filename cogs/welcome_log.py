from __future__ import annotations

import logging
from typing import Union

import discord
from discord.ext import commands

import config

log = logging.getLogger("con9sole-bartender.welcome")


def welcome_message(member, rules_mention: str, bot_mention: str) -> str:
    """One short welcome for this newcomer; no preference means neutral copy."""
    return "\n".join((
        f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！",
        f"📜 請先閱讀 {rules_mention}，再選擇感興趣的遊戲。",
        "🎮 按下方按鈕找隊友、發起預約或設定香港／台灣用語。",
    ))


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
                from cogs.member_entry import MemberEntryView
                await channel.send(message, view=MemberEntryView())
        except Exception as exc:
            log.exception("Failed to send welcome message: member=%s guild=%s", member.id, member.guild.id)



async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLog(bot))
