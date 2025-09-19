from __future__ import annotations
from typing import List, Optional, Union
import discord
from discord.ext import commands

from utils import emb, send_log


async def mention_or_id(guild: discord.Guild, user_or_id: Union[int, discord.abc.User, discord.Member, None]) -> str:
    """Return a **real mention** for members (clickable on mobile/desktop).
    Fallback to plain ID text if the user isn't in the guild anymore.
    """
    if user_or_id is None:
        return "（未知成員）"

    # If we already have a Member with .mention, use it directly
    if isinstance(user_or_id, discord.Member):
        return user_or_id.mention

    # If it's a User object, try to resolve to Member
    if isinstance(user_or_id, discord.User):
        uid = user_or_id.id
    elif isinstance(user_or_id, int):
        uid = user_or_id
    else:
        # Unexpected type; show string to avoid mobile 'unknown user' popup
        return f"User ID: {getattr(user_or_id, 'id', '未知')}"

    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except discord.NotFound:
            member = None
        except discord.HTTPException:
            member = None

    return member.mention if member else f"User ID: {uid}"


class MessageAudit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return

        author_txt = await mention_or_id(message.guild, getattr(message, "author", None))
        content = message.content or "（無文字，可能只有附件 / 嵌入）"
        if len(content) > 500:
            content = content[:497] + "…"

        attach_text = ""
        if message.attachments:
            attach_text = "\n附件：" + ", ".join(a.filename for a in message.attachments)

        desc = (
            f"🧹 {author_txt} 的訊息被刪除於 {message.channel.mention}\n"
            f"內容：{content}{attach_text}"
        )
        e = emb("Message Delete", desc, 0xED4245)
        e.set_footer(text=f"Author ID: {getattr(message.author, 'id', '未知')} • Message ID: {message.id}")
        # send_log 內部用 channel.send(embed=...)；預設 AllowedMentions 允許 user 提及，
        # 若你全域關過 allowed_mentions，就在 utils.send_log 內補回 users=True。
        await send_log(message.guild, e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        if not messages:
            return
        g = messages[0].guild
        if not g:
            return
        await send_log(g, emb("Bulk Message Delete", f"一次刪除了 **{len(messages)}** 則訊息。", 0xED4245))

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


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageAudit(bot))
