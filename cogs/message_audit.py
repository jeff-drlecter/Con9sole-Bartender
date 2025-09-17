from __future__ import annotations
from typing import List
import discord
from discord.ext import commands

from utils import emb, send_log

class MessageAudit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        if getattr(message, "author", None) and getattr(message.author, "mention", None):
            author_mention = message.author.mention
        elif getattr(message, "author", None) and getattr(message.author, "id", None):
            author_mention = f"<@{message.author.id}>"
        else:
            author_mention = "（未知成員）"
        content = message.content or "（無文字，可能只有附件 / 嵌入）"
        if len(content) > 500:
            content = content[:497] + "…"
        attach_text = ""
        if message.attachments:
            attach_text = "\n附件：" + ", ".join(a.filename for a in message.attachments)
        desc = f"🧹 {author_mention} 的訊息被刪除於 {message.channel.mention}\n內容：{content}{attach_text}"
        e = emb("Message Delete", desc, 0xED4245)
        e.set_footer(text=f"Author ID: {getattr(message.author, 'id', '未知')} • Message ID: {message.id}")
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
        b = before.content or "（空）"
        a = after.content or "（空）"
        desc = (
            f"✏️ {before.author.mention if hasattr(before.author,'mention') else str(before.author)} "
            f"在 {before.channel.mention} 編輯了訊息：\n"
            f"**Before**：{b[:900]}\n**After**：{a[:900]}"
        )
        await send_log(before.guild, emb("Message Edit", desc, 0xFEE75C))

async def setup(bot: commands.Bot):
    await bot.add_cog(MessageAudit(bot))
