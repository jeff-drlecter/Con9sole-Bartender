from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional, Iterable
import asyncio
import contextlib
import logging
import discord

log = logging.getLogger("con9sole-bartender.utils")

# 可選：如果你喺 config 入面未必有呢啲，就保持可選導入
try:  # noqa: SIM105
    from config import LOG_CHANNEL_ID  # type: ignore
except Exception:  # pragma: no cover
    LOG_CHANNEL_ID = 0  # 類型: int

# =============================
# Embed / Logging
# =============================

def emb(title: str, desc: str = "", color: int = 0x5865F2) -> discord.Embed:
    """建立通用 Embed，會自動加 UTC 時戳。"""
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.now(timezone.utc)
    return e


async def send_log(guild: discord.Guild, embed: discord.Embed) -> None:
    """把 embed 發到 LOG_CHANNEL_ID（如果設置正確）。

    - 先用 cache `guild.get_channel`，失敗再 `fetch_channel`。
    - 強制允許 **user mentions**，以確保手機/桌面都可點擊打開用戶卡。
    - 出錯唔會影響主流程，只記錄提示。
    """
    if not LOG_CHANNEL_ID:
        log.warning("LOG_CHANNEL_ID is not configured; skipping Discord audit log")
        return

    ch = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        with contextlib.suppress(Exception):
            ch = await guild.fetch_channel(LOG_CHANNEL_ID)  # type: ignore[assignment]

    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=True,  # ✅ 允許 @用戶（保證 mobile-clickable）
                    roles=False,
                    everyone=False,
                ),
            )
        except Exception:  # pragma: no cover
            log.exception("Failed to send Discord audit log to channel=%s", LOG_CHANNEL_ID)
    else:
        log.warning("Discord audit channel is unavailable: channel=%s", LOG_CHANNEL_ID)


# =============================
# 權限覆寫 Helper（文字/語音兩用）
# =============================

def make_private_overwrites(
    guild: discord.Guild,
    allow_roles: List[discord.Role],
    manage_roles: List[discord.Role],
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """建立「私有」頻道覆寫：
    - @everyone 隱藏
    - allow_roles 可見+基本互動
    - manage_roles 額外管理權限
    """
    ow: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }

    base = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        create_public_threads=True,
        create_private_threads=True,
        send_messages_in_threads=True,
        connect=True,
        speak=True,
    )
    for r in allow_roles:
        ow[r] = base

    for r in manage_roles:
        curr = ow.get(r, discord.PermissionOverwrite())
        curr.manage_channels = True
        curr.manage_messages = True
        curr.manage_threads = True
        curr.move_members = True
        curr.mute_members = True
        ow[r] = curr

    return ow


# =============================
# Forum Tags 複製
# =============================

async def copy_forum_tags(src_forum: discord.ForumChannel, dst_forum: discord.ForumChannel) -> None:
    """將來源 Forum 的可用 Tags 完整複製到目標 Forum。
    - 會嘗試複製 emoji；如果有跨伺服器自訂 emoji 失敗，會 fallback 無 emoji。
    """
    tags = src_forum.available_tags
    if not tags:
        log.info("Source forum has no tags; nothing to copy")
        return

    new_tags: List[discord.ForumTag] = []
    for t in tags:
        try:
            new_tags.append(discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji))
        except Exception:
            # emoji 無法複製時，去除 emoji
            new_tags.append(discord.ForumTag(name=t.name, moderated=t.moderated))

    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    log.info("Copied %s forum tags to channel=%s", len(new_tags), dst_forum.id)


# =============================
# Temp VC 狀態管理（in-memory）
# =============================

TEMP_VC_IDS: set[int] = set()
_PENDING_DELETE_TASKS: dict[int, asyncio.Task] = {}


def is_temp_vc_id(cid: int) -> bool:
    return cid in TEMP_VC_IDS


def track_temp_vc(channel_id: int) -> None:
    TEMP_VC_IDS.add(channel_id)


def untrack_temp_vc(channel_id: int) -> None:
    TEMP_VC_IDS.discard(channel_id)


def set_delete_task(channel_id: int, task: asyncio.Task) -> None:
    old = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if old and not old.done():
        old.cancel()
        log.debug("Cancelled previous temp VC deletion task: channel=%s", channel_id)
    _PENDING_DELETE_TASKS[channel_id] = task


def cancel_delete_task(channel_id: int) -> None:
    task = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if task and not task.done():
        task.cancel()
        log.debug("Cancelled temp VC deletion task: channel=%s", channel_id)


def clear_delete_task(channel_id: int, task: asyncio.Task | None = None) -> None:
    """Forget a completed task without cancelling it or a newer replacement."""
    tracked = _PENDING_DELETE_TASKS.get(channel_id)
    if tracked is not None and (task is None or tracked is task):
        _PENDING_DELETE_TASKS.pop(channel_id, None)


async def schedule_delete_if_empty(
    channel: discord.VoiceChannel,
    *,
    idle_seconds: int,
    reason: str = "Temp VC idle timeout",
) -> None:
    """如房間在 `idle_seconds` 內持續無人，便自動刪除。
    - 會自動覆蓋（重設）同一 channel 的舊計時任務。
    - 只會刪除被 `track_temp_vc` 記錄過的 VC。
    """

    async def _task() -> None:
        try:
            await asyncio.sleep(idle_seconds)
            if len(channel.members) == 0 and is_temp_vc_id(channel.id):
                log.info("Deleting empty temp VC: channel=%s name=%s", channel.id, channel.name)
                untrack_temp_vc(channel.id)
                await channel.delete(reason=reason)
        except asyncio.CancelledError:  # 被重設/取消
            pass
        except Exception:  # pragma: no cover
            log.exception("Temp VC deletion task failed: channel=%s", channel.id)
        finally:
            clear_delete_task(channel.id, asyncio.current_task())

    if len(channel.members) == 0:
        set_delete_task(channel.id, asyncio.create_task(_task()))


# =============================
# 啟動補償 / 清理工具
# =============================

async def bootstrap_track_temp_vcs(
    guild: discord.Guild,
    *,
    name_prefixes: Iterable[str],
) -> List[int]:
    """Bot 重啟後，掃描現有語音房，以名稱前綴重建 TEMP_VC_IDS。
    會返回被追蹤的 channel id 清單。
    """
    tracked: List[int] = []
    prefixes = tuple(name_prefixes)
    for ch in guild.voice_channels:
        try:
            if ch.name.startswith(prefixes):
                track_temp_vc(ch.id)
                tracked.append(ch.id)
        except Exception:  # 極端情況：名稱是 None
            continue
    if tracked:
        log.info("Restored tracking for %s temp VCs: sample=%s", len(tracked), tracked[:5])
    return tracked


def cancel_all_delete_tasks() -> None:
    """取消所有 pending 的自動刪除任務（例如關機前）。"""
    for cid, task in list(_PENDING_DELETE_TASKS.items()):
        if not task.done():
            task.cancel()
    _PENDING_DELETE_TASKS.clear()
    log.info("Cancelled all pending temp VC deletion tasks")


# --------- Helpers ---------
from typing import Optional

def voice_arrow(before: Optional[discord.abc.GuildChannel],
                after: Optional[discord.abc.GuildChannel]) -> str:
    """把頻道變化格式化為 A → B；允許 None。"""
    def _name(ch: Optional[discord.abc.GuildChannel]) -> str:
        if ch is None:
            return "（無）"
        # Threads 可能沒有 name，用 parent 名稱後綴 thread
        name = getattr(ch, "name", None)
        if name is None and hasattr(ch, "parent") and getattr(ch, "parent", None):
            parent = getattr(ch, "parent")
            name = f"{getattr(parent, 'name', '未知')}/thread"
        return f"#{name}" if name and not str(name).startswith("#") else (name or "#未知")
    return f"{_name(before)} → {_name(after)}"


def role_mention_safe(role: discord.Role, allow_ping: bool = False) -> str:
    """
    以「不觸發 ping」的方式顯示角色。
    allow_ping=True 時回傳 role.mention；否則回傳 `@角色名`（行內程式碼樣式）。
    """
    return role.mention if allow_ping else f"`@{role.name}`"
