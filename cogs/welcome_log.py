from __future__ import annotations

import logging
from typing import Union

import discord
from discord.ext import commands

import config

log = logging.getLogger("con9sole-bartender.welcome")


def welcome_message(member, rules_mention: str, bot_mention: str) -> str:
    """Explain what the newcomer can already do and what the button grants."""
    return "\n".join((
        f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！",
        f"📜 喺 Discord 確認 {rules_mention} 嘅入群守則後，就可以同大家打招呼、搵隊友。",
        "你可以喺任何人嘅歡迎訊息撳「我是人類」，為自己領取 Verified 身份，解鎖完整會員功能。",
        "如果按鈕沒有回應，請等約 10 秒再試一次。仍然無法驗證的話，可以在本頻道找 Helper 幫忙。",
        "想揀遊戲或開主選單，可以用下面嘅按鈕。有問題就按「搵 Helper」。",
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
            if member.bot or member.guild.id != config.GUILD_ID:
                return
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if isinstance(channel, discord.TextChannel):
                rules_channel = member.guild.get_channel(config.RULES_CHANNEL_ID)
                rules_mention = (
                    rules_channel.mention
                    if isinstance(rules_channel, discord.TextChannel)
                    else f"<#{config.RULES_CHANNEL_ID}>"
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
                await channel.send(message, view=MemberEntryView(welcome=True),
                                   allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            log.exception("Failed to send welcome message: member=%s guild=%s", member.id, member.guild.id)



async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLog(bot))
