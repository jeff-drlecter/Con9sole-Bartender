"""Private, owner-bound subscription cancellation; never subscribes another user."""
from features.wording import text as wording_text, view_copy as wording_view
import discord
from core.ui import SafeView
from core.action_guard import shared_async_lock
from features import squad_interest
from features.menu_stats import run_stats


class SubscriptionView(SafeView):
    def __init__(self, cog, guild_id, owner_id, rows, page=0, member=None):
        super().__init__(timeout=180)
        self.member = member
        self.cog,self.guild_id,self.owner_id,self.rows = cog,guild_id,owner_id,rows
        self.page=max(0,min(page,max(0,(len(rows)-1)//20)))
        visible=rows[self.page*20:(self.page+1)*20]
        if visible:
            select=discord.ui.Select(placeholder=wording_text(self.member, '揀一款遊戲取消通知'), options=[
                discord.SelectOption(label=row['label'][:100],value=row['id'],description={'once':'下次通知','always':'每次通知','pending':'下一局通知已排隊'}[row['kind']]) for row in visible])
            async def choose(interaction):
                if not await self.interaction_check(interaction):return
                await interaction.response.defer(ephemeral=True,thinking=True)
                async with self.cog.lock:
                    async with shared_async_lock('subscription-consent',self.guild_id,select.values[0]):
                        await run_stats(squad_interest.cancel,select.values[0],self.guild_id,self.owner_id)
                await self.cog.menu_entry(interaction)
            select.callback=choose;self.add_item(select)
        for label,delta in (('上一頁',-1),('下一頁',1)):
            button=discord.ui.Button(label=label,row=1,disabled=not 0<=self.page+delta<max(1,(len(rows)+19)//20))
            async def turn(interaction,delta=delta):await self.cog.menu_entry(interaction,page=self.page+delta)
            button.callback=turn;self.add_item(button)
        from features.drink_views import FeatureButton
        self.add_item(FeatureButton(label='重新整理',emoji='🔄',cog='SquadCards',method='menu_entry',row=2))
        self.add_item(FeatureButton(label='返回吧枱',emoji='🍸',cog='Menu',method='open_main_menu',row=2))

        wording_view(self.member, self)

    async def interaction_check(self, interaction):
        if interaction.guild_id==self.guild_id and interaction.user.id==self.owner_id and not interaction.user.bot:
            return True
        await interaction.response.send_message(wording_text(self.member, '面板唔屬於你，請重新開啟「我的組隊通知」。'),ephemeral=True)
        return False

    def embed(self):
        labels={'once':'🙋 下次通知','always':'🔔 每次通知','pending':'⏳ 下一局通知已排隊'}
        text='\n'.join(f"• {discord.utils.escape_mentions(discord.utils.escape_markdown(row['label']))}｜{labels[row['kind']]}" for row in self.rows[self.page*20:(self.page+1)*20])
        embed=discord.Embed(title='🔔 我的組隊通知',description=text or '暫時未有訂閱或排隊通知。')
        embed.add_field(name='更改通知',value=wording_text(self.member, '揀遊戲即可取消之後及未送出嘅通知；已送出或處理中嘅通知無法撤回。想重新登記或切換通知方式，可到該遊戲召人卡／足跡卡選擇。'),inline=False)
        embed.set_footer(text=wording_text(self.member, '只顯示你自己嘅設定 · 第 ') + f'{self.page+1}/{max(1,(len(self.rows)+19)//20)} 頁')
        return embed
