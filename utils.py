from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional, Iterable
import asyncio
import contextlib
import discord

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
    - 出錯唔會影響主流程，只 print 提示。
    """
    if not LOG_CHANNEL_ID:
        print("[send_log] LOG_CHANNEL_ID 未設置，略過發送。")
        return

    ch = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        with contextlib.suppress(Exception):
            ch = await guild.fetch_channel(LOG_CHANNEL_ID)  # type: ignore[assignment]

    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(embed=embed)
        except Exception as e:  # pragma: no cover
            print(f"[send_log] 發送失敗：{e}")
    else:
        print(f"[send_log] 找唔到有效文字頻道：LOG_CHANNEL_ID={LOG_CHANNEL_ID}")


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
        print("   （Tag）來源沒有可用標籤，略過。")
        return

    new_tags: List[discord.ForumTag] = []
    for t in tags:
        try:
            new_tags.append(discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji))
        except Exception:
            # emoji 無法複製時，去除 emoji
            new_tags.append(discord.ForumTag(name=t.name, moderated=t.moderated))

    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    print(f"   ✅ 已複製 Forum Tags：{len(new_tags)}")


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
        print(f"🛑 取消舊的自動刪除任務：{channel_id}")
    _PENDING_DELETE_TASKS[channel_id] = task


def cancel_delete_task(channel_id: int) -> None:
    task = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if task and not task.done():
        task.cancel()
        print(f"🛑 已取消自動刪除任務：{channel_id}")


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
                print(f"🧹 自動刪除空房：#{channel.name}（id={channel.id}）")
                untrack_temp_vc(channel.id)
                await channel.delete(reason=reason)
        except asyncio.CancelledError:  # 被重設/取消
            pass
        except Exception as e:  # pragma: no cover
            print(f"[schedule_delete_if_empty] 任務錯誤：{e}")

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
        print(f"🔁 啟動追蹤 Temp VC：{len(tracked)} → {tracked[:5]}{'...' if len(tracked) > 5 else ''}")
    return tracked


def cancel_all_delete_tasks() -> None:
    """取消所有 pending 的自動刪除任務（例如關機前）。"""
    for cid, task in list(_PENDING_DELETE_TASKS.items()):
        if not task.done():
            task.cancel()
    _PENDING_DELETE_TASKS.clear()
    print("🧯 已清空所有自動刪除任務。")
