"""Private, owner-bound review of uncertain audit deliveries."""
from __future__ import annotations

import asyncio

import discord

import config
from core.permissions import is_server_admin
from core.ui import SafeView

NONE=discord.AllowedMentions.none()


class AuditView(SafeView):
    def __init__(self,cog,owner):
        super().__init__(timeout=180)
        self.cog,self.owner=cog,owner

    async def interaction_check(self,inter):
        member=inter.guild.get_member(inter.user.id) if inter.guild else None
        if inter.guild_id==config.GUILD_ID and inter.user.id==self.owner and is_server_admin(member):
            return True
        await inter.response.send_message('此面板不屬於你或管理權限已變更，請重新開啟。',ephemeral=True)
        return False


class AuditHomeView(AuditView):
    @discord.ui.button(label='重新整理',emoji='🔄')
    async def refresh(self,inter,button): await self.cog.show_status(inter)

    @discord.ui.button(label='處理待查事件',emoji='📋')
    async def reviews(self,inter,button): await open_reviews(self.cog,inter)


async def open_reviews(cog,inter):
    if not await cog.authorized(inter):return
    await inter.response.defer(ephemeral=True)
    rows=await asyncio.to_thread(cog.store.review_rows)
    if not rows:
        await inter.followup.send('目前沒有送出結果未明的日誌事件。',view=AuditHomeView(cog,inter.user.id),ephemeral=True)
        return
    view=AuditView(cog,inter.user.id)
    select=discord.ui.Select(placeholder='選擇待查事件（最多 25 筆）',options=[discord.SelectOption(
        label=f"{row['category']}｜{row['payload']['title']}"[:100],value=row['id'],
        description=f"{row['id'][:45]}｜嘗試 {row['attempts']} 次"[:100]) for row in rows])
    async def choose(interaction):
        await interaction.response.defer(ephemeral=True)
        row=await asyncio.to_thread(cog.store.get_review,select.values[0])
        if row is None:
            return await interaction.followup.send('此事件已處理，請重新整理。',ephemeral=True)
        await show_detail(cog,interaction,row)
    select.callback=choose
    view.add_item(select)
    await inter.followup.send('先查看原日誌頻道，確認有沒有相同事件編號，再決定是否重試。',view=view,ephemeral=True,allowed_mentions=NONE)


async def show_detail(cog,inter,row):
    embed=discord.Embed(title='📋 待查日誌事件',description=row['payload']['description'][:2200])
    embed.add_field(name='事件',value=f"`{row['id']}`\n{row['category']}｜{row['payload']['title']}\n<t:{int(row['stamp'])}:f>",inline=False)
    embed.add_field(name='派送狀態',value=f"結果未明｜嘗試 {row['attempts']} 次｜{row['error'] or '無錯誤分類'}",inline=False)
    embed.set_footer(text='原頻道已出現相同事件編號才選確認收到；未收到才確認重試。')
    await inter.followup.send(embed=embed,view=AuditDetailView(cog,inter.user.id,row['id'],row['category']),ephemeral=True,allowed_mentions=NONE)


class AuditDetailView(AuditView):
    def __init__(self,cog,owner,key,category):
        super().__init__(cog,owner)
        self.key=key
        from cogs.community_audit import ROUTES
        self.add_item(discord.ui.Button(label='開啟日誌頻道',style=discord.ButtonStyle.link,
            url=f'https://discord.com/channels/{config.GUILD_ID}/{ROUTES[category]}',row=1))

    @discord.ui.button(label='人工確認已收到',style=discord.ButtonStyle.success)
    async def received(self,inter,button): await apply_review(self.cog,inter,self.key,'ack')

    @discord.ui.button(label='重試派送…',style=discord.ButtonStyle.secondary)
    async def retry(self,inter,button):
        await inter.response.defer(ephemeral=True)
        row=await asyncio.to_thread(self.cog.store.get_review,self.key)
        if row is None:
            return await inter.followup.send('此事件已處理，請重新整理。',ephemeral=True)
        await inter.followup.send('已在原頻道核對，未找到相同事件編號？\n確認後會重新派送；若其實已收到，可能出現重複日誌。',
            view=RetryConfirmation(self.cog,self.owner,self.key),ephemeral=True,allowed_mentions=NONE)


class RetryConfirmation(AuditView):
    def __init__(self,cog,owner,key):
        super().__init__(cog,owner); self.key=key

    @discord.ui.button(label='已核對未收到，確認重試',style=discord.ButtonStyle.primary)
    async def confirm(self,inter,button): await apply_review(self.cog,inter,self.key,'retry')

    @discord.ui.button(label='取消')
    async def cancel(self,inter,button): await inter.response.edit_message(content='已取消，事件狀態不變。',view=None)


async def apply_review(cog,inter,key,action):
    # Also protect direct invocation; the SQL transition and receipt are atomic.
    if not await cog.authorized(inter):return
    await inter.response.defer(ephemeral=True)
    changed=await asyncio.to_thread(cog.store.resolve,key,action,inter.user.id)
    if changed:
        await cog.emit('server','日誌待查事件處理',f'操作人 ID：{inter.user.id}\n事件：{key}\n處理：{action}\n人工確認不等於系統派送回條；重試可能產生重複。')
    text=('已排入重試佇列。' if action=='retry' else '已記錄你的人工確認，不再自動重發。') if changed else '此事件已處理或不存在，沒有重複操作。'
    await inter.followup.send(text,view=AuditHomeView(cog,inter.user.id),ephemeral=True,allowed_mentions=NONE)
