"""Two independent consent categories; owner-bound, fresh, private UI."""
import sqlite3
import discord
from core.private_source import Source, SourceUnavailable, fresh_access
from core.ui import SafeView
from features.notification_words import text, COPY
from features import plan_reminder_client as reminders
from features.menu_stats import run_stats
from features import squad_interest

NONE=discord.AllowedMentions.none()


async def game_rows(i, member, rows):
    result=[]
    for row in rows:
        # Own consent may always be withdrawn; redact inaccessible game labels.
        visible=False
        for card in (await run_stats(squad_interest.cards,row['id']))[-20:]:
            try:
                current,channel=await fresh_access(i.guild,member.id,card['channel_id'])
                p=channel.permissions_for(current)
                if channel.guild.id==i.guild_id and p.view_channel and p.read_message_history and not getattr(channel,'nsfw',False):
                    visible=True;break
            except SourceUnavailable: continue
        result.append(dict(row,label=row['label'] if visible else text(member,'hidden_subscription')))
    return result


class CenterView(SafeView):
    def __init__(self,cog,source,member,section='home',page=0,rows=(),plan_state='ready',selected=None,unattributed=0):
        super().__init__(timeout=180)
        self.cog,self.source,self.member,self.section,self.page=cog,source,member,section,page
        self.unattributed=unattributed
        self.row_count = len(rows)
        # The summary only needs a count. Keep unredacted labels out of its callbacks.
        self.rows = [] if section == 'home' else list(rows)
        self.plan_state=plan_state;self.selected=selected
        if section=='home':
            for key in ('plans','games'):
                self.button(text(member,key),lambda i,key=key:self.open(i,key),0)
        elif section in ('plans','games'):
            visible=self.rows[page*20:(page+1)*20]
            if visible:
                pick=discord.ui.Select(placeholder=text(member,'manage_plan' if section=='plans' else 'manage_game'),
                    options=[discord.SelectOption(label=r['game' if section=='plans' else 'label'][:100],value=r['id']) for r in visible])
                async def choose(i):
                    if section=='plans': await self.open(i,'detail',key=pick.values[0])
                    else: await self.cancel_game(i,pick.values[0])
                pick.callback=choose;self.add_item(pick)
            if page>0:self.button(text(member,'previous'),lambda i:self.open(i,section,page=page-1),1)
            if (page+1)*20<len(rows):self.button(text(member,'next'),lambda i:self.open(i,section,page=page+1),1)
        elif selected:
            for enabled,key,allowed in [(True,'enable',selected['can_enable']), (False,'disable',selected['can_disable'])]:
                self.button(text(member,key),lambda i,enabled=enabled:self.set_plan(i,enabled),0,disabled=not allowed)
            url=reminders.card_url(selected.get('url'),source.guild)
            if url:self.add_item(discord.ui.Button(label=text(member,'original'),url=url,row=1))
        self.button(text(member,'refresh'),lambda i:self.open(i,section,page=page,key=selected['id'] if selected else None),2)
        if section!='home':self.button(text(member,'back'),lambda i:self.open(i,'plans' if section=='detail' else 'home'),2)
        self.button(text(member,'menu'),self.back,2)
        self.button(text(member,'choose_game'),self.guide,3)

    def button(self,label,callback,row,disabled=False):
        button=discord.ui.Button(label=label,row=row,disabled=disabled);button.callback=callback;self.add_item(button)

    async def interaction_check(self,i):
        if i.user.id==self.source.owner:return True
        await i.response.send_message(text(i.user,'owner'),ephemeral=True);return False

    async def begin(self,i):
        if not await self.interaction_check(i):return None
        if not i.response.is_done():await i.response.defer(ephemeral=True)
        try:return (await self.source.resolve(i))[0]
        except SourceUnavailable:
            await i.edit_original_response(content=text(i.user,'denied'),embed=None,view=None);return None

    async def open(self,i,section,*,page=0,key=None):
        if await self.begin(i) is None:return
        await show_center(self.cog,i,replace=True,section=section,page=page,key=key,source=self.source)

    async def set_plan(self,i,enabled):
        if await self.begin(i) is None:return
        try:
            # 03 must re-authorize and atomically reject a stale registration/version.
            result=await reminders.set_choice(i.client,i.guild,i.user.id,self.selected['id'],enabled,self.selected['version'])
            note=text(i.user,'saved' if result.get('status')=='updated' else 'changed')
        except Exception:
            # Never replay an uncertain write or restore a cached enabled value.
            await i.edit_original_response(content=text(i.user,'uncertain'),embed=None,view=CenterView(self.cog,self.source,i.user))
            return
        await show_center(self.cog,i,replace=True,section='detail',key=self.selected['id'],source=self.source,note=note)

    async def cancel_game(self,i,key):
        member=await self.begin(i)
        if member is None:return
        from core.action_guard import shared_async_lock
        try:
            async with self.cog.lock:
                scope=await run_stats(squad_interest.canonical_scope,key)
                async with shared_async_lock('subscription-consent',i.guild_id,scope):
                    await self.source.resolve(i)
                    current=await run_stats(squad_interest.own_preferences,i.guild_id,member.id)
                    if key not in {r['id'] for r in current}:raise ValueError('changed')
                    await run_stats(squad_interest.cancel,key,i.guild_id,member.id)
            note=text(member,'game_cancelled')
        except (SourceUnavailable,OSError,ValueError,sqlite3.Error):note=text(member,'changed')
        await show_center(self.cog,i,replace=True,section='games',source=self.source,note=note)

    async def back(self,i):
        if await self.begin(i) is None:return
        menu=i.client.get_cog('Menu')
        if menu:await menu.open_main_menu(i)
        else:await self.guide(i)

    async def guide(self,i):
        if await self.begin(i) is None:return
        from core.newcomer_routes import show_next_steps
        await show_next_steps(i,reason='no_destination',replace=True,return_to=lambda j:self.open(j,'home'))

    def embed(self):
        e=discord.Embed(title=text(self.member,'center' if self.section=='home' else 'plans' if self.section=='detail' else self.section))
        if self.section=='home':
            e.description=text(self.member,'independent')
            e.add_field(name=text(self.member,'plans'),value=self.plan_state,inline=False)
            e.add_field(name=text(self.member,'games'),value=str(self.row_count),inline=False)
        elif self.section=='games':
            e.description='\n'.join(self.game_line(r) for r in self.rows[self.page*20:(self.page+1)*20]) or text(self.member,'unattributed' if self.unattributed else 'no_games')
            e.add_field(name=text(self.member,'games'),value=text(self.member,'delivery_note'),inline=False)
        elif self.section=='plans':
            e.description=('\n'.join(self.line(r) for r in self.rows[self.page*20:(self.page+1)*20]) or text(self.member,'no_plans')) if self.plan_state=='ready' else text(self.member,'plan_unavailable')
        else:e.description=self.line(self.selected) if self.selected else text(self.member,'changed')
        if self.unattributed:
            e.add_field(name=text(self.member,'unknown'),value=text(self.member,'unattributed'),inline=False)
        e.set_footer(text=text(self.member,'page',page=self.page+1,total=max(1,(self.row_count+19)//20)))
        return e

    def game_line(self,r):
        label=discord.utils.escape_mentions(discord.utils.escape_markdown(r['label']))[:140]
        status=text(self.member,r['kind'])
        if r.get('uncertain'):
            status=(status+' · ' if r['kind']!='pending' else '')+text(self.member,'delivery_uncertain')
        elif r.get('pending') and r['kind']!='pending':
            status+=' · '+text(self.member,'pending')
        return f"• {label} · {status}"

    def line(self,r):
        game=discord.utils.escape_mentions(discord.utils.escape_markdown(r['game']))[:140]
        state=r['status'] if r['status'] in COPY else 'unknown'
        start=f" · <t:{int(r['start'])}:f>" if isinstance(r.get('start'),(int,float)) else ''
        return f"• {game}{start} · {text(self.member,state)} · {text(self.member,'on' if r['enabled'] else 'off')}"


async def show_center(cog,i,*,replace=False,section='home',page=0,key=None,source=None,note=None):
    source=source or Source(i.user.id,i.guild_id,i.channel_id)
    if not i.response.is_done():await i.response.defer(ephemeral=True,thinking=not replace)
    try:
        member,_,_=await source.resolve(i)
        plan_rows=[];plan_state='ready'
        if section in ('home','plans','detail'):
            try:plan_rows=await reminders.query(i.client,i.guild,member.id)
            except reminders.ReminderUnavailable:plan_state='unavailable'
        rows = plan_rows
        if section in ('home', 'games'):
            rows = await run_stats(squad_interest.own_preferences, i.guild_id, member.id)
            if section == 'games':
                rows = await game_rows(i, member, rows)
        selected=next((r for r in plan_rows if r['id']==key),None) if section=='detail' else None
        if section=='detail' and selected is None:section='plans';note=text(member,'changed') if plan_state=='ready' else text(member,'plan_unavailable')
        if section=='home':plan_state=str(len(plan_rows)) if plan_state=='ready' else text(member,'plan_unavailable')
        page=max(0,min(page,max(0,(len(rows)-1)//20)))
        unattributed=await run_stats(squad_interest.unattributed_deliveries,i.guild_id,member.id) if section in ('home','games') else 0
        member,_,_=await source.resolve(i)
        view=CenterView(cog,source,member,section,page,rows,plan_state,selected,unattributed)
        kwargs=dict(content=note,embed=view.embed(),view=view,allowed_mentions=NONE)
    except (SourceUnavailable,discord.HTTPException,OSError,ValueError,sqlite3.Error):
        kwargs=dict(content=text(i.user,'denied'),embed=None,view=None,allowed_mentions=NONE)
    if replace:await i.edit_original_response(**kwargs)
    else:await i.followup.send(**kwargs,ephemeral=True)
