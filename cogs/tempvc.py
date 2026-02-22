from __future__ import annotations

from typing import Optional, Dict, Union, Iterable
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import (
    emb, send_log, voice_arrow,
    is_temp_vc_id, set_delete_task, cancel_delete_task,
    track_temp_vc, untrack_temp_vc, bootstrap_track_temp_vcs,
)

# ============================================================
# Temp VC Manager
# - 120s empty => auto delete
# - resilient to discord.py member cache timing
# - resilient to bot restarts (bootstrap + sweeper)
# ============================================================


# ---------- Mention helper (mobile/desktop clickable) ----------
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


# ---------- 權限 ----------
def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == config.VERIFIED_ROLE_ID for r in m.roles)


def _get_timeout_seconds() -> float:
    try:
        return float(getattr(config, "TEMP_VC_EMPTY_SECONDS", 120))
    except Exception:
        return 120.0


def _get_sweep_interval_seconds() -> float:
    """
    safety sweeper interval (seconds)
    - 預設 300s（5分鐘）
    - 你可喺 config.py 加 TEMP_VC_SWEEP_SECONDS 來改
    - 設為 0 或負數會關掉 sweeper
    """
    try:
        return float(getattr(config, "TEMP_VC_SWEEP_SECONDS", 300))
    except Exception:
        return 300.0


def _get_name_prefixes() -> list[str]:
    # 你 utils.bootstrap_track_temp_vcs 似乎係用 prefix 去找回 temp vc
    return [getattr(config, "TEMP_VC_PREFIX", "")]


# ---------- 清理空房（修正版：避免 members cache 時序問題） ----------
async def schedule_delete_if_empty(channel: discord.VoiceChannel, *, force: bool = False):
    """
    - force=False：只喺「目前已空」先起倒數（避免無謂 task）
    - force=True：用於 voice_state_update / bootstrap / sweeper — 不信當刻 members cache，直接起倒數，
                  timeout 後用 fresh channel 再判斷是否仍然空房
    """
    timeout = _get_timeout_seconds()
    ch_id = channel.id

    # 保守：只處理 temp VC
    if not is_temp_vc_id(ch_id):
        return

    # 非強制模式：真係空房先 schedule；唔空就順手 cancel 舊 task
    if not force:
        if len(channel.members) > 0:
            cancel_delete_task(ch_id)
            return

    async def _task():
        try:
            print(f"⏳ Temp VC 倒數開始（{timeout:.0f}s）：#{channel.name} id={ch_id}")
            await asyncio.sleep(timeout)

            guild = channel.guild

            # 用 fresh object 做最終判斷（避免 stale cache）
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

            if (
                isinstance(fresh, discord.VoiceChannel)
                and len(fresh.members) == 0
                and is_temp_vc_id(ch_id)
            ):
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
            print(f"🛑 倒數已取消（有人進入/房間不再空）id={ch_id}")
            raise
        except Exception as e:
            print(f"⚠️ 倒數 task 發生例外 id={ch_id}：{e!r}")
        finally:
            cancel_delete_task(ch_id)

    # 保證每個 VC 同一時間只有 1 個 task
    cancel_delete_task(ch_id)
    set_delete_task(ch_id, asyncio.create_task(_task()))


# ---------- Cog ----------
class TempVC(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bootstrapped = False  # 防止多次 on_ready
        self._sweeper_task: Optional[asyncio.Task] = None

    def cog_unload(self):
        # cog 被 unload 時確保 sweeper 停止
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if self._bootstrapped:
            return
        self._bootstrapped = True

        # 1) Bootstrap：重啟後找回 temp VC（非常重要）
        for g in self.bot.guilds:
            try:
                ids = await bootstrap_track_temp_vcs(g, name_prefixes=_get_name_prefixes())

                for cid in ids:
                    ch = g.get_channel(cid)

                    # cache 攞唔到先 fetch（低 API call）
                    if ch is None:
                        try:
                            ch = await g.fetch_channel(cid)
                        except discord.NotFound:
                            continue
                        except Exception as e:
                            print(f"[TempVC bootstrap] fetch_channel 失敗 cid={cid}：{e!r}")
                            continue

                    # ✅ 關鍵修正：boot 時一律 force=True
                    # 原因：重啟後 members cache 經常唔準，會令「空房但以為有人」而漏 schedule
                    if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id):
                        await schedule_delete_if_empty(ch, force=True)

            except Exception as e:
                print(f"[TempVC bootstrap] {g.name} 失敗：{e!r}")

        # 2) Safety Sweeper（超輕量）
        # - 防止 voice_state_update 漏事件、斷線、restart timing 等 edge cases
        # - 每次 sweep：只會對「空房」的 temp VC 起倒數（force=True），唔會狂打 API
        interval = _get_sweep_interval_seconds()
        if interval > 0:
            self._sweeper_task = asyncio.create_task(self._sweeper_loop(interval))
            print(f"[TempVC] safety sweeper started (interval={interval:.0f}s)")
        else:
            print("[TempVC] safety sweeper disabled (TEMP_VC_SWEEP_SECONDS <= 0)")

    async def _sweeper_loop(self, interval: float):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(interval)

                for g in self.bot.guilds:
                    try:
                        ids = await bootstrap_track_temp_vcs(g, name_prefixes=_get_name_prefixes())
                        # 注意：bootstrap_track_temp_vcs 應該係「同步 track list」，
                        # 但我哋用佢返回 ids 來做 sweep，保持一致性。

                        for cid in ids:
                            ch = g.get_channel(cid)
                            if ch is None:
                                # 盡量少 fetch：只有 cache 無先 fetch
                                try:
                                    ch = await g.fetch_channel(cid)
                                except discord.NotFound:
                                    continue
                                except Exception:
                                    continue

                            if isinstance(ch, discord.VoiceChannel) and is_temp_vc_id(ch.id):
                                # 只對「看起來空」先 schedule（慳 task），但仍 force=True 以防 cache 錯
                                if len(ch.members) == 0:
                                    await schedule_delete_if_empty(ch, force=True)

                    except Exception as e:
                        print(f"[TempVC sweeper] {g.name} sweep 失敗：{e!r}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TempVC sweeper] loop exception: {e!r}")

    # 事件監聽：誰入誰走
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # log join/leave/move
        if before.channel != after.channel:
            mtxt = await mention_or_id(member.guild, member)
            if not before.channel and after.channel:
                await send_log(
                    member.guild,
                    emb("Voice Join", f"🎤 {mtxt} {voice_arrow(before.channel, after.channel)}", 0x57F287),
                )
            elif before.channel and not after.channel:
                await send_log(
                    member.guild,
                    emb("Voice Leave", f"🔇 {mtxt} {voice_arrow(before.channel, after.channel)}", 0xED4245),
                )
            else:
                await send_log(
                    member.guild,
                    emb("Voice Move", f"🔀 {mtxt} {voice_arrow(before.channel, after.channel)}", 0x5865F2),
                )

        # 離開 temp VC：用 force=True，避免 members cache 未更新而漏 schedule
        if before.channel and is_temp_vc_id(before.channel.id):
            await schedule_delete_if_empty(before.channel, force=True)

        # 進入 temp VC：一定 cancel（因為唔應該刪）
        if after.channel and is_temp_vc_id(after.channel.id):
            cancel_delete_task(after.channel.id)

    @app_commands.command(name="vc_new", description="建立一個臨時語音房（空房 120 秒自動刪除）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(name="語音房名稱（可選）", limit="人數上限（可選；不填＝無限制）")
    async def vc_new(self, inter: discord.Interaction, name: Optional[str] = None, limit: Optional[int] = None):
        if not user_can_run_tempvc(inter):
            return await inter.response.send_message("你未有使用權限。", ephemeral=True)
        if not inter.guild:
            return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

        def _category_from_ctx_channel(
            ch: Optional[discord.abc.GuildChannel],
        ) -> Optional[discord.CategoryChannel]:
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

        ch = await inter.guild.create_voice_channel(
            vc_name,
            category=category,
            reason="Create temp VC (bartender)",
            **kwargs,
        )
        track_temp_vc(ch.id)

        print(f"✅ 建立 Temp VC：#{ch.name}（id={ch.id}）於 {category.name if category else '根目錄'}")

        # 新建房：只喺「已空」先 schedule（避免無謂 task）
        await schedule_delete_if_empty(ch, force=False)

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


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVC(bot))
