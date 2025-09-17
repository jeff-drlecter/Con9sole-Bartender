from __future__ import annotations
from typing import Optional, Dict
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import emb, send_log, voice_arrow, is_temp_vc_id, set_delete_task, cancel_delete_task, track_temp_vc, untrack_temp_vc

# ---------- 權限 ----------
def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == config.VERIFIED_ROLE_ID for r in m.roles)

# ---------- 清理空房 ----------
async def schedule_delete_if_empty(channel: discord.VoiceChannel):
    async def _task():
        try:
            await asyncio.sleep(config.TEMP_VC_EMPTY_SECONDS)
            if len(channel.members) == 0 and is_temp_vc_id(channel.id):
                print(f"🧹 自動刪除空房：#{channel.name}（id={channel.id}）")
                untrack_temp_vc(channel.id)
                await channel.delete(reason="Temp VC idle timeout")
        finally:
            pass
    if len(channel.members) == 0:
        set_delete_task(channel.id, asyncio.create_task(_task()))

# ---------- Cog ----------
class TempVC(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="vc_new", description="建立一個臨時語音房（空房 120 秒自動刪除）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(name="語音房名稱（可選）", limit="人數上限（可選；不填＝無限制）")
    async def vc_new(self, inter: discord.Interaction, name: Optional[str] = None, limit: Optional[int] = None):
        if not user_can_run_tempvc(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)
        if not inter.guild:
            return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

        def _category_from_ctx_channel(ch: Optional[discord.abc.GuildChannel]) -> Optional[discord.CategoryChannel]:
            if ch is None:
                return None
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
                return ch.category
            if isinstance(ch, discord.Thread):
                parent = ch.parent
                if isinstance(parent, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel)):
                    return parent.category
            return None

        category = _category_from_ctx_channel(inter.channel)
        vc_name = f"{config.TEMP_VC_PREFIX}{(name or '臨時語音').strip()}"

        await inter.response.defer(ephemeral=False)

        max_bitrate = inter.guild.bitrate_limit
        kwargs: Dict[str, object] = {"bitrate": max_bitrate}
        if limit is not None:
            limit = max(1, min(99, int(limit)))
            kwargs["user_limit"] = limit

        ch = await inter.guild.create_voice_channel(vc_name, category=category, reason="Create temp VC (bartender)", **kwargs)
        track_temp_vc(ch.id)

        print(f"✅ 建立 Temp VC：#{ch.name}（id={ch.id}）於 {category.name if category else '根目錄'}")
        await schedule_delete_if_empty(ch)

        msg = (
            f"你好 {inter.user.mention} ，✅ 房間已經安排好 → {ch.mention}\n"
            f"（bitrate={ch.bitrate // 1000}kbps, limit={ch.user_limit or '無限制'}）"
        )
        await inter.followup.send(msg)

    @app_commands.command(name="vc_teardown", description="刪除由 Bot 建立的臨時語音房")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(channel="要刪嘅語音房（可選；唔填就刪你而家身處的 VC）")
    async def vc_teardown(self, inter: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
        if not user_can_run_tempvc(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)
        if not inter.guild:
            return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        target = channel
        if target is None and isinstance(inter.user, discord.Member) and inter.user.voice and inter.user.voice.channel:
            target = inter.user.voice.channel  # type: ignore[assignment]

        if not isinstance(target, discord.VoiceChannel):
            return await inter.followup.send("請指定或身處一個語音房。", ephemeral=True)
        if not is_temp_vc_id(target.id):
            return await inter.followup.send("呢個唔係由 Bot 建立的臨時語音房。", ephemeral=True)

        untrack_temp_vc(target.id)
        cancel_delete_task(target.id)
        print(f"🗑️ 手動刪除 Temp VC：#{target.name}（id={target.id}）")
        await target.delete(reason="Manual teardown temp VC")
        await inter.followup.send("✅ 已刪除。", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel != after.channel:
            if not before.channel and after.channel:
                await send_log(member.guild, emb("Voice Join", f"🎤 {member.mention} {voice_arrow(before.channel, after.channel)}", 0x57F287))
            elif before.channel and not after.channel:
                await send_log(member.guild, emb("Voice Leave", f"🔇 {member.mention} {voice_arrow(before.channel, after.channel)}", 0xED4245))
            else:
                await send_log(member.guild, emb("Voice Move", f"🔀 {member.mention} {voice_arrow(before.channel, after.channel)}", 0x5865F2))

        if before.channel and is_temp_vc_id(before.channel.id):
            await schedule_delete_if_empty(before.channel)
        if after.channel and is_temp_vc_id(after.channel.id):
            cancel_delete_task(after.channel.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(TempVC(bot))
