import asyncio
import re
import discord
import config
from core.action_guard import shared_async_lock
from core.permissions import is_admin_or_helper
from core.ui import SafeView,SafeModal
from features import notification_review as store

STATE={'pending':'待發送','uncertain':'待核對','failed':'明確未送出'}


async def permitted(inter,owner):
    current=inter.guild.get_member(inter.user.id) if inter.guild else None
    return inter.guild_id==config.GUILD_ID and inter.user.id==owner and current is not None and is_admin_or_helper(current)


class OwnedReview(SafeView):
    def __init__(self,owner):super().__init__(timeout=180);self.owner=owner
    async def interaction_check(self,inter):
        if await permitted(inter,self.owner):return True
        await inter.response.send_message('呢個管理面板只限原本管理員使用；請重新開啟。',ephemeral=True)
        return False


async def open_reviews(inter):
    if not await permitted(inter,inter.user.id):
        await inter.response.send_message('只限本伺服器管理員／Helper。',ephemeral=True);return
    await inter.response.defer(ephemeral=True,thinking=True)
    levels=inter.client.get_cog('CommunityLevels')
    rows=await asyncio.to_thread(store.subscription_rows,inter.guild_id)
    if levels:rows+=await asyncio.to_thread(store.weekly_rows,levels.ledger,inter.guild_id)
    view=ReviewList(inter.user.id,rows)
    await inter.followup.send(embed=view.embed(),view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class ReviewList(OwnedReview):
    def __init__(self,owner,rows,page=0):
        super().__init__(owner);self.rows=rows;self.page=page
        visible=rows[page*10:(page+1)*10]
        if visible:
            select=discord.ui.Select(placeholder='揀一項通知核對',options=[discord.SelectOption(
                label=(('招募通知｜' if row['kind']=='subscription' else '週榜｜')+row['label'])[:100],
                description=STATE.get(row['state'],row['state']),value=str(page*10+i)) for i,row in enumerate(visible)])
            async def selected(inter):
                row=self.rows[int(select.values[0])]
                view=ReviewItem(self.owner,row)
                await inter.response.edit_message(embed=view.embed(),view=view)
            select.callback=selected;self.add_item(select)
        for label,offset in (('上一頁',-1),('下一頁',1)):
            button=discord.ui.Button(label=label,row=1,disabled=not 0<=page+offset<max(1,(len(rows)+9)//10))
            async def turn(inter,offset=offset):
                view=ReviewList(self.owner,self.rows,self.page+offset)
                await inter.response.edit_message(embed=view.embed(),view=view)
            button.callback=turn;self.add_item(button)
        refresh=discord.ui.Button(label='重新整理',row=2)
        refresh.callback=open_reviews;self.add_item(refresh)
        from features.drink_views import FeatureButton
        self.add_item(FeatureButton(label='系統狀態',emoji='🩺',cog='BotHealth',method='menu_entry',row=2))

    def embed(self):
        return discord.Embed(title='📬 待查通知',description=f'共有 {len(self.rows)} 項｜第 {self.page+1} 頁\n先核對原頻道，再標記已送出或確認重試。\n結果不確定嘅通知唔會自動重發。'+('\n目前冇待處理通知。' if not self.rows else ''))


class ReviewItem(OwnedReview):
    def __init__(self,owner,row):
        super().__init__(owner);self.row=row
        actions=[('核對並標記已送出','sent'),('確認重試','retry')]
        if row['kind']=='subscription':actions.append(('取消呢次通知','cancel'))
        for label,action in actions:
            button=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary if action=='sent' else discord.ButtonStyle.danger)
            async def choose(inter,action=action):await inter.response.send_modal(ResolveModal(self.owner,self.row,action))
            button.callback=choose;self.add_item(button)
        back=discord.ui.Button(label='返回待查名單',row=1);back.callback=open_reviews;self.add_item(back)

    def embed(self):
        row=self.row
        detail=f"{'招募通知' if row['kind']=='subscription' else '每週排名公告'}｜{discord.utils.escape_markdown(row['label'])}\n狀態：{STATE.get(row['state'],row['state'])}"
        if row['kind']=='subscription':detail+=f"\n原通知人數：{len(row['users'])}｜開局結束後不能重試。"
        detail+='\n標記已送出需要實際通知訊息連結。\n重試可能再次通知成員，請先確認原頻道未有該通知。'
        context=row.get('context',{})
        if context.get('channel'):detail+=f"\n原頻道：<#{context['channel']}>"
        return discord.Embed(title='📬 核對通知',description=detail)


class ResolveModal(SafeModal):
    def __init__(self,owner,row,action):
        super().__init__(title={'sent':'核對已送出通知','retry':'確認重試（可能再次通知成員）','cancel':'取消呢次通知（不會重發）'}[action])
        self.owner=owner;self.row=row;self.action=action
        self.reason=discord.ui.TextInput(label='核對原因',placeholder='例如：已查過原頻道，確認未有送出',max_length=200)
        self.add_item(self.reason)
        self.link=None
        if action=='sent':
            self.link=discord.ui.TextInput(label='實際通知訊息連結',max_length=200)
            self.add_item(self.link)

    async def on_submit(self,inter):
        if not await permitted(inter,self.owner):
            await inter.response.send_message('管理權限已改變，請重新開啟面板。',ephemeral=True);return
        await inter.response.defer(ephemeral=True,thinking=True)
        try:await self.apply(inter)
        except (ValueError,discord.HTTPException) as exc:
            text=str(exc) if isinstance(exc,ValueError) else '讀取／送出失敗；請重新整理狀態再核對。'
            await inter.followup.send(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def proof(self,inter,levels):
        if self.action!='sent':return None
        match=re.fullmatch(r'https://(?:canary\.|ptb\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)',str(self.link.value).strip())
        if not match or int(match[1])!=inter.guild_id:raise ValueError('請貼本伺服器嘅 Discord 訊息連結。')
        channel=inter.guild.get_channel_or_thread(int(match[2]))
        if not channel or not channel.permissions_for(inter.user).view_channel:raise ValueError('無法存取該訊息頻道。')
        message=await channel.fetch_message(int(match[3]))
        if message.author.id!=inter.client.user.id:raise ValueError('該訊息唔係由本 Bot 發出。')
        if self.row['kind']=='weekly':
            if not any(embed.title==f"🏆 {self.row['period']} 頭三名" for embed in message.embeds):raise ValueError('訊息唔係呢個期數嘅週榜公告。')
        else:
            context=self.row.get('context',{})
            if not context.get('card') or channel.id!=context.get('channel'):raise ValueError('缺少原通知資料，或訊息頻道唔符合。')
            url=f"https://discord.com/channels/{inter.guild_id}/{context['channel']}/{context['card']}"
            if url not in message.content:raise ValueError('訊息唔係呢場開局嘅招募通知。')
            mentioned={member.id for member in message.mentions}
            if not mentioned or not mentioned<=set(self.row['users']):raise ValueError('訊息收件名單唔符合呢批通知。')
        return message.id

    async def apply(self,inter):
        levels=inter.client.get_cog('CommunityLevels')
        if not levels:raise ValueError('等級功能未載入，請稍後再試。')
        row=self.row
        if row['kind']=='weekly' and not levels.admin(inter):raise ValueError('處理週榜需要管理伺服器權限。')
        message_id=await self.proof(inter,levels)
        lock=levels.role_lock if row['kind']=='weekly' else shared_async_lock('subscription-delivery',inter.guild_id,row['session'])
        async with lock:
            if not await permitted(inter,self.owner):raise ValueError('管理權限已改變。')
            current=inter.guild.get_member(inter.user.id)
            if row['kind']=='weekly' and not (current.guild_permissions.administrator or current.guild_permissions.manage_guild):raise ValueError('管理伺服器權限已改變。')
            squad=None;session=None;channel=None
            if self.action=='retry' and row['kind']=='subscription':
                from cogs.squad_cards import interest_topic,humans
                squad=inter.client.get_cog('SquadCards')
                pair=next(((cid,s) for cid,s in squad.state['sessions'].items() if s['id']==row['session']),None) if squad else None
                if pair:
                    channel=inter.guild.get_channel(int(pair[0]));session=pair[1]
                topic=interest_topic(channel,session) if channel and session else None
                if not topic or topic['id']!=row['scope'] or session.get('ended') or not humans(channel):raise ValueError('呢場開局已結束或資料已改變，唔會重試通知。')
                if row.get('context',{}).get('channel')!=session['destination']:raise ValueError('原通知頻道已改變，唔會重試。')
            if self.action=='retry' and row['kind']=='weekly' and levels.cfg['mode']!='active':raise ValueError('請先恢復正式模式，再重試週榜。')
            changed=await asyncio.to_thread(store.resolve,levels.ledger,inter.guild_id,row,self.action,inter.user.id,str(self.reason.value),message_id)
            if not changed:raise ValueError('狀態已更新；請重新整理名單，避免重複處理。')
            if squad:
                await squad._notify_interested_locked(channel,session,retry_batch=row['batch'])
        if self.action=='retry' and row['kind']=='weekly':
            await levels.winners.callback(levels,inter,period=row['period'],publish=True)
        else:
            await inter.followup.send({'sent':'已標記並保存核對紀錄。','retry':'已執行一次重試；請重新整理確認送出狀態。','cancel':'已取消呢次通知並保存原因；唔會重發，其他訂閱保持原有設定。'}[self.action],ephemeral=True)
