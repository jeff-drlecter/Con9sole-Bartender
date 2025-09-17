from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional
import asyncio
import discord

from config import LOG_CHANNEL_ID

# ---------- 共用 Helper ----------

def make_private_overwrites(
    guild: discord.Guild, allow_roles: List[discord.Role], manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for r in allow_roles:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            create_public_threads=True, create_private_threads=True, send_messages_in_threads=True,
            connect=True, speak=True
        )
    for r in manage_roles:
        curr = ow.get(r, discord.PermissionOverwrite())
        curr.manage_channels = True
        curr.manage_messages = True
        curr.manage_threads = True
        curr.move_members = True
        curr.mute_members = True
        ow[r] = curr
    return ow

async def copy_forum_tags(src_forum: discord.ForumChannel, dst_forum: discord.ForumChannel):
    tags = src_forum.available_tags
    if not tags:
        print("   （Tag）模板 Forum 無可用標籤，略過。")
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    print(f"   ✅ 已複製 Forum Tags：{len(new_tags)}")

# ---------- Embeds / Logging ----------

def emb(title: str, desc: str = "", color: int = 0x5865F2) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.now(timezone.utc)
    return e

async def send_log(guild: discord.Guild, embed: discord.Embed):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if isinstance(ch, discord.TextChannel):
        await ch.send(embed=embed)

# ---------- Tiny helpers ----------

def role_mention_safe(role: discord.Role) -> str:
    try:
        return role.mention
    except Exception:
        return f"@{getattr(role, 'name', '（未知角色）')}"

def voice_arrow(before: Optional[discord.VoiceChannel], after: Optional[discord.VoiceChannel]) -> str:
    if before and after and before.id != after.id:
        return f"{before.mention} → {after.mention}"
    if after and not before:
        return f"加入 {after.mention}"
    if before and not after:
        return f"離開 {before.mention}"
    return "（狀態未變）"

# ---------- Temp VC book-keeping (shared) ----------
TEMP_VC_IDS: set[int] = set()
_PENDING_DELETE_TASKS: dict[int, asyncio.Task] = {}

def is_temp_vc_id(cid: int) -> bool:
    return cid in TEMP_VC_IDS

def cancel_delete_task(channel_id: int):
    task = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if task and not task.done():
        task.cancel()

def track_temp_vc(channel_id: int):
    TEMP_VC_IDS.add(channel_id)

def untrack_temp_vc(channel_id: int):
    TEMP_VC_IDS.discard(channel_id)

def set_delete_task(channel_id: int, task: asyncio.Task):
    old = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if old and not old.done():
        old.cancel()
    _PENDING_DELETE_TASKS[channel_id] = task
