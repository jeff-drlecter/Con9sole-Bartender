from __future__ import annotations
import random
import discord
from discord import app_commands
from discord.ext import commands

import config

# ---------- 權限 ----------
def user_can_run_tu(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == config.VERIFIED_ROLE_ID for r in m.roles)

# ---------- Cog ----------
class Teams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tu", description="隨機將 @人 分成兩隊")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(members="請 @ 想參與分隊的所有人")
    async def tu_cmd(self, inter: discord.Interaction, members: str):
        if not user_can_run_tu(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)

        await inter.response.defer(ephemeral=False)

        mentions = inter.user.mention + " " + members
        user_ids = [w for w in mentions.split() if w.startswith("<@")]
        if len(user_ids) < 2:
            return await inter.followup.send("⚠️ 請至少 @ 兩位參加者！", ephemeral=True)

        random.shuffle(user_ids)
        mid = len(user_ids) // 2
        team_a = user_ids[:mid]
        team_b = user_ids[mid:]

        result = (
            "🎮 **分隊結果**：\n\n"
            "🔴 **Team A**\n" + "\n".join(team_a) + "\n\n"
            "🔵 **Team B**\n" + "\n".join(team_b)
        )
        await inter.followup.send(result)

async def setup(bot: commands.Bot):
    await bot.add_cog(Teams(bot))
