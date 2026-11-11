from __future__ import annotations
import asyncio
import logging
import sqlite3
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from core.permissions import is_server_admin, is_verified_member
from features.referrals import Referrals, source_invites, INVITE_XP, match_batch, month_start

log=logging.getLogger(__name__)


class InviteView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog

    @discord.ui.button(label='邀請朋友',emoji='🔗',style=discord.ButtonStyle.primary,custom_id='referrals:invite')
    async def invite(self,inter,button):await self.cog.menu_entry(inter)

    @discord.ui.button(label='我的邀請成果',custom_id='referrals:mine')
    async def mine(self,inter,button):await self.cog.mine_entry(inter)

    @discord.ui.button(label='邀請排行榜',emoji='🏆',custom_id='referrals:board')
    async def board(self,inter,button):await self.cog.leaderboard_entry(inter)


class BoardView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=180)
        self.cog=cog
    @discord.ui.button(label='本月')
    async def month(self,inter,button):await self.cog.show_board(inter,True)
    @discord.ui.button(label='累計')
    async def total(self,inter,button):await self.cog.show_board(inter,False)


class AdminInviteView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog
    @discord.ui.button(label='平台邀請連結',emoji='🔗',custom_id='referrals:platforms')
    async def platforms(self,inter,button):await self.cog.platform_entry(inter)


class PlatformSelect(discord.ui.Select):
    def __init__(self,cog,entries):
        super().__init__(placeholder='選擇平台／用途',options=[discord.SelectOption(label=k,value=i.code,description=f"累計使用 {i.uses or 0} 次") for k,i in entries[:25]])
        self.cog=cog
    async def callback(self,inter):
        if not is_server_admin(inter.user):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        await inter.response.defer(ephemeral=True)
        try:invites=await inter.guild.invites()
        except discord.HTTPException:
            await inter.followup.send('暫時無法核對連結狀態，未提供未核實連結。',ephemeral=True);return
        code=self.values[0]
        item=next((i for i in invites if i.code==code),None)
        if item is None:
            await inter.followup.send('呢條連結已不在有效清單；未自動建立替代連結。',ephemeral=True);return
        personal=await asyncio.to_thread(self.cog.store.personal_codes,inter.guild_id)
        name=next((label for label,invite in source_invites([item],personal)),None)
        if name is None:
            await inter.followup.send('呢條連結已不屬於平台邀請清單，請重新選擇。',ephemeral=True);return
        channel=f"#{item.channel.name}" if item.channel else "現有邀請"
        await inter.followup.send(f'**{name}**\nhttps://discord.gg/{code}\n累計使用：{item.uses}｜入口：{channel}',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class Invites(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.store=None
        self.snapshots={}
        self.pending_joins=[]
        self.lock=asyncio.Lock()
        self.batch_task=None
        self.ready=False
        self.epoch=0

    async def cog_load(self):
        self.bot.add_view(InviteView(self))
        self.bot.add_view(AdminInviteView(self))
        self.retry_rewards.add_exception_type(sqlite3.OperationalError)
        self.retry_rewards.start()

    async def cog_unload(self):
        self.retry_rewards.cancel()
        if self.batch_task:
            self.batch_task.cancel()
            await asyncio.gather(self.batch_task,return_exceptions=True)

    async def initialize(self):
        if self.store is None:
            levels=self.bot.get_cog('CommunityLevels')
            if not levels or not levels.ledger:return False
            self.store=await asyncio.to_thread(Referrals,levels.ledger)
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        await self.baseline()

    @commands.Cog.listener()
    async def on_resumed(self):
        await self.baseline()

    @commands.Cog.listener()
    async def on_disconnect(self):
        self.epoch+=1
        self.ready=False
        self.snapshots.clear()

    async def baseline(self):
        async with self.lock:
            self.epoch+=1
            self.ready=False
            if not await self.initialize():return
            guild=self.bot.get_guild(config.GUILD_ID)
            if guild is None:return
            if not guild.chunked:await guild.chunk(cache=True)
            # Existing/reconnected members are never retroactively credited.
            await asyncio.to_thread(self.store.seed,guild.id,[m.id for m in guild.members])
            try:self.snapshots[guild.id]={i.code:i.uses or 0 for i in await guild.invites()}
            except discord.HTTPException:
                log.warning('Invite baseline unavailable; attribution remains unknown');return
            self.ready=True

    @commands.Cog.listener()
    async def on_invite_create(self,invite):
        # An unknown newly-created invite starts at zero; do not refresh other counts.
        if invite.guild and invite.guild.id==config.GUILD_ID and self.ready:
            self.snapshots.setdefault(invite.guild.id,{}).setdefault(invite.code,0)

    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.guild.id!=config.GUILD_ID or member.bot:return
        if not await self.initialize():return
        self.pending_joins.append((member,self.epoch if self.ready else None))
        if not self.batch_task or self.batch_task.done():
            self.batch_task=asyncio.create_task(self.process_batch())

    async def process_batch(self):
        await asyncio.sleep(2)
        async with self.lock:
            batch,self.pending_joins=self.pending_joins,[]
            if not batch:return
            guild=batch[0][0].guild
            code=None
            try:
                after={i.code:i.uses or 0 for i in await guild.invites()}
                if self.ready and all(epoch==self.epoch for _,epoch in batch):
                    code=match_batch(self.snapshots.get(guild.id,{}),after,len(batch))
                self.snapshots[guild.id]=after
            except discord.HTTPException:
                self.ready=False
                self.snapshots.pop(guild.id,None)
            for member,_ in batch:
                await asyncio.to_thread(self.store.joined,guild.id,member.id,member.joined_at.timestamp(),code)
                # A member may have left during the short correlation window.
                if guild.get_member(member.id) is None:
                    await asyncio.to_thread(self.store.departed,guild.id,member.id,member.joined_at.timestamp(),time.time())
        for member,_ in batch:
            try:await self.try_reward(member)
            except Exception:log.exception('Invite reward remains retryable after join')
        if self.pending_joins:self.batch_task=asyncio.create_task(self.process_batch())

    @commands.Cog.listener()
    async def on_member_remove(self,member):
        if member.guild.id==config.GUILD_ID and self.store and member.joined_at:
            await asyncio.to_thread(self.store.departed,member.guild.id,member.id,member.joined_at.timestamp(),time.time())

    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        if after.guild.id==config.GUILD_ID:await self.try_reward(after)

    async def try_reward(self,member):
        if member.bot or member.pending or not is_verified_member(member) or not self.store:return
        levels=self.bot.get_cog('CommunityLevels')
        if not levels:return
        async with levels.lock:
            if not await levels.ensure_current_membership(member,time.time()):return
            history=await asyncio.to_thread(self.store.history,member.guild.id,member.id)
            record=next((r for r in history if r[0]==member.joined_at.timestamp()),None)
            inviter=member.guild.get_member(record[2]) if record and record[2] else None
            if not inviter or inviter.bot or not await levels.ensure_current_membership(inviter,time.time()):return
            if any(r.id in levels.cfg.get('excluded_roles',[]) for r in inviter.roles):return
            result=await asyncio.to_thread(self.store.reward,member.guild.id,member.id,member.joined_at.timestamp(),time.time())
        if result:await levels.apply_rewards(inviter,result[1])

    @tasks.loop(minutes=1)
    async def retry_rewards(self):
        if not await self.initialize():return
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild:return
        for uid,joined,_ in await asyncio.to_thread(self.store.pending,guild.id):
            member=guild.get_member(uid)
            if member and member.joined_at.timestamp()==joined:
                try:await self.try_reward(member)
                except Exception:log.exception('Invite reward remains retryable')

    @retry_rewards.before_loop
    async def before_rewards(self):
        await self.bot.wait_until_ready()
        if not self.ready:await self.baseline()

    async def menu_entry(self,inter):
        if inter.guild_id!=config.GUILD_ID or inter.user.bot:return
        await inter.response.defer(ephemeral=True)
        if not await self.initialize():
            await inter.followup.send('邀請功能暫時未準備好。',ephemeral=True);return
        # Serialize creation: concurrent clicks reuse one stored code.
        async with self.lock:
            try:
                live={i.code:i for i in await inter.guild.invites()}
                code=await asyncio.to_thread(self.store.link,inter.guild_id,inter.user.id)
                if code not in live:
                    channel=inter.guild.get_channel(config.INVITE_CHANNEL_ID)
                    if not channel or not channel.permissions_for(inter.guild.default_role).view_channel:
                        await inter.followup.send('公開邀請入口未設定好，請聯絡管理員。',ephemeral=True);return
                    invite=await channel.create_invite(max_age=0,max_uses=0,temporary=False,unique=True,reason='Member referral link')
                    code=invite.code
                    await asyncio.to_thread(self.store.save_link,inter.guild_id,inter.user.id,code)
                    self.snapshots.setdefault(inter.guild_id,{}).setdefault(code,0)
            except discord.HTTPException:
                await inter.followup.send('暫時無法取得邀請連結，請管理員核對 Bot 查看邀請及建立邀請權限。',ephemeral=True);return
        await inter.followup.send(f'🔗 **你嘅專屬邀請連結**\nhttps://discord.gg/{code}\n新朋友完成驗證，你可獲 **{INVITE_XP} EXP**；同一人只計一次。\n手機長按連結即可複製。',view=InviteView(self),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def mine_entry(self,inter):
        await inter.response.defer(ephemeral=True)
        if not await self.initialize():return await inter.followup.send('邀請功能暫時未準備好。',ephemeral=True)
        rows=await asyncio.to_thread(self.store.board,inter.guild_id)
        rank=next(((n,count,xp) for n,(uid,count,xp) in enumerate(rows,1) if uid==inter.user.id),(None,0,0))
        await inter.followup.send(f'**我的邀請成果**\n有效邀請：{rank[1]} 人｜累計獲得：{rank[2]} EXP\n排名：{rank[0] or "未上榜"}\n只計功能啟用後確認並已獎勵嘅新成員。',ephemeral=True)

    async def leaderboard_entry(self,inter):await self.show_board(inter,False)

    async def show_board(self,inter,monthly):
        await inter.response.defer(ephemeral=True)
        if not await self.initialize():return await inter.followup.send('邀請功能暫時未準備好。',ephemeral=True)
        rows=await asyncio.to_thread(self.store.board,inter.guild_id,month_start(time.time()) if monthly else 0)
        text='\n'.join(f'{n}. <@{uid}> — **{count} 人** · {xp} EXP' for n,(uid,count,xp) in enumerate(rows[:20],1)) or '暫時未有有效邀請。'
        await inter.followup.send(embed=discord.Embed(title=('本月' if monthly else '累計')+'邀請排行榜',description=text,color=0xe5b65b),view=BoardView(self),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    async def platform_entry(self,inter):
        if not is_server_admin(inter.user):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        await inter.response.defer(ephemeral=True)
        if not await self.initialize():
            await inter.followup.send('邀請功能暫時未準備好。',ephemeral=True);return
        try:invites=await inter.guild.invites()
        except discord.HTTPException:
            await inter.followup.send('暫時無法讀取現有邀請清單。',ephemeral=True);return
        personal=await asyncio.to_thread(self.store.personal_codes,inter.guild_id)
        entries=source_invites(invites,personal)
        if not entries:
            await inter.followup.send('暫時未有對應來源 channel 嘅有效邀請。',ephemeral=True);return
        view=discord.ui.View(timeout=180);view.add_item(PlatformSelect(self,entries))
        await inter.followup.send('選擇現有邀請連結；不會重新生成。',view=view,ephemeral=True)

    @app_commands.command(name='invite',description='一按取得自己嘅邀請連結')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def invite_command(self,inter:discord.Interaction):await self.menu_entry(inter)

    @app_commands.command(name='invite_sources',description='管理員：查看入會來源統計或個別成員紀錄')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def sources_command(self,inter:discord.Interaction,member:discord.Member|None=None,days:app_commands.Range[int,1,365]|None=None):
        if not is_server_admin(inter.user):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        await inter.response.defer(ephemeral=True)
        if not await self.initialize():return await inter.followup.send('邀請功能暫時未準備好。',ephemeral=True)
        if member:
            rows=await asyncio.to_thread(self.store.history,inter.guild_id,member.id)
            lines=[f'<t:{int(joined)}:f>｜{code or "未能確認"}｜邀請人 {inviter or "平台／未知"}｜{"首次記錄" if fresh else "重入／舊成員"}｜{"已離開" if left else "當次未記錄離開"}' for joined,code,inviter,fresh,left in rows]
        else:
            rows=await asyncio.to_thread(self.store.sources,inter.guild_id,time.time()-days*86400 if days else 0)
            try:
                personal=await asyncio.to_thread(self.store.personal_codes,inter.guild_id)
                names={i.code:name for name,i in source_invites(await inter.guild.invites(),personal)}
            except discord.HTTPException:names={}
            lines=[f'{names.get(code,code or "未能確認")}：{joins} 次／{unique} 人／{remaining} 次未記錄離開' for code,joins,unique,remaining in rows]
        await inter.followup.send(('**入會來源紀錄（啟用後）**\n'+'\n'.join(lines))[:1900] if lines else '暫時未有紀錄；不會推算舊成員來源。',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='invite_panel',description='管理員：在指定頻道放置邀請朋友或平台連結固定入口')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def panel_command(self,inter:discord.Interaction,channel:discord.TextChannel,platforms:bool=False):
        if not is_server_admin(inter.user):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        if channel.guild.id!=inter.guild_id:
            await inter.response.send_message('只可放喺本伺服器。',ephemeral=True);return
        await inter.response.defer(ephemeral=True)
        message=await channel.send(
            '🔗 **平台邀請連結**\n管理員揀來源，即可取得現有連結。' if platforms else
            f'🤝 **邀請朋友一齊玩**\n按一下取得你嘅專屬連結；每位新朋友完成驗證，你可獲 {INVITE_XP} EXP。',
            view=AdminInviteView(self) if platforms else InviteView(self),allowed_mentions=discord.AllowedMentions.none())
        await inter.followup.send(f'入口已建立：{message.jump_url}',ephemeral=True)


async def setup(bot):await bot.add_cog(Invites(bot))
