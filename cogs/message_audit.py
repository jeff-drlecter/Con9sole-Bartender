from __future__ import annotations
from typing import List, Optional, Union, Dict, Any
import json
import os
import sqlite3
from collections import OrderedDict

import discord
from discord.ext import commands

from utils import emb, send_log

# -----------------------------
# Utilities
# -----------------------------

def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _attachments_payload(message: discord.Message) -> Dict[str, Any]:
    return {
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "url": a.url,
                "content_type": a.content_type,
                "size": a.size,
            }
            for a in message.attachments
        ],
        "embeds": [e.to_dict() for e in message.embeds] if message.embeds else [],
        "stickers": [s.to_dict() for s in message.stickers] if message.stickers else [],
    }


async def mention_or_id(
    guild: discord.Guild,
    user_or_id: Union[int, discord.abc.User, discord.Member, None],
) -> str:
    """Return a **real mention** for members (clickable on mobile/desktop).
    Fallback to plain ID text if the user isn't in the guild anymore.
    """
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


# -----------------------------
# LRU Message Cache (memory)
# -----------------------------

class LRUCache(OrderedDict):
    def __init__(self, maxsize: int = 5000):
        super().__init__()
        self.maxsize = maxsize

    def set(self, key, value):
        if key in self:
            super().__delitem__(key)
        super().__setitem__(key, value)
        self.move_to_end(key)
        if len(self) > self.maxsize:
            self.popitem(last=False)

    def get(self, key, default=None):
        val = super().get(key, default)
        if val is not None:
            self.move_to_end(key)
        return val


# -----------------------------
# SQLite storage (persistence)
# -----------------------------

class MessageStore:
    def __init__(self, db_path: str = "data/message_log.db"):
        self.db_path = db_path
        _ensure_dir(self.db_path)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY,
                    guild_id   INTEGER,
                    channel_id INTEGER,
                    author_id  INTEGER,
                    content    TEXT,
                    payload    TEXT,
                    created_at INTEGER
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id)"
            )

    def upsert(self, message: discord.Message):
        payload = json.dumps(_attachments_payload(message), ensure_ascii=False)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO messages(message_id, guild_id, channel_id, author_id, content, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content,
                    payload=excluded.payload
                """,
                (
                    message.id,
                    message.guild.id if message.guild else None,
                    message.channel.id if message.channel else None,
                    message.author.id if message.author else None,
                    message.content or "",
                    payload,
                    int(message.created_at.timestamp()) if message.created_at else 0,
                ),
            )

    def get(self, message_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT author_id, content, payload FROM messages WHERE message_id = ?",
                (message_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            author_id, content, payload = row
            try:
                payload_obj = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                payload_obj = {}
            return {
                "author_id": author_id,
                "content": content,
                **payload_obj,
            }


class MessageAudit(commands.Cog):
    def __init__(self, bot: commands.Bot, *, cache_size: int = 5000, db_path: str = "data/message_log.db"):
        self.bot = bot
        self.cache = LRUCache(cache_size)
        self.store = MessageStore(db_path)

    # ---------------
    # Capture messages
    # ---------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        # Save to memory cache
        self.cache.set(
            message.id,
            {
                "author_id": message.author.id,
                "content": message.content or "",
                **_attachments_payload(message),
            },
        )
        # Persist to sqlite
        try:
            self.store.upsert(message)
        except Exception:
            # Avoid crashing on rare sqlite issues
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return

        author_txt = await mention_or_id(before.guild, getattr(before, "author", None))
        b = before.content or "（空）"
        a = after.content or "（空）"
        desc = (
            f"✏️ {author_txt} 在 {before.channel.mention} 編輯了訊息：\n"
            f"**Before**：{b[:900]}\n**After**：{a[:900]}"
        )
        await send_log(before.guild, emb("Message Edit", desc, 0xFEE75C))

        # Update cache + store with the latest state
        self.cache.set(
            after.id,
            {
                "author_id": after.author.id,
                "content": after.content or "",
                **_attachments_payload(after),
            },
        )
        try:
            self.store.upsert(after)
        except Exception:
            pass

    # ----------------
    # Delete handlers
    # ----------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        cached = self.cache.get(message.id)
        if cached is None:
            cached = self.store.get(message.id)

        # Prefer original cached content if available
        if cached is not None:
            content = cached.get("content") or "（無文字）"
            if len(content) > 900:
                content = content[:897] + "…"
            atts = cached.get("attachments") or []
            att_lines = [f"`{a.get('filename','')}` → {a.get('url','')}" for a in atts]
            attach_text = ("\n📎 附件：\n" + "\n".join(att_lines)) if att_lines else ""
            author_txt = await mention_or_id(message.guild, cached.get("author_id"))
            desc = (
                f"🧹 {author_txt} 的訊息被刪除於 {message.channel.mention}\n"
                f"原文：{content}{attach_text}"
            )
        else:
            # Fallback to runtime message object (likely no content)
            author_txt = await mention_or_id(message.guild, getattr(message, "author", None))
            content = message.content or "（無文字，可能只有附件 / 嵌入）"
            if len(content) > 900:
                content = content[:897] + "…"
            attach_text = ""
            if message.attachments:
                attach_text = "\n附件：" + ", ".join(a.filename for a in message.attachments)
            desc = (
                f"🧹 {author_txt} 的訊息被刪除於 {message.channel.mention}\n"
                f"內容：{content}{attach_text}"
            )

        e = emb("Message Delete", desc, 0xED4245)
        e.set_footer(
            text=f"Author ID: {getattr(message.author, 'id', '未知')} • Message ID: {message.id}"
        )
        await send_log(message.guild, e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        if not messages:
            return
        g = messages[0].guild
        if not g:
            return
        await send_log(g, emb("Bulk Message Delete", f"一次刪除了 **{len(messages)}** 則訊息。", 0xED4245))


async def setup(bot: commands.Bot):
    # You can tune cache size & DB path here if needed
    await bot.add_cog(MessageAudit(bot, cache_size=5000, db_path="data/message_log.db"))
