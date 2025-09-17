from __future__ import annotations
import discord
from discord.ext import commands

import config
from utils import emb, send_log, role_mention_safe

class WelcomeLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if isinstance(channel, discord.TextChannel):
                rules_ch = member.guild.get_channel(config.RULES_CHANNEL_ID)
                guide_ch = member.guild.get_channel(config.GUIDE_CHANNEL_ID)
                support_ch = member.guild.get_channel(config.SUPPORT_CHANNEL_ID)

                msg = (
                    f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！\n\n"
                    f"📜 請先細心閱讀 {rules_ch.mention if isinstance(rules_ch, discord.TextChannel) else '#rules'}\n"
                    f"📝 組別分派會根據你揀嘅答案，如需更改請查看 {guide_ch.mention if isinstance(guide_ch, discord.TextChannel) else '#教學'}\n"
                    f"💬 如果有任何疑問，請到 {support_ch.mention if isinstance(support_ch, discord.TextChannel) else '#支援'} 講聲 **hi**，會有專人協助你。\n\n"
                    f"最後 🙌 喺呢度同大家打一聲招呼啦！\n👉 你想我哋點稱呼你？"
                )
                await channel.send(msg)
        except Exception:
            pass

        await send_log(member.guild, emb("Member Join", f"👋 {member.mention} 加入伺服器。", 0x57F287))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await send_log(member.guild, emb("Member Leave", f"👋 {member.mention} 離開伺服器。", 0xED4245))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            desc = (
                f"🪪 {after.mention} 暱稱變更：\n"
                f"**Before**：{before.nick or '（無）'}\n**After**：{after.nick or '（無）'}"
            )
            await send_log(after.guild, emb("Nickname Change", desc, 0x5865F2))

        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        added_roles = [r for r in after.roles if r.id not in before_ids and r.name != "@everyone"]
        removed_roles = [r for r in before.roles if r.id not in after_ids and r.name != "@everyone"]

        if added_roles:
            txt = "➕ " + after.mention + " 新增角色： " + ", ".join(role_mention_safe(r) for r in added_roles)
            await send_log(after.guild, emb("Member Role Add", txt, 0x57F287))
        if removed_roles:
            txt = "➖ " + after.mention + " 移除角色： " + ", ".join(role_mention_safe(r) for r in removed_roles)
            await send_log(after.guild, emb("Member Role Remove", txt, 0xED4245))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await send_log(guild, emb("Member Ban", f"🔨 封鎖：{user.mention}", 0xED4245))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await send_log(guild, emb("Member Unban", f"🕊️ 解除封鎖：{user.mention}", 0x57F287))

async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLog(bot))
