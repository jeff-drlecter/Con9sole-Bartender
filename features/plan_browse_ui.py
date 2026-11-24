"""Private, freshly queried pages; original cards retain the signup controls."""
import discord
from core.ui import SafeView, SafeModal
from features.plan_services import query, fresh_source, AccessError
from features.plan_community import add_draft_picker, draft_line
from features.language_preferences import language


def words(i,neutral,hk):return hk if language(i.user)=='hk' else neutral


async def next_steps(i):
    from core import newcomer_routes
    if hasattr(newcomer_routes,'show_next_steps'):
        await newcomer_routes.show_next_steps(i,reason='no_destination')
    else:await newcomer_routes.show_route(i,'games')


async def browse(cog,i,*,mine=False,page=0,game='',replace=False):
    if not i.response.is_done():await i.response.defer(ephemeral=True)
    unavailable=False
    try:
        rows=await query(cog,i.guild,i.user.id,mine=mine,game=game)
    except (AccessError,discord.HTTPException,OSError):
        rows=[];unavailable=True
    page=max(0,min(page,(max(1,len(rows))-1)//10))
    embed=discord.Embed(title=words(i,'我的約局' if mine else '看看現有約局','我嘅約局' if mine else '睇吓現有約局'))
    states=dict(open='預約中',due='待開局',gathering='集合中',live='進行中',ended='已結束',cancelled='已取消',expired='未開局',history='歷史紀錄',card_deleted='原卡已刪除',source_deleted='來源已刪除',temporary_failure='暫時無法核對',unknown_result='發送結果待核對',source_mismatch='原卡不符',posting='發送結果待核對')
    labels={0:'進行中',1:'即將開始',2:'歷史／來源狀態'}
    for r in rows[page*10:page*10+10]:
        safe=lambda value:discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))
        slot='不限' if r.get('remaining') is None else str(r['remaining'])
        detail=f"{safe(r['mode'])} · {safe(states.get(r['status'],'狀態待核對'))}\n"
        if r['start']:detail+=f"<t:{int(r['start'])}:f> · 預計 {r.get('total','未知')} 人 · 尚欠 {slot} 人\n"
        detail+=f"[前往原卡報名]({r['url']})" if r['url'] else safe(states.get(r['availability'],'來源目前無法使用'))
        embed.add_field(name=f"{labels[r['group']]} · {safe(r['game'])}"[:256],value=detail[:1024],inline=False)
    if not rows:embed.description=words(i,'目前沒有可顯示的約局。','暫時冇可顯示嘅約局。')
    if unavailable:embed.description=words(i,'暫時無法核對約局；這不代表沒有約局。請重新整理。','暫時核對唔到約局；唔代表冇約局。請重新整理。')
    embed.set_footer(text=f'{page+1}/{max(1,(len(rows)+9)//10)} · 報名不等於到場')
    view=BrowsePages(cog,i.user.id,i.guild_id,mine,page,game,len(rows))
    if language(i.user)=='hk':
        view.children[3].label='揀遊戲篩選'
    await i.edit_original_response(content=None,embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())


class BrowsePages(SafeView):
    def __init__(self,cog,owner,guild,mine,page,game,total):
        super().__init__(timeout=180)
        self.cog,self.owner,self.guild,self.mine,self.page,self.game=cog,owner,guild,mine,page,game
        for label,offset in [('上一頁',-1),('刷新',0),('下一頁',1)]:
            b=discord.ui.Button(label=label,disabled=(offset<0 and page==0) or (offset>0 and (page+1)*10>=total))
            async def callback(i,offset=offset):
                if not await self.interaction_check(i):return
                await browse(cog,i,mine=mine,page=page+offset,game=game,replace=True)
            b.callback=callback;self.add_item(b)
        b=discord.ui.Button(label='篩選遊戲');b.callback=self.filter;self.add_item(b)
        b=discord.ui.Button(label='返回主選單',row=1);b.callback=self.back;self.add_item(b)
    async def interaction_check(self,i):
        if i.user.id==self.owner and i.guild_id==self.guild:return True
        await i.response.send_message(words(i,'請開啟自己的約局選單。','請開啟自己嘅約局選單。'),ephemeral=True);return False
    async def filter(self,i):
        if not await self.interaction_check(i):return
        await i.response.send_modal(GameFilter(self,i.user))

    async def back(self,i):
        if not await self.interaction_check(i):return
        from core.newcomer_routes import NextSteps
        from core.private_source import Source
        await NextSteps(Source(self.owner,self.guild,i.channel_id)).back(i)


class GameFilter(SafeModal):
    def __init__(self,view,member=None):
        super().__init__(title='揀遊戲篩選' if language(member)=='hk' else '篩選遊戲');self.view=view
        self.game=discord.ui.TextInput(label='遊戲名（留空顯示全部）' if language(member)=='hk' else '遊戲名稱（留空顯示全部）',required=False,max_length=80)
        self.add_item(self.game)
    async def on_submit(self,i):
        if not await self.view.interaction_check(i):return
        await browse(self.view.cog,i,mine=self.view.mine,game=self.game.value.strip())


class InstantDraft(SafeView):
    def __init__(self,cog,channel,owner,seed,member=None):
        super().__init__(timeout=180)
        self.cog,self.channel,self.owner,self.seed=cog,channel,owner,seed
        self.used=False
        self.member=member
        self.host_notices=bool(seed.get('host_notices', True))
        add_draft_picker(self, self.seed, owner)
    def summary(self):
        s=self.seed
        safe=lambda value:discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))
        note='只係你嘅招募設定，唔會代其他人報名。' if language(self.member)=='hk' else '只代表你的招募設定，不會代他人報名。'
        return f"🎮 {safe(s['game']) or '請先修改遊戲'}\n平台／模式：{safe(s['mode']) or '未填'} · 原有 {s['party']} 人 · 尚欠 {s['missing']} 人\n{note}\n有人報名時提醒我：{'開啟' if self.host_notices else '關閉'}（原頻道短訊息，其他有權限成員可見）。\n現在玩不建立活動；原有隊友不用重複報名。" + draft_line(self.cog, s)
    async def interaction_check(self,i):
        if i.user.id==self.owner and not self.used:return True
        await i.response.send_message(words(i,'此草稿已關閉，請重新開啟。','呢份草稿已關閉，請重新開啟。'),ephemeral=True);return False
    @discord.ui.button(label='發起',style=discord.ButtonStyle.success)
    async def publish(self,i,b):
        if not await self.interaction_check(i):return
        from cogs.squad_plans import PlanForm,allowed,squad_channel
        self.used=True # Before any await: a second click cannot submit this draft.
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            member,ch=await fresh_source(i.guild,i.user.id,self.channel.id)
            from types import SimpleNamespace
            if not squad_channel(ch) or not allowed(SimpleNamespace(guild_id=i.guild_id,user=member,channel=ch)):
                raise AccessError('denied')
        except (AccessError,discord.HTTPException,OSError):
            await i.edit_original_response(content=words(i,'目的地目前無法使用，草稿未發起。','目的地暫時用唔到，草稿未發起。'),view=None);return
        from features.plan_delivery import options
        from features.squad_plans import counts
        party,capacity=counts(self.seed['party'],self.seed['missing'])
        form=PlanForm(self.cog,ch,instant=True,seed=self.seed,confirmed=True,
            community_key=self.seed.get('community_key'),
            delivery_options=options(party,capacity,instant=True,notices=self.host_notices))
        await form.on_submit(i)
    @discord.ui.button(label='切換報名提醒',row=1)
    async def notice(self,i,b):
        if not await self.interaction_check(i):return
        self.host_notices=not self.host_notices
        self.seed['host_notices']=self.host_notices
        await i.response.edit_message(content=self.summary(),view=self)
    @discord.ui.button(label='修改')
    async def edit(self,i,b):
        if not await self.interaction_check(i):return
        from cogs.squad_plans import PlanForm
        self.used=True
        await i.response.send_modal(draft_form(self.cog,self.channel,self.owner,self.seed))
    @discord.ui.button(label='取消')
    async def cancel(self,i,b):
        if not await self.interaction_check(i):return
        self.used=True
        await i.response.edit_message(content=words(i,'草稿已取消。','草稿已取消。'),embed=None,view=None)


def draft_form(cog,channel,owner,seed):
    from cogs.squad_plans import PlanForm
    from features.squad_plans import counts
    class EditDraft(PlanForm):
        async def on_submit(self,i):
            if i.user.id!=owner:return
            try:
                party,capacity=counts(self.party.value,self.missing.value)
                game=self.game.value.strip()
                if not game:raise ValueError('請填遊戲名稱。')
            except ValueError as e:
                await i.response.send_message(str(e),ephemeral=True);return
            data=dict(game=game,mode=self.mode.value.strip(),party=party,missing='' if capacity is None else capacity-party)
            if seed.get('community_key'):
                data['community_key'] = seed['community_key']
            if 'host_notices' in seed:
                data['host_notices'] = seed['host_notices']
            view=InstantDraft(cog,channel,owner,data,i.user)
            await i.response.send_message(view.summary(),view=view,ephemeral=True)
    return EditDraft(cog,channel,instant=True,seed=seed)
