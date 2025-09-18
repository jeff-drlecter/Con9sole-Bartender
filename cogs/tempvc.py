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

# ---------- 清理空房（強化版） ----------
async def schedule_delete_if_empty(channel: discord.VoiceChannel):
    """如果房間目前冇人，就開始倒數刪除；有人再入就會被 on_voice_state_update 取消。"""
    try:
        timeout = float(getattr(config, "TEMP_VC_EMPTY_SECONDS", 120))
    except Exception:
        timeout = 120.0

    # 只在「而家」係空先開新倒數
    if len(channel.members) > 0:
        return

    ch_id = channel.id

    async def _task():
        try:
            print(f"⏳ Temp VC 倒數開始（{timeout:.0f}s）：#{channel.name} id={ch_id}")
            await asyncio.sleep(timeout)

            # 倒數完先重新 fetch，避免用舊 cache
            guild = channel.guild
            fresh = guild.get_channel(ch_id)
            if fresh is None:
                try:
                    fresh = await guild.fetch_channel(ch_id)
                except discord.NotFound:
                    print(f"🧹 目標已不存在（可能已手動刪）：id={ch_id}")
                    return
                except Exception as e:
                    print(f"⚠️ 取 channel 失敗 id={ch_id}：{e!r}")
                    return

            # 最後檢查一次真係無人同埋係 temp VC 先刪
            if isinstance(fresh, discord.VoiceChannel) and len(fresh.members) == 0 and is_temp_vc_id(ch_id):
                print(f"🧹 自動刪除空房：#{fresh.name}（id={ch_id}）")
                untrack_temp_vc(ch_id)
                try:
                    await fresh.delete(reason="Temp VC idle timeout")
                except discord.Forbidden:
                    print("❌ 沒有權限刪除語音房（請檢查 Bot 角色是否有『管理頻道』）。")
                except Exception as e:
                    print(f"❌ 刪除語音房失敗：{e!r}")
            else:
                print(f"🚫 取消刪除：房間有人或已不是 temp（id={ch_id}）")
        except asyncio.CancelledError:
            print(f"🛑 倒數已取消（有人進入？）id={ch_id}")
            raise
        except Exception as e:
            print(f"⚠️ 倒數 task 發生例外 id={ch_id}：{e!r}")
        finally:
            # 任務完成/取消都要把紀錄清走
            cancel_delete_task(ch_id)

    # 若已存在舊倒數，先取消再設置（避免重覆）
    cancel_delete_task(ch_id)
    set_delete_task(ch_id, asyncio.create_task(_task()))


# ---------- 事件監聽：誰入誰走 ----------
@commands.Cog.listener()
async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # 你的 log 保留
    if before.channel != after.channel:
        if not before.channel and after.channel:
            await send_log(member.guild, emb("Voice Join", f"🎤 {member.mention} {voice_arrow(before.channel, after.channel)}", 0x57F287))
        elif before.channel and not after.channel:
            await send_log(member.guild, emb("Voice Leave", f"🔇 {member.mention} {voice_arrow(before.channel, after.channel)}", 0xED4245))
        else:
            await send_log(member.guild, emb("Voice Move", f"🔀 {member.mention} {voice_arrow(before.channel, after.channel)}", 0x5865F2))

    # 有人離開一個 temp 房：如果變到 0 人，就開始倒數
    if before.channel and is_temp_vc_id(before.channel.id):
        if len(before.channel.members) == 0:
            await schedule_delete_if_empty(before.channel)

    # 有人加入一個 temp 房：取消倒數
    if after.channel and is_temp_vc_id(after.channel.id):
        cancel_delete_task(after.channel.id)

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
