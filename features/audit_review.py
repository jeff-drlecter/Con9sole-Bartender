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

    @discord.ui.button(label='處理監察問題',emoji='🛠️')
    async def monitor(self,inter,button):
        if not await self.cog.authorized(inter): return
        await inter.response.defer(ephemeral=True)
        monitor=self.cog.bot.get_cog('AuditMonitor')
        if monitor is None:
            return await inter.followup.send('故障監察尚未載入。',ephemeral=True)
        view=MonitorRecoveryView(self.cog,self.owner,monitor.card.state.get('recovery_token'),self.cog.write_failures.count)
        view.rebuild.disabled=monitor.card.state.get('delivery')!='uncertain'
        view.confirm_loss.disabled=not self.cog.write_failed
        await inter.followup.send('監察卡結果未明：先核對 bot-維護，再決定重建；原卡如已送達，可能重複。\n寫入失敗：確認只會解除警號，無法補回遺失事件。',view=view,ephemeral=True,allowed_mentions=NONE)


class MonitorRecoveryView(AuditView):
    def __init__(self,cog,owner,token,count):
        super().__init__(cog,owner)
        self.token,self.count=token,count

    @discord.ui.button(label='已核對，重建監察卡…')
    async def rebuild(self,inter,button):
        await inter.response.send_message('確認已核對 bot-維護？重建可恢復通知，但原卡如已送達，可能出現重複。',
            view=MonitorConfirmation(self.cog,self.owner,'rebuild',self.token,self.count),ephemeral=True)

    @discord.ui.button(label='確認已知悉漏記…')
    async def confirm_loss(self,inter,button):
        await inter.response.send_message(f'確認已知悉累計 {self.count} 次寫入失敗？遺失內容無法由此操作補回；其後新增失敗仍會保留警號。',
            view=MonitorConfirmation(self.cog,self.owner,'loss',self.token,self.count),ephemeral=True)


class MonitorConfirmation(AuditView):
    def __init__(self,cog,owner,action,token,count):
        super().__init__(cog,owner)
        self.action,self.token,self.count=action,token,count

    @discord.ui.button(label='確認處理',style=discord.ButtonStyle.primary)
    async def confirm(self,inter,button):
        if not await self.cog.authorized(inter): return
        await inter.response.defer(ephemeral=True)
        if self.action=='rebuild':
            monitor=self.cog.bot.get_cog('AuditMonitor')
            if monitor is None:
                return await inter.followup.send('故障監察尚未載入。',ephemeral=True)
            async with monitor.lock:
                changed=await asyncio.to_thread(monitor.card.allow_rebuild,self.token,inter.user.id)
        else:
            changed=await self.cog.acknowledge_write_failures(self.count,inter.user.id)
        if changed:
            await self.cog.emit('server','日誌監察人工處理',f'操作人 ID：{inter.user.id}\n處理：{self.action}\n失敗累計：{self.count}\n此操作不代表遺失事件已補回。')
        await inter.followup.send('已記錄處理，監察將於下一輪重新核對。' if changed else '狀態已變更或已處理，請重新開啟面板。',ephemeral=True,allowed_mentions=NONE)

    @discord.ui.button(label='取消')
    async def cancel(self,inter,button):
        await inter.response.edit_message(content='已取消，狀態不變。',view=None)


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
