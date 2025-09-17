from __future__ import annotations
import discord
from discord.ext import commands

from utils import emb, send_log

class RoleChannelEmojiLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await send_log(role.guild, emb("Role Create", f"🎭 建立角色：{role.mention}", 0x57F287))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await send_log(role.guild, emb("Role Delete", f"🗑️ 刪除角色：**{role.name}**", 0xED4245))

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.name != after.name:
            await send_log(after.guild, emb("Role Update", f"✏️ 角色改名：**{before.name}** → **{after.name}**", 0xFEE75C))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        mention = channel.mention if hasattr(channel, "mention") else f"#{channel.name}"
        await send_log(channel.guild, emb("Channel Create", f"📦 建立：{mention}", 0x57F287))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await send_log(channel.guild, emb("Channel Delete", f"🗑️ 刪除：**#{channel.name}**", 0xED4245))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.name != after.name:
            await send_log(after.guild, emb("Channel Update", f"✏️ 頻道改名：**#{before.name}** → **#{after.name}**", 0xFEE75C))

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]):
        bmap = {e.id: e for e in before}
        amap = {e.id: e for e in after}
        created = [e for e in after if e.id not in bmap]
        deleted = [e for e in before if e.id not in amap]
        renamed = [(bmap[i], amap[i]) for i in set(bmap).intersection(amap) if bmap[i].name != amap[i].name]
        if created:
            await send_log(guild, emb("Emoji Create", "😀 新增：" + ", ".join(e.name for e in created), 0x57F287))
        if deleted:
            await send_log(guild, emb("Emoji Delete", "🫥 刪除：" + ", ".join(e.name for e in deleted), 0xED4245))
        for bef, aft in renamed:
            await send_log(guild, emb("Emoji Rename", f"✏️ **{bef.name}** → **{aft.name}**", 0xFEE75C))

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleChannelEmojiLog(bot))
