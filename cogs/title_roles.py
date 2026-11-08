import asyncio
import hashlib
import json
import logging
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands,tasks
import config
from core.ui import SafeView
from core.action_guard import shared_async_lock
from features import title_roles as store
from features.collection_milestones import collection_snapshot,select_title,milestones

log=logging.getLogger(__name__)


def catalog():
    from features.theme_collections import themes
    return {**{m.key:m.label for m in milestones()},**{t.award_id(t.targets[-1]):t.title for t in themes()}}


class Owned(SafeView):
    def __init__(self,cog,owner,admin=False):
        super().__init__(timeout=180);self.cog=cog;self.owner=owner;self.admin=admin
    async def interaction_check(self,inter):
        member=inter.guild.get_member(inter.user.id) if inter.guild else None
        okay=inter.guild_id==config.GUILD_ID and member and inter.user.id==self.owner
        if self.admin:okay=okay and self.cog.can_admin(member)
        if okay:return True
        await inter.response.send_message('權限已改變或面板唔屬於你，請重新開啟。',ephemeral=True)
        return False


class Titles(Owned):
    def __init__(self,cog,owner,snapshot,page=0):
        super().__init__(cog,owner)
        awards=snapshot['awards'];visible=awards[page*20:(page+1)*20]
        select=discord.ui.Select(placeholder='揀一個已解鎖稱號',options=[discord.SelectOption(label='不展示稱號',value='none')]+[
            discord.SelectOption(label=a['label'][:100],value=a['milestone_id']) for a in visible])
        async def choose(inter):await cog.preview(inter,select.values[0])
        select.callback=choose;self.add_item(select)
        for label,delta in (('上一頁',-1),('下一頁',1)):
            button=discord.ui.Button(label=label,row=1,disabled=not 0<=page+delta<max(1,(len(awards)+19)//20))
            async def turn(inter,delta=delta):await cog.show_titles(inter,page+delta)
            button.callback=turn;self.add_item(button)
        retry=discord.ui.Button(label='重新核對 Role',row=2)
        async def repair(inter):
            await inter.response.defer(ephemeral=True,thinking=True)
            await asyncio.to_thread(store.enqueue,inter.guild_id,inter.user.id)
            await cog.sync_user(inter.guild,inter.user.id)
            await cog.show_titles(inter)
        retry.callback=repair;self.add_item(retry)
        from features.drink_views import FeatureButton
        self.add_item(FeatureButton(label='我的收藏',emoji='🍾',cog='Drink',method='collection_entry',row=2))
        self.add_item(FeatureButton(label='我的會員卡',emoji='🎖️',cog='CommunityLevels',method='menu_entry',row=2))


class ConfirmTitle(Owned):
    def __init__(self,cog,owner,key):
        super().__init__(cog,owner)
        yes=discord.ui.Button(label='確認選用',style=discord.ButtonStyle.primary)
        async def confirm(inter):
            if not await self.interaction_check(inter):return
            await inter.response.defer(ephemeral=True,thinking=True)
            async with cog.lock:
                snap=await asyncio.to_thread(collection_snapshot,inter.guild_id,inter.user.id)
                if key!='none' and key not in {a['milestone_id'] for a in snap['awards']}:
                    await inter.followup.send('稱號未解鎖，請重新開啟。',ephemeral=True);return
                if not await asyncio.to_thread(select_title,inter.guild_id,inter.user.id,key):return
                await cog._sync(inter.guild,inter.user.id)
            await cog.show_titles(inter)
        yes.callback=confirm;self.add_item(yes)
        back=discord.ui.Button(label='返回稱號名單')
        back.callback=cog.show_titles;self.add_item(back)


class AdminTitles(Owned):
    def __init__(self,cog,owner,items,page=0):
        super().__init__(cog,owner,True)
        entries=list(items.items())[page*20:(page+1)*20]
        select=discord.ui.Select(placeholder='揀一個稱號設定 Role',options=[discord.SelectOption(label=label[:100],value=key) for key,label in entries])
        async def choose(inter):
            key=select.values[0];cfg=await asyncio.to_thread(store.settings,inter.guild_id)
            await inter.response.send_message(f"稱號：{discord.utils.escape_markdown(items[key])}\n目前綁定："+(f"<@&{cfg['mapping'][key]}>" if key in cfg['mapping'] else '未綁定')+'\n只可綁定符合專用規格嘅空 Role；不會即時批量派發。',view=Binding(cog,owner,key),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        select.callback=choose;self.add_item(select)
        for label,delta in (('上一頁',-1),('下一頁',1)):
            button=discord.ui.Button(label=label,row=1,disabled=not 0<=page+delta<max(1,(len(items)+19)//20))
            async def turn(inter,delta=delta):await cog.admin_entry(inter,page+delta)
            button.callback=turn;self.add_item(button)
        preview=discord.ui.Button(label='預覽全員同步',row=2)
        async def plan(inter):await cog.bulk_preview(inter)
        preview.callback=plan;self.add_item(preview)
        retry=discord.ui.Button(label='重試待同步',row=2)
        async def repair(inter):
            if not await self.interaction_check(inter):return
            await inter.response.defer(ephemeral=True,thinking=True)
            for user,_ in await asyncio.to_thread(store.queue_status,inter.guild_id):await asyncio.to_thread(store.enqueue,inter.guild_id,user)
            await cog.tick()
            await cog.admin_entry(inter)
        retry.callback=repair;self.add_item(retry)
        standard=discord.ui.Button(label='建立標準稱號 Roles',row=2)
        standard.callback=cog.standard_preview;self.add_item(standard)



class Binding(Owned):
    def __init__(self,cog,owner,key):
        super().__init__(cog,owner,True)
        roles=discord.ui.RoleSelect(placeholder='選擇專用稱號 Role（需無權限／無顏色）')
        async def choose(inter):await cog.binding_preview(inter,key,roles.values[0].id)
        roles.callback=choose;self.add_item(roles)
        create=discord.ui.Button(label='建立專用 Role',row=1)
        async def make(inter):await cog.binding_preview(inter,key,'create')
        create.callback=make;self.add_item(create)
        clear=discord.ui.Button(label='解除綁定',row=1)
        async def unbind(inter):await cog.binding_preview(inter,key,None)
        clear.callback=unbind;self.add_item(clear)


class TitleRoles(commands.Cog):
    def __init__(self,bot):self.bot=bot;self.managed=set()
    @property
    def lock(self):return shared_async_lock('title-role-sync',config.GUILD_ID)
    async def cog_load(self):
        await asyncio.to_thread(store.initialize)
        self.managed=set((await asyncio.to_thread(store.settings,config.GUILD_ID))['managed'])
        self.tick.add_exception_type(sqlite3.OperationalError)
        self.tick.start()
    async def cog_unload(self):self.tick.cancel()
    @staticmethod
    def can_admin(member):return bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))
    def levels(self):
        levels=self.bot.get_cog('CommunityLevels')
        return {int(rid) for rid in levels.cfg.get('rewards',{}).values()} if levels else set()

    async def sync_user(self,guild,user):
        async with self.lock:await self._sync(guild,user)

    async def _sync(self,guild,user):
        jobs=await asyncio.to_thread(store.queue_status,guild.id,user)
        if jobs is None:return
        # Fresh revision; acknowledgements can never remove a newer selection job.
        from features import drink_storage as storage
        def revision():
            with storage.connect_sqlite(storage.STATS_DB) as db:return db.execute('SELECT revision FROM title_role_jobs WHERE guild=? AND user=?',(guild.id,user)).fetchone()
        row=await asyncio.to_thread(revision)
        if not row:return
        version=row[0]
        try:
            cfg=await asyncio.to_thread(store.settings,guild.id);self.managed=set(cfg['managed'])
            member=await guild.fetch_member(user)
            cached=guild.get_member(user)
            if member.bot or cached is None or cached.joined_at!=member.joined_at:raise ValueError('會員已離開或重新加入，等待核對。')
            selected=await asyncio.to_thread(store.selected,guild.id,user)
            snapshot=await asyncio.to_thread(collection_snapshot,guild.id,user)
            if selected and selected not in {a['milestone_id'] for a in snapshot['awards']}:raise ValueError('選用稱號已無解鎖證明。')
            wanted=cfg['mapping'].get(selected)
            roles={rid:guild.get_role(rid) for rid in cfg['managed']}
            involved={r.id for r in member.roles if r.id in self.managed}|({wanted} if wanted else set())
            if any(not store.safe_role(guild,roles.get(rid),self.levels()) for rid in involved):raise ValueError('Role 遺失、規格或 Bot 層級不符合；未修改角色。')
            if {r.id for r in member.roles if r.id in self.managed}==({wanted} if wanted else set()):
                await asyncio.to_thread(store.finish,guild.id,user,version);return
            if member.id==guild.owner_id or member.top_role>=guild.me.top_role:raise ValueError('Bot 無法修改呢位會員嘅角色。')
            for role in member.roles:
                if role.id in self.managed and role.id!=wanted:await member.remove_roles(role,reason='會員展示稱號同步')
            if wanted and wanted not in {r.id for r in member.roles}:await member.add_roles(roles[wanted],reason='會員展示稱號同步')
            await asyncio.to_thread(store.finish,guild.id,user,version)
        except Exception as exc:
            log.warning('Title role pending for user=%s: %s',user,type(exc).__name__)
            await asyncio.to_thread(store.finish,guild.id,user,version,str(exc) if isinstance(exc,ValueError) else 'Discord 操作失敗，等待重試。')

    @tasks.loop(seconds=30)
    async def tick(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild or not self.bot.is_ready():return
        for user,_ in await asyncio.to_thread(store.pending,guild.id):await self.sync_user(guild,user)
    @tick.before_loop
    async def before_tick(self):await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        if after.guild.id==config.GUILD_ID and not after.bot and ({r.id for r in before.roles}^{r.id for r in after.roles}) & self.managed:
            await asyncio.to_thread(store.enqueue,after.guild.id,after.id)

    async def status(self,guild,user,snap):
        cfg=await asyncio.to_thread(store.settings,guild.id)
        member=guild.get_member(user);wanted=cfg['mapping'].get(snap['selected'])
        have={r.id for r in member.roles if r.id in cfg['managed']} if member else set()
        job=await asyncio.to_thread(store.queue_status,guild.id,user)
        if job:return 'Role 待同步；可按「重新核對 Role」重試'
        if have!=({wanted} if wanted else set()):return 'Role 尚未同步；可按「重新核對 Role」'
        if not snap['selected']:return '不展示稱號'
        return '✅ 已同步 Discord Role' if wanted else '未綁定 Role；稱號只顯示喺卡片'

    async def show_titles(self,inter,page=0):
        if inter.guild_id!=config.GUILD_ID:return
        if not inter.response.is_done():await inter.response.defer(ephemeral=True,thinking=True)
        snap=await asyncio.to_thread(collection_snapshot,inter.guild_id,inter.user.id)
        cfg=await asyncio.to_thread(store.settings,inter.guild_id)
        current=next((a['label'] for a in snap['awards'] if a['milestone_id']==snap['selected']),'不展示稱號')
        state=await self.status(inter.guild,inter.user.id,snap)
        embed=discord.Embed(title='🏅 管理稱號',description=f'目前展示：**{discord.utils.escape_markdown(current)}**\n{state}\n已解鎖 {len(snap["awards"])} 個稱號｜第 {page+1} 頁\n只可展示一個；更換時會移除舊稱號 Role。')
        unlocked={a['milestone_id'] for a in snap['awards']}
        next_goals=[m for m in milestones() if m.key.startswith('count:') and m.key not in unlocked][:3]
        if next_goals:embed.add_field(name='🔒 下一批稱號',value='\n'.join(f'{m.label}：收藏 {m.target} 款不同酒' for m in next_goals)+f'\n目前已收藏 {len(snap["names"])} 款；主題稱號條件可到「主題酒單」查看。',inline=False)
        await inter.followup.send(embed=embed,view=Titles(self,inter.user.id,snap,page),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    async def menu_entry(self,inter):await self.show_titles(inter)

    async def preview(self,inter,key):
        snap=await asyncio.to_thread(collection_snapshot,inter.guild_id,inter.user.id)
        labels={a['milestone_id']:a['label'] for a in snap['awards']}
        if key!='none' and key not in labels:
            await inter.response.send_message('稱號未解鎖。',ephemeral=True);return
        await inter.response.send_message('將選用：**'+discord.utils.escape_markdown(labels.get(key,'不展示稱號'))+'**\n確認後更新會員卡，並同步已綁定嘅 Discord 稱號 Role。',view=ConfirmTitle(self,inter.user.id,key),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def admin_entry(self,inter,page=0):
        current=inter.guild.get_member(inter.user.id) if inter.guild else None
        if inter.guild_id!=config.GUILD_ID or not self.can_admin(current):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        if not inter.response.is_done():await inter.response.defer(ephemeral=True,thinking=True)
        cfg=await asyncio.to_thread(store.settings,inter.guild_id);jobs=await asyncio.to_thread(store.queue_status,inter.guild_id)
        unsafe=sum(not store.safe_role(inter.guild,inter.guild.get_role(rid),self.levels()) for rid in cfg['mapping'].values())
        pending=cfg.get('provisioning',{})
        items=catalog()
        for key in cfg['mapping']:items.setdefault(key,'舊版稱號 · '+key[:50])
        note='\n建立結果待核對：'+ '、'.join(items.get(key,key) for key in pending)+'；請核對伺服器 Role 後綁定，或確認未建立後解除綁定。' if pending else ''
        await inter.followup.send(f'🏅 稱號管理｜已綁定 {len(cfg["mapping"])} 個｜待同步 {len(jobs)} 人｜待修正 Role {unsafe} 個\n首次全員同步必須先預覽再確認；唔會自動補派。'+note+'\n'+ '\n'.join(f'<@{user}>：{error or "等待同步"}' for user,error in jobs[:15]),view=AdminTitles(self,inter.user.id,items,page),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def binding_preview(self,inter,key,role_id):
        if not self.can_admin(inter.guild.get_member(inter.user.id)):return
        cfg=await asyncio.to_thread(store.settings,inter.guild_id)
        view=Owned(self,inter.user.id,True);confirm=discord.ui.Button(label='確認設定',style=discord.ButtonStyle.primary)
        async def commit(i):
            if not await view.interaction_check(i):return
            await i.response.defer(ephemeral=True,thinking=True)
            async with self.lock:
                latest=await asyncio.to_thread(store.settings,i.guild_id)
                if latest['version']!=cfg['version']:
                    await i.followup.send('設定已改變，請重新預覽。',ephemeral=True);return
                role=i.guild.get_role(role_id) if type(role_id) is int else None
                if role_id=='create':
                    try:await asyncio.to_thread(store.begin_provision,i.guild_id,key,i.user.id)
                    except ValueError as exc:await i.followup.send(str(exc),ephemeral=True);return
                    role=await i.guild.create_role(name=('🍸 '+catalog().get(key,'舊版收藏稱號'))[:100],permissions=discord.Permissions.none(),colour=discord.Colour.default(),hoist=False,mentionable=False,reason='建立專用會員展示稱號')
                if role_id and (not store.safe_role(i.guild,role,self.levels()) or (role.id not in latest['managed'] and role.members)):
                    await i.followup.send('Role 必須無權限、無顏色、不分組、不可提及、低於 Bot；首次綁定不可已有成員。',ephemeral=True);return
                self.managed=set((await asyncio.to_thread(store.bind,i.guild_id,key,role.id if role else None,i.user.id))['managed'])
            await self.admin_entry(i)
        confirm.callback=commit;view.add_item(confirm)
        await inter.response.send_message(f'稱號：{discord.utils.escape_markdown(catalog().get(key,"舊版收藏稱號"))}\n操作：'+('建立專用 Role' if role_id=='create' else '解除綁定' if role_id is None else f'綁定 Role {role_id}')+'\n此 Role 會交由稱號系統管理；今次不會批量派發。',view=view,ephemeral=True)

    async def standard_preview(self,inter):
        if not self.can_admin(inter.guild.get_member(inter.user.id)):return
        await inter.response.defer(ephemeral=True,thinking=True)
        cfg=await asyncio.to_thread(store.settings,inter.guild_id)
        missing={m.key:m.label for m in milestones() if m.key.startswith('count:') and m.key not in cfg['mapping']}
        view=Owned(self,inter.user.id,True)
        confirm=discord.ui.Button(label=f'確認建立 {len(missing)} 個專用 Role',disabled=not missing)
        async def create(i):
            if not await view.interaction_check(i):return
            await i.response.defer(ephemeral=True,thinking=True)
            async with self.lock:
                current=await asyncio.to_thread(store.settings,i.guild_id)
                if current['version']!=cfg['version']:
                    await i.followup.send('設定已改變，請重新預覽。',ephemeral=True);return
                if not i.guild.me or not i.guild.me.guild_permissions.manage_roles:
                    await i.followup.send('Bot 缺少管理角色權限；未建立。',ephemeral=True);return
                done=0
                try:
                    for key,label in missing.items():
                        await asyncio.to_thread(store.begin_provision,i.guild_id,key,i.user.id)
                        role=await i.guild.create_role(name=('🍸 '+label)[:100],permissions=discord.Permissions.none(),colour=discord.Colour.default(),hoist=False,mentionable=False,reason='建立標準會員展示稱號；不派發會員')
                        if not store.safe_role(i.guild,role,self.levels()):raise ValueError('新 Role 規格不符合，請核對。')
                        self.managed=set((await asyncio.to_thread(store.bind,i.guild_id,key,role.id,i.user.id))['managed']);done+=1
                except Exception:
                    await i.followup.send(f'已建立及綁定 {done} 個；其餘有待核對。請重新開啟稱號管理，避免重複建立。',ephemeral=True);return
            await i.followup.send(f'已建立及綁定 {done} 個專用 Role；未向任何會員派發。',ephemeral=True)
        confirm.callback=create;view.add_item(confirm)
        await inter.followup.send('將建立以下無權限、無顏色、不分組、不可任意提及嘅專用 Role：\n'+'\n'.join('🍸 '+label for label in missing.values())+'\n今次只建立綁定，不會派發畀會員；主題稱號可另外設定。',view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def bulk_plan(self,guild):
        if not guild.chunked:raise ValueError('會員名單未完整，請稍後重試。')
        cfg=await asyncio.to_thread(store.settings,guild.id);selected=await asyncio.to_thread(store.selections,guild.id)
        rows=[]
        for member in guild.members:
            if member.bot:continue
            have=sorted(r.id for r in member.roles if r.id in cfg['managed'])
            wanted=cfg['mapping'].get(selected.get(member.id));want=[wanted] if wanted else []
            if have!=want:
                if any(not store.safe_role(guild,guild.get_role(rid),self.levels()) for rid in set(have+want)):
                    raise ValueError('有 Role 遺失、規格或層級不符合；請先修正綁定。')
                if member.id==guild.owner_id or member.top_role>=guild.me.top_role:
                    raise ValueError(f'會員 {member.id} 層級高於 Bot；請先核對，今次未排隊。')
                if wanted:
                    snap=await asyncio.to_thread(collection_snapshot,guild.id,member.id)
                    if selected[member.id] not in {a['milestone_id'] for a in snap['awards']}:
                        raise ValueError(f'會員 {member.id} 嘅選用稱號未有解鎖證明。')
                rows.append((member.id,selected.get(member.id),have,want))
        digest=hashlib.sha256(json.dumps([cfg['version'],rows],sort_keys=True).encode()).hexdigest()
        return rows,digest

    async def bulk_preview(self,inter):
        if not self.can_admin(inter.guild.get_member(inter.user.id)):return
        await inter.response.defer(ephemeral=True,thinking=True)
        try:rows,digest=await self.bulk_plan(inter.guild)
        except ValueError as exc:await inter.followup.send(str(exc),ephemeral=True);return
        view=Owned(self,inter.user.id,True);button=discord.ui.Button(label=f'確認排隊同步 {len(rows)} 人',disabled=not rows)
        async def commit(i):
            if not await view.interaction_check(i):return
            await i.response.defer(ephemeral=True,thinking=True)
            async with self.lock:
                latest,check=await self.bulk_plan(i.guild)
                if check!=digest:await i.followup.send('名單／角色已改變，請重新預覽。',ephemeral=True);return
                await asyncio.to_thread(store.enqueue_batch,i.guild_id,[r[0] for r in latest],i.user.id,dict(digest=check,rows=latest))
            await i.followup.send('已排隊；可喺稱號管理查看待同步人數及重試。',ephemeral=True)
        button.callback=commit;view.add_item(button)
        import io,csv
        export=io.StringIO();writer=csv.writer(export);writer.writerow(['user_id','selected_title','old_roles','new_roles'])
        writer.writerows(rows)
        lines='\n'.join(f'<@{user}>：'+('更新稱號 Role' if want else '移除舊稱號 Role') for user,_,_,want in rows[:20]) or '所有已綁定稱號角色一致。'
        await inter.followup.send(f'預計同步 {len(rows)} 人；未確認前不會派發。完整名單見附件。\n'+lines,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),file=discord.File(io.BytesIO(export.getvalue().encode('utf-8-sig')),filename='title-role-preview.csv'))

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='title_roles',description='管理收藏展示稱號與 Discord Role 綁定及同步')
    async def command(self,inter:discord.Interaction):await self.admin_entry(inter)


async def setup(bot):await bot.add_cog(TitleRoles(bot))
