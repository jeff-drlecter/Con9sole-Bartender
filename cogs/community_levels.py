"""Opt-in Con9sole leveling; read-only until the owner starts a preview."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import json
import re
import sqlite3
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from features.community_levels import Ledger, REWARD_NAMES, battle_identity, calendar, level_for, threshold, render_notice
from features.level_history import HistoryAudit

log = logging.getLogger(__name__)
GUILD = discord.Object(id=config.GUILD_ID)
# Release gate: turn on only after the evidence checklist in LEVEL_AUDIT.md passes.
REPLACEMENT_READY = False


def reward_role_safe(role, me):
    powers = ('administrator', 'manage_guild', 'manage_roles', 'kick_members',
              'ban_members', 'moderate_members', 'manage_channels', 'manage_webhooks',
              'manage_messages', 'manage_threads', 'mention_everyone')
    return not (role.is_default() or role.managed or role >= me.top_role or
                any(getattr(role.permissions, p, False) for p in powers))



def eligible(member, channel, cfg):
    if member.bot or any(r.id in cfg['excluded_roles'] for r in member.roles):
        return False
    ids = {channel.id, getattr(channel,'parent_id',None), getattr(channel,'category_id',None)}
    return not ids.intersection(cfg['excluded_channels'])


def voice_members(channel,cfg):
    return [m for m in channel.members if eligible(m,channel,cfg) and m.voice and
            not (m.voice.self_deaf or m.voice.deaf or m.voice.afk or m.voice.suppress)]


class LevelsPanel(discord.ui.View):
    def __init__(self,cog,owner):
        super().__init__(timeout=180)
        self.cog,self.owner = cog,owner

    async def interaction_check(self,inter):
        if inter.user.id != self.owner or not self.cog.admin(inter):
            await inter.response.send_message('只有開啟面板嘅管理員可以操作。',ephemeral=True)
            return False
        return True

    @discord.ui.button(label='開始試行',style=discord.ButtonStyle.primary)
    async def preview(self,inter,button):
        await inter.response.defer(ephemeral=True)
        await self.cog.configure(mode='preview')
        self.cog.voice_clock.clear()
        await inter.edit_original_response(embed=await self.cog.settings_embed(),view=self)

    @discord.ui.button(label='暫停計分',style=discord.ButtonStyle.secondary)
    async def pause(self,inter,button):
        await inter.response.defer(ephemeral=True)
        await self.cog.configure(mode='off')
        self.cog.voice_clock.clear()
        await inter.edit_original_response(embed=await self.cog.settings_embed(),view=self)

    @discord.ui.button(label='重新整理',style=discord.ButtonStyle.secondary)
    async def refresh(self,inter,button):
        await inter.response.defer(ephemeral=True)
        await inter.edit_original_response(embed=await self.cog.settings_embed(),view=self)


def original_bot_message(message):
    """Accept bot sends or application interaction responses, never arbitrary webhooks.

    Discord interaction followups use the application ID as webhook ID.
    Require all three server-supplied identities to agree for that path.
    """
    if not message.author.bot:
        return False
    if not message.webhook_id:
        return True
    app_id=getattr(message,'application_id',None)
    return type(app_id) is int and app_id==message.webhook_id==message.author.id


class CommunityLevels(commands.Cog):
    levels = app_commands.Group(name='levels',description='Con9sole 會員等級及活躍紀錄',guild_ids=[config.GUILD_ID])

    def __init__(self,bot):
        self.bot=bot
        self.ledger=None
        self.lock=asyncio.Lock()
        self.role_lock=asyncio.Lock()
        self.gateway_confirmed=False
        self.voice_clock={}
        self.cfg={}
        self.history_audit=None
        self.history_tasks={}

    async def cog_load(self):
        self.ledger=await asyncio.to_thread(Ledger)
        self.cfg=await asyncio.to_thread(self.ledger.settings,config.GUILD_ID)
        self.history_audit=await asyncio.to_thread(HistoryAudit)
        self.voice_tick.add_exception_type(sqlite3.OperationalError)
        self.voice_tick.start()

    async def cog_unload(self):
        self.voice_tick.cancel()
        for task in self.history_tasks.values():task.cancel()
        if self.history_tasks:await asyncio.gather(*self.history_tasks.values(),return_exceptions=True)

    async def configure(self,**changes):
        # A confirmed pause waits for current Discord role writes to finish.
        async with self.role_lock:
            async with self.lock:
                self.cfg=await asyncio.to_thread(self.ledger.configure,config.GUILD_ID,**changes)

    @staticmethod
    def admin(inter):
        return inter.guild_id==config.GUILD_ID and (inter.user.guild_permissions.administrator or inter.user.guild_permissions.manage_guild)

    async def guard(self,inter):
        if not self.admin(inter):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True)
            return False
        if not inter.response.is_done():
            await inter.response.defer(ephemeral=True)
        return True

    async def settings_embed(self):
        cfg=self.cfg
        e=discord.Embed(title='🎖️ Con9sole 等級管理',color=0xe5b65b,
                       description=f"狀態：**{cfg['mode']}**\n試行會記錄獨立 XP，但唔派角色／發升級公告。")
        cap_note=f"Bot 活動每日最多 {cfg['activity_daily_cap']} 次" if cfg['activity_daily_cap'] else 'Bot 活動冇額外每日上限'
        e.add_field(name='文字／Bot 活動',value=f"共用 {max(cfg['text_cooldown'],cfg['activity_cooldown'])} 秒冷卻；每次 1 XP\n{cap_note}",inline=False)
        e.add_field(name='語音',value=f"最少 2 位有效真人；每 {cfg['voice_interval']//60} 分鐘 {cfg['voice_xp']} XP\n排除 AFK、耳聾及舞台聽眾",inline=False)
        e.add_field(name='其他',value=f"Booster 文字／活動 ×{cfg['booster_multiplier']}\n來源 {len(cfg['sources'])} 個｜角色獎勵 {len(cfg['rewards'])} 個\n離開清分 {cfg['clear_on_leave']}；每週一香港時間自動開始新榜",inline=False)
        e.set_footer(text='Auditor：正式接管鎖定。需完成無損搬遷、實際計分及回滾驗證。')
        return e

    async def credit(self,member,channel,source,event,now=None):
        if not member or member.guild.id!=config.GUILD_ID or self.cfg['mode']=='off' or not eligible(member,channel,self.cfg):
            return
        multiplier=self.cfg['booster_multiplier'] if member.premium_since else 1
        async with self.lock:
            result=await asyncio.to_thread(self.ledger.award,config.GUILD_ID,member.id,source,event,
                                          time.time() if now is None else now,multiplier=multiplier)
        if result and self.cfg['mode']=='active':
            await self.apply_rewards(member,result)

    async def apply_rewards(self,member,result):
        async with self.role_lock:
            if self.cfg['mode'] != 'active':
                return
            if isinstance(member,discord.Member):
                try:
                    member=await member.guild.fetch_member(member.id)
                except discord.HTTPException:
                    log.warning('Could not fetch current level roles; deferred reconciliation')
                    return
            latest=await asyncio.to_thread(self.ledger.profile,member.guild.id,member.id)
            # Supplied award totals may already be superseded by another award or adjustment.
            success=await self._apply_rewards_locked(member,(result[0],latest['total']))
            if success:
                await asyncio.to_thread(self.ledger.mark_repaired,member.guild.id,member.id,latest['total'])
            return bool(success)

    async def _apply_rewards_locked(self,member,result):
        old,new=map(level_for,result)
        # Reconcile on each earned award so a transient permissions/API error is retried.
        pairs=[(int(level),member.guild.get_role(int(rid))) for level,rid in self.cfg['rewards'].items()]
        if isinstance(member,discord.Member) and any(role and not reward_role_safe(role,member.guild.me) for _,role in pairs):
            log.warning('Configured level role became unsafe; reconciliation blocked')
            return
        notified=await asyncio.to_thread(self.ledger.notice_level,member.guild.id,member.id,old)
        due=[(level,role) for level,role in pairs if level<=new and role]
        highest=max(due,key=lambda p:p[0])[1] if due else None
        if pairs:
            try:
                if highest and highest not in member.roles:
                    await member.add_roles(highest,reason='Con9sole 會員等級')
                remove=[r for _,r in pairs if r and r!=highest and r in member.roles]
                if remove:
                    await member.remove_roles(*remove,reason='Con9sole 等級角色替換')
            except discord.HTTPException:
                log.warning('Level role update failed; check role hierarchy and Manage Roles')
                return
        if new>notified and self.cfg['announcement_mode']!='off':
            crossed=([new] if self.cfg['announcement_mode']=='all' else [level for level,_ in due if notified<level<=new])
            channel=member.guild.get_channel(self.cfg['announcement_channel'])
            if crossed and isinstance(channel,discord.TextChannel):
                name=REWARD_NAMES.get(max(crossed),'會員')
                try:
                    await channel.send(render_notice(self.cfg,member,new,max(crossed)),
                        allowed_mentions=discord.AllowedMentions(users=self.cfg['announcement_ping'],roles=False,everyone=False))
                    await asyncio.to_thread(self.ledger.mark_notice,member.guild.id,member.id,new)
                except discord.HTTPException:
                    log.warning('Level announcement failed')
                    return False
            elif crossed and self.cfg['announcement_channel']:
                return False
        return True

    @commands.Cog.listener()
    async def on_message(self,message):
        if not message.guild or message.guild.id!=config.GUILD_ID or self.cfg['mode']=='off':
            return
        if message.author.bot:
            await self.observe_battle(message)
        elif isinstance(message.author,discord.Member):
            content=message.content.strip()
            if not content and not message.attachments:
                return
            await self.credit(message.author,message.channel,'text',f'm:{message.id}',message.created_at.timestamp())

    async def observe_battle(self,message):
        if not original_bot_message(message):
            return
        source={'bot':message.author.id,'channel':message.channel.id}
        if source not in self.cfg['sources']:
            return
        identity=battle_identity([e.to_dict() for e in message.embeds])
        if not identity:
            return
        uid,name=identity
        if uid is not None:
            member=message.guild.get_member(uid)
            # Bind only a direct mention paired with the member's exact current account name.
            if not member or member.bot or member.name!=name:
                return
            async with self.lock:
                if self.cfg['mode']=='off': return
                await asyncio.to_thread(self.ledger.bind,message.guild.id,message.author.id,name,uid)
        else:
            uid=await asyncio.to_thread(self.ledger.resolve,message.guild.id,message.author.id,name)
            member=message.guild.get_member(uid) if uid else None
            if not member or member.name!=name:
                return
        await self.credit(member,message.channel,'activity',f'm:{message.id}',message.created_at.timestamp())

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if payload.guild_id!=config.GUILD_ID or self.cfg['mode']=='off':
            return
        if not any(s['channel']==payload.channel_id for s in self.cfg['sources']):
            return
        channel=self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:channel=await self.bot.fetch_channel(payload.channel_id)
            except discord.HTTPException:return
        if channel:
            try:
                message=await channel.fetch_message(payload.message_id)
                # Never award ancient cards merely because buttons/previews were refreshed.
                if time.time()-message.created_at.timestamp()<=120:
                    await self.observe_battle(message)
            except discord.HTTPException:
                log.warning('Could not inspect updated game card')

    @commands.Cog.listener()
    async def on_community_activity(self,member,channel,event):
        """Dispatched only AFTER a successful Bartender action, never raw button clicks."""
        await self.credit(member,channel,'activity',f'i:{event}')

    def reconcile_voice_members(self,channel,now):
        members=[] if channel.id == channel.guild.afk_channel_id else voice_members(channel,self.cfg)
        valid={(channel.id,m.id) for m in members} if len(members)>=2 else set()
        for key in list(self.voice_clock):
            if key[0]==channel.id and key not in valid:
                self.voice_clock.pop(key,None)
        for key in valid:
            self.voice_clock.setdefault(key,now)
        return members if len(members)>=2 else []

    @commands.Cog.listener()
    async def on_member_remove(self,member):
        if member.guild.id!=config.GUILD_ID or self.cfg['mode']!='active' or not self.cfg['clear_on_leave']:
            return
        async with self.role_lock:
            async with self.lock:
                if self.cfg['mode']=='active' and self.cfg['clear_on_leave']:
                    await asyncio.to_thread(self.ledger.member_left,member.guild.id,member.id,time.time())

    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        if member.guild.id!=config.GUILD_ID or not self.gateway_confirmed:
            return
        # Discord updates channel membership/state before dispatching this event.
        # Keeping the same eligible set preserves time through mute/video/stream changes.
        channels={c.id:c for c in (before.channel,after.channel) if c}
        for channel in channels.values():
            self.reconcile_voice_members(channel,time.monotonic())

    @commands.Cog.listener()
    async def on_thread_update(self,before,after):
        if after.guild.id!=config.GUILD_ID or after.archived:
            return
        if any(s['channel']==after.id for s in self.cfg['sources']):
            try:await after.join()
            except discord.HTTPException:log.warning('Could not join allowlisted game thread')

    @commands.Cog.listener()
    async def on_disconnect(self):
        self.gateway_confirmed=False
        self.voice_clock.clear()

    @commands.Cog.listener()
    async def on_ready(self):
        self.gateway_confirmed=True
        self.voice_clock.clear()
        await self.reconcile_sources()

    @commands.Cog.listener()
    async def on_resumed(self):
        self.gateway_confirmed=True
        self.voice_clock.clear()
        await self.reconcile_sources()

    async def reconcile_sources(self):
        """Restore subscriptions after downtime without reopening archived threads."""
        for channel_id in sorted({s['channel'] for s in self.cfg.get('sources',[])}):
            try:
                channel=self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if isinstance(channel,discord.Thread) and channel.guild.id==config.GUILD_ID and not channel.archived:
                    await channel.join()
            except discord.HTTPException:
                log.warning('Could not restore allowlisted game thread subscription')

    async def repair_pending(self):
        if self.cfg['mode']!='active' or not self.bot.is_ready() or not self.gateway_confirmed:
            return
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild: return
        pending=await asyncio.to_thread(self.ledger.pending_roles,config.GUILD_ID)
        for uid,total,old in pending:
            member=guild.get_member(uid)
            if member is None:
                try: member=await guild.fetch_member(uid)
                except discord.NotFound:
                    await asyncio.to_thread(self.ledger.mark_repaired,config.GUILD_ID,uid,total)
                    continue
                except discord.HTTPException:
                    await asyncio.to_thread(self.ledger.defer_repair,config.GUILD_ID,uid,time.time())
                    continue
            if not await self.apply_rewards(member,(old,total)):
                await asyncio.to_thread(self.ledger.defer_repair,config.GUILD_ID,uid,time.time())

    @tasks.loop(seconds=30)
    async def voice_tick(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild or self.cfg.get('mode')=='off' or not self.bot.is_ready() or not self.gateway_confirmed:
            self.voice_clock.clear()
            return
        await self.repair_pending()
        now=time.monotonic()
        present=set()
        for channel in guild.voice_channels+guild.stage_channels:
            members=self.reconcile_voice_members(channel,now)
            for member in members:
                key=(channel.id,member.id)
                present.add(key)
                start=self.voice_clock[key]
                if now-start>=self.cfg['voice_interval']:
                    # Disconnect may occur while another member's DB write is awaited.
                    if not self.gateway_confirmed or not self.bot.is_ready():
                        self.voice_clock.clear()
                        return
                    await self.credit(member,channel,'voice',f'v:{channel.id}:{member.id}:{int(time.time())}')
                    self.voice_clock[key]=now
        self.voice_clock={k:v for k,v in self.voice_clock.items() if k in present}

    @voice_tick.before_loop
    async def before_voice(self):
        await self.bot.wait_until_ready()
        self.gateway_confirmed=True

    @voice_tick.error
    async def voice_error(self,error):
        log.error('Level voice timer stopped: %s',type(error).__name__)

    async def menu_entry(self,inter):
        await self.rank.callback(self,inter)

    async def admin_entry(self,inter):
        await self.panel.callback(self,inter)

    @levels.command(name='rank',description='查看等級、升級進度及 XP 來源')
    async def rank(self,inter:discord.Interaction,member:discord.Member|None=None):
        await inter.response.defer(ephemeral=True)
        target=member or inter.user
        p=await asyncio.to_thread(self.ledger.profile,inter.guild_id,target.id)
        position=await asyncio.to_thread(self.ledger.rank_position,inter.guild_id,target.id)
        level=level_for(p['total'])
        earned=p['total']-threshold(level)
        required=threshold(level+1)-threshold(level)
        filled=min(10,earned*10//required)
        e=discord.Embed(title='🎖️ 會員等級',description=f'{target.mention}\n**Lv.{level}** · {p["total"]:,} XP\n'+ '▰'*filled+'▱'*(10-filled)+f' {earned:,}/{required:,}',color=0xe5b65b)
        e.add_field(name='總榜排名',value=str(position) if position else '未上榜')
        e.add_field(name='XP 來源',value=f"文字 {p['text']:,}｜互動 {p['activity']:,}｜語音 {p['voice']:,}\n匯入基準 {p['imported']:,}",inline=False)
        e.set_footer(text=f'模式：{self.cfg["mode"]}｜獨立計分，未同步 Amari；管理調整另計')
        await inter.followup.send(embed=e,allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name='leaderboard',description='查看總榜或香港時間每週榜')
    async def leaderboard(self,inter:discord.Interaction,weekly:bool=False,page:app_commands.Range[int,1,10000]=1,period:str|None=None):
        await inter.response.defer(ephemeral=True)
        if period and not re.fullmatch(r'(?:[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])|amari-legacy)',period):
            await inter.followup.send('期數請填 YYYY-Www，或 amari-legacy。'); return
        week=period or (calendar(time.time())[1] if weekly else None)
        rows=await asyncio.to_thread(self.ledger.leaderboard,inter.guild_id,week,page)
        text='\n'.join(f'{i}. <@{uid}> · {points:,} XP' for i,(uid,points) in enumerate(rows,(page-1)*10+1)) or '暫時未有紀錄。'
        await inter.followup.send(embed=discord.Embed(title='🏆 '+(f'期數 {week}' if week else '會員總榜'),description=text),allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name='admin',description='管理等級設定及試行狀態')
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self,inter:discord.Interaction):
        if await self.guard(inter):
            await inter.followup.send(embed=await self.settings_embed(),view=LevelsPanel(self,inter.user.id))

    @levels.command(name='source',description='設定 Adventure Frontier 計分 Bot 及討論串白名單')
    @app_commands.default_permissions(manage_guild=True)
    async def source(self,inter:discord.Interaction,bot:discord.Member,channel:discord.Thread,remove:bool=False):
        if not await self.guard(inter): return
        if not bot.bot or bot.id==self.bot.user.id:
            await inter.followup.send('請選擇 Adventure Frontier Bot。'); return
        entry={'bot':bot.id,'channel':channel.id}
        async with self.role_lock:
            async with self.lock:
                sources=[s for s in self.cfg['sources'] if s!=entry]
                if not remove: sources.append(entry)
                self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,sources=sources)
        await inter.followup.send('已更新來源白名單；只會識別支援嘅戰鬥卡格式。')

    @levels.command(name='exclude',description='排除或恢復頻道／分類／身份組計分')
    @app_commands.default_permissions(manage_guild=True)
    async def exclude(self,inter:discord.Interaction,channel:discord.TextChannel|discord.VoiceChannel|discord.CategoryChannel|discord.ForumChannel|None=None,role:discord.Role|None=None,remove:bool=False):
        if not await self.guard(inter): return
        if (channel is None)==(role is None):
            await inter.followup.send('請揀一個頻道或一個身份組。'); return
        key='excluded_roles' if role else 'excluded_channels'
        target=(role or channel).id
        async with self.role_lock:
            async with self.lock:
                values=set(self.cfg[key])
                values.discard(target) if remove else values.add(target)
                self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,**{key:sorted(values)})
        self.voice_clock.clear()
        await inter.followup.send('已更新計分排除設定。')

    @levels.command(name='rates',description='設定冷卻、每日互動上限及語音 XP')
    @app_commands.default_permissions(manage_guild=True)
    async def rates(self,inter:discord.Interaction,cooldown:app_commands.Range[int,30,3600]=60,activity_cap:app_commands.Range[int,0,500]=0,voice_minutes:app_commands.Range[int,1,60]=5,voice_xp:app_commands.Range[int,1,100]=25):
        if not await self.guard(inter): return
        await self.configure(text_cooldown=cooldown,activity_cooldown=cooldown,activity_daily_cap=activity_cap,voice_interval=voice_minutes*60,voice_xp=voice_xp)
        self.voice_clock.clear()
        await inter.followup.send(embed=await self.settings_embed())

    @levels.command(name='reward',description='明確指定等級獎勵角色，避免自動猜測')
    @app_commands.default_permissions(manage_guild=True)
    async def reward(self,inter:discord.Interaction,level:app_commands.Range[int,1,10000],role:discord.Role,remove:bool=False):
        if not await self.guard(inter): return
        me=inter.guild.me
        if not remove and not reward_role_safe(role,me):
            await inter.followup.send('角色唔適合自動派發；請檢查權限及角色排序。'); return
        async with self.role_lock:
            async with self.lock:
                rewards=dict(self.cfg['rewards'])
                if remove: rewards.pop(str(level),None)
                else:
                    if str(role.id) in [str(r) for l,r in rewards.items() if l!=str(level)]:
                        await inter.followup.send('同一角色不可對應多個等級。'); return
                    rewards[str(level)]=role.id
                self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,rewards=rewards)
        await inter.followup.send('已更新獎勵；正式模式只保留最高合資格等級角色。')

    @levels.command(name='leave_policy',description='設定離開伺服器時清分或保留 XP')
    @app_commands.default_permissions(manage_guild=True)
    async def leave_policy(self,inter:discord.Interaction,clear:bool):
        if not await self.guard(inter):return
        await self.configure(clear_on_leave=clear)
        await inter.followup.send('已設定離開清分。舊紀錄會先封存供復原核對。' if clear else '已設定離開保留 XP。')

    @levels.command(name='winners',description='預覽或發佈指定期數頭三名；不刪除舊週榜')
    @app_commands.default_permissions(manage_guild=True)
    async def winners(self,inter:discord.Interaction,period:str,publish:bool=False):
        if not await self.guard(inter):return
        if not re.fullmatch(r'(?:[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])|amari-legacy)',period):
            await inter.followup.send('期數格式需係 YYYY-Www 或 amari-legacy。');return
        rows=(await asyncio.to_thread(self.ledger.leaderboard,inter.guild_id,period))[:3]
        text='\n'.join(f'{i}. <@{uid}> · {xp:,} XP' for i,(uid,xp) in enumerate(rows,1)) or '暫時未有紀錄。'
        embed=discord.Embed(title=f'🏆 {period} 頭三名',description=text)
        if not publish:
            await inter.followup.send(embed=embed,allowed_mentions=discord.AllowedMentions.none());return
        if self.cfg['mode']!='active':
            await inter.followup.send('只可喺正式模式發佈；試行只提供預覽。');return
        channel=inter.guild.get_channel(self.cfg['announcement_channel'])
        if not isinstance(channel,discord.TextChannel):
            await inter.followup.send('請先設定公告頻道。');return
        async with self.role_lock:
            if self.cfg['mode']!='active':
                await inter.followup.send('模式已改變，今次冇發佈。');return
            if not await asyncio.to_thread(self.ledger.claim_weekly_notice,inter.guild_id,period):
                await inter.followup.send('呢個期數已發佈過。');return
            try:await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await asyncio.to_thread(self.ledger.release_weekly_notice,inter.guild_id,period)
                await inter.followup.send('未能發佈，請稍後再試。');return
        await inter.followup.send('已發佈；歷史週榜保留。')

    @levels.command(name='announcements',description='設定升級公告模式及原有各級自訂字句')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(mode=[app_commands.Choice(name='只報角色階梯',value='milestones'),app_commands.Choice(name='每次升級',value='all'),app_commands.Choice(name='關閉',value='off')])
    async def announcements(self,inter:discord.Interaction,mode:app_commands.Choice[str],template:str|None=None,level:app_commands.Range[int,1,10000]|None=None,ping:bool=False):
        if not await self.guard(inter): return
        if template is not None and (not template.strip() or len(template)>1800):
            await inter.followup.send('公告字句需有 1–1800 字。');return
        async with self.role_lock:
            async with self.lock:
                changes=dict(announcement_mode=mode.value,announcement_ping=ping)
                if template is not None:
                    if level is None:changes['announcement_template']=template
                    else:changes['level_templates']={**self.cfg['level_templates'],str(level):template}
                self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,**changes)
        await inter.followup.send('已更新公告設定。支援 {user}、{user.ping}、{level}。')

    @levels.command(name='activate',description='完成舊等級核對及停用 Amari 派角色後正式接管')
    @app_commands.default_permissions(manage_guild=True)
    async def activate(self,inter:discord.Interaction,amari_rewards_disabled:bool,baseline_verified:bool,announcement:discord.TextChannel,ping:bool=False):
        if not await self.guard(inter): return
        if not REPLACEMENT_READY:
            await inter.followup.send('Auditor 未批准正式接管：舊 XP／級內進度／週榜完整快照、實際計分對照、戰鬥卡實測及回滾演練未全部驗證。請保持試行；勾選確認不能繞過。')
            return
        if not amari_rewards_disabled or not baseline_verified or not self.cfg['rewards']:
            await inter.followup.send('請先核對舊等級基準、設定獎勵角色，並停用 Amari 派角色，避免兩套系統互相覆蓋。'); return
        await self.configure(mode='active',announcement_channel=announcement.id,announcement_ping=ping)
        self.voice_clock.clear()
        await inter.followup.send('已正式接管；保留試行 XP。原有 Amari 資料不會被修改。')

    @levels.command(name='adjust',description='有原因紀錄嘅管理員 XP 調整，不影響每週榜')
    @app_commands.default_permissions(manage_guild=True)
    async def adjust(self,inter:discord.Interaction,member:discord.Member,delta:app_commands.Range[int,-1000000,1000000],reason:str):
        if not await self.guard(inter): return
        try:
            async with self.lock:
                result=await asyncio.to_thread(self.ledger.adjust,inter.guild_id,member.id,inter.user.id,delta,reason,time.time())
            if self.cfg['mode']=='active': await self.apply_rewards(member,result)
            await inter.followup.send(f'已調整：{result[0]:,} → {result[1]:,} XP。')
        except ValueError as exc: await inter.followup.send(str(exc))

    @levels.command(name='import_levels',description='預覽／一次性匯入已核對嘅 user_id,level CSV')
    @app_commands.default_permissions(manage_guild=True)
    async def import_levels(self,inter:discord.Interaction,file:discord.Attachment,commit:bool=False):
        if not await self.guard(inter): return
        if commit:
            await inter.followup.send('Auditor 已封鎖只匯入等級：會遺失級內進度，亦可能同試行 XP 重複。現時只准預覽；需先完成原始 XP／週榜快照及切換時間驗證。')
            return
        if file.size>1_000_000 or not file.filename.lower().endswith('.csv'):
            await inter.followup.send('請提供不超過 1MB 嘅 CSV。'); return
        if self.cfg['mode']=='active':
            await inter.followup.send('正式模式不可匯入，請先暫停。'); return
        try:
            raw=(await file.read()).decode('utf-8-sig')
            reader=csv.DictReader(io.StringIO(raw))
            if reader.fieldnames!=['user_id','level']: raise ValueError('欄名必須係 user_id,level。')
            records=list(reader)
            if any(set(r)!={'user_id','level'} for r in records):
                raise ValueError('每行必須只有 user_id,level 兩個欄位。')
            rows=[(int(r['user_id']),int(r['level'])) for r in records]
            if any(not inter.guild.get_member(uid) or inter.guild.get_member(uid).bot for uid,_ in rows):
                raise ValueError('名單有非現有真人成員，請先核對。')
            async with self.lock:
                count=await asyncio.to_thread(self.ledger.import_levels,inter.guild_id,rows,time.time(),commit=commit)
            await inter.followup.send(f'{"已匯入" if commit else "預覽通過"} {count} 人。保留等級基準及試行 XP；唔係 Amari 原始 XP 完整搬遷。')
        except (ValueError,UnicodeError,KeyError,TypeError,csv.Error) as exc:
            await inter.followup.send(discord.utils.escape_mentions(str(exc)))

    async def resolve_card_link(self,inter,link):
        match=re.fullmatch(r'https://discord\.com/channels/([0-9]+)/([0-9]+)/([0-9]+)/?',link.strip())
        if not match or int(match[1])!=config.GUILD_ID:
            raise ValueError('請貼上本伺服器嘅 Discord 訊息連結。')
        channel=self.bot.get_channel(int(match[2])) or await self.bot.fetch_channel(int(match[2]))
        if not isinstance(channel,discord.Thread) or channel.guild.id!=config.GUILD_ID:
            raise ValueError('訊息必須位於本伺服器嘅討論串。')
        perms=channel.permissions_for(inter.user)
        if not perms.view_channel or not perms.read_message_history:
            raise ValueError('你未有查看或讀取討論串記錄嘅權限。')
        message=await channel.fetch_message(int(match[3]))
        return channel,message

    @levels.command(name='source_card',description='直接貼 Adventure Frontier 戰鬥訊息連結設定來源，支援舊討論串')
    @app_commands.default_permissions(manage_guild=True)
    async def source_card(self,inter:discord.Interaction,message_link:str,remove:bool=False):
        if not await self.guard(inter):return
        try:
            channel,message=await self.resolve_card_link(inter,message_link)
            if not original_bot_message(message) or message.author.id==self.bot.user.id:
                raise ValueError(f'來源未加入：Bot={message.author.bot}；Webhook={bool(message.webhook_id)}；本 Bot={message.author.id==self.bot.user.id}。請選擇原始遊戲 Bot 嘅戰鬥訊息。')
            entry={'bot':message.author.id,'channel':channel.id}
            if not remove and not channel.archived:
                await channel.join()
            async with self.role_lock:
                async with self.lock:
                    sources=[s for s in self.cfg['sources'] if s!=entry]
                    if not remove:sources.append(entry)
                    self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,sources=sources)
            parsed=battle_identity([e.to_dict() for e in message.embeds]) is not None
            await inter.followup.send(f'已更新指定 Bot＋討論串來源；戰鬥格式可識別：{parsed}（未識別嘅卡片唔會計分）。模式冇改變，亦冇加分。')
        except (ValueError,discord.HTTPException) as exc:
            await inter.followup.send(str(exc) if isinstance(exc,ValueError) else '讀唔到卡片，請核對 Bot 嘅查看及讀取記錄權限。')

    @levels.command(name='inspect_link',description='直接貼戰鬥訊息連結做只讀格式驗證')
    @app_commands.default_permissions(manage_guild=True)
    async def inspect_link(self,inter:discord.Interaction,message_link:str,raw_private:bool=False):
        # Resolve before handing to the shared inspector; acknowledge only once.
        if not self.admin(inter):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True);return
        try:
            # Metadata/history fetch may take >3s; defer now, guard detects that below.
            await inter.response.defer(ephemeral=True)
            channel,message=await self.resolve_card_link(inter,message_link)
            await self.inspect.callback(self,inter,channel,str(message.id),raw_private=raw_private)
        except (ValueError,discord.HTTPException) as exc:
            await inter.followup.send(str(exc) if isinstance(exc,ValueError) else '讀唔到訊息，請核對 ID 同權限。')

    @levels.command(name='activity_check',description='只讀核對白名單近期戰鬥卡與實際加分，不補計')
    @app_commands.default_permissions(manage_guild=True)
    async def activity_check(self,inter:discord.Interaction):
        if not await self.guard(inter):return
        lines=[]
        for cid in sorted({s['channel'] for s in self.cfg['sources']})[:5]:
            try:
                channel=self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
                if not isinstance(channel,discord.Thread) or channel.guild.id!=inter.guild_id:continue
                perms=channel.permissions_for(inter.user)
                if not perms.view_channel or not perms.read_message_history:continue
                async for msg in channel.history(limit=20):
                    if {'bot':msg.author.id,'channel':cid} not in self.cfg['sources'] or not original_bot_message(msg):continue
                    identity=battle_identity([e.to_dict() for e in msg.embeds])
                    member=None
                    if identity:
                        uid,name=identity
                        if uid is None:uid=await asyncio.to_thread(self.ledger.resolve,inter.guild_id,msg.author.id,name)
                        member=msg.guild.get_member(uid) if uid else None
                        if member and (member.bot or member.name!=name):member=None
                    proof=await asyncio.to_thread(self.ledger.event_proof,inter.guild_id,f'm:{msg.id}')
                    outcome=f'已計 {proof[1]} XP → <@{proof[0]}>' if proof else '無加分紀錄（唔等於漏計；可能冷卻／上限／試行前）'
                    edited=f'｜修改 <t:{int(msg.edited_at.timestamp())}:T>' if msg.edited_at else ''
                    lines.append(f'{msg.jump_url}\n<t:{int(msg.created_at.timestamp())}:T>{edited}｜格式 {bool(identity)}｜玩家 {member.mention if member else "未對應"}｜{outcome}')
                    if len(lines)>=10:break
            except discord.HTTPException:
                lines.append('其中一個來源讀取失敗，請核對權限。')
            if len(lines)>=10:break
        await inter.followup.send(('只讀核對；冇加分、綁定或改模式。最多 10 張／各來源最近 20 訊息。\n'+'\n'.join(lines) if lines else '未找到可讀取嘅來源卡片。')[:1950],allowed_mentions=discord.AllowedMentions.none())

    async def collect_history(self,job):
        """Restartable audit only. No live XP, roles, cooldowns or current bindings are written."""
        scope=await asyncio.to_thread(self.history_audit.job,job,config.GUILD_ID)
        try:
            await asyncio.to_thread(self.history_audit.state,job,'running')
            for cid,cursor,done in scope['cursors']:
                if done:continue
                channel=self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
                if not isinstance(channel,discord.Thread) or channel.guild.id!=config.GUILD_ID:raise ValueError('Source no longer available')
                after=discord.Object(id=cursor) if cursor else datetime.fromtimestamp(scope['start'],timezone.utc)
                before=datetime.fromtimestamp(scope['cutoff'],timezone.utc)
                async for msg in channel.history(limit=None,after=after,before=before,oldest_first=True):
                    if {'bot':msg.author.id,'channel':cid} in scope['sources'] and original_bot_message(msg):
                        payload=[e.to_dict() for e in msg.embeds]
                        identity=battle_identity(payload)
                        uid=None;name=None;kind='unknown';reason='format_unrecognized'
                        if identity:
                            uid,name=identity;kind='normal' if uid else 'pet'
                            member=msg.guild.get_member(uid) if uid else None
                            reason='identity_unresolved'
                            if member and not member.bot and member.name==name:
                                reason='candidate'
                            elif member:reason='name_changed_or_mismatch'
                            elif uid:reason='departed_or_not_cached'
                        edited=msg.edited_at.timestamp() if msg.edited_at else None
                        if edited and edited-msg.created_at.timestamp()>120:reason='edited_card_history_unavailable'
                        # Preserve conflicting old associations too; eligibility is separate from identity evidence.
                        if kind=='normal' and uid and reason!='edited_card_history_unavailable':
                            await asyncio.to_thread(self.history_audit.remember_owner,job,msg.author.id,name,uid)
                        proof=await asyncio.to_thread(self.ledger.event_proof,config.GUILD_ID,f'm:{msg.id}')
                        await asyncio.to_thread(self.history_audit.record,job,message=msg.id,channel=cid,bot=msg.author.id,
                            stamp=msg.created_at.timestamp(),edited=edited,user=uid,name=name,kind=kind,reason=reason,
                            payload=payload,preview_xp=proof[1] if proof else 0)
                    # Advance only after the observation is durable; replay is idempotent.
                    cursor=msg.id
                    await asyncio.to_thread(self.history_audit.checkpoint,job,cid,cursor)
                await asyncio.to_thread(self.history_audit.checkpoint,job,cid,cursor,done=True)
            guild=self.bot.get_guild(config.GUILD_ID)
            if not guild:raise ValueError('Guild unavailable')
            current_names={m.id:self.history_audit.owner_hash(m.name) for m in guild.members if not m.bot}
            await asyncio.to_thread(self.history_audit.finalize_pets,job,current_names)
            preview=await asyncio.to_thread(self.ledger.engagement_events,config.GUILD_ID,scope['start']-60,scope['cutoff']+60)
            await asyncio.to_thread(self.history_audit.preview_events,job,preview)
            await asyncio.to_thread(self.history_audit.state,job,'complete')
        except asyncio.CancelledError:
            await asyncio.to_thread(self.history_audit.state,job,'paused')
            raise
        except (discord.HTTPException,ValueError,sqlite3.Error):
            await asyncio.to_thread(self.history_audit.state,job,'paused')
            log.warning('Historical game audit paused; resume through administrator command')

    @levels.command(name='history_audit',description='唯讀掃描2026年8月18日起遊戲紀錄；不補分；可續跑或查進度')
    @app_commands.default_permissions(manage_guild=True)
    async def history_audit_command(self,inter:discord.Interaction,status_only:bool=False):
        if not await self.guard(inter):return
        for cid in {s['channel'] for s in self.cfg['sources']}:
            channel=self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            perms=channel.permissions_for(inter.user)
            if not perms.view_channel or not perms.read_message_history:
                await inter.followup.send('需要所有來源嘅查看及讀取記錄權限。');return
        latest=await asyncio.to_thread(self.history_audit.latest,inter.guild_id)
        if status_only:
            if not latest:await inter.followup.send('未有歷史核數批次。');return
            job=latest[0]
        else:
            start=datetime.fromisoformat('2026-08-18T00:00:00+08:00').timestamp()
            job=await asyncio.to_thread(self.history_audit.start,inter.guild_id,start,time.time(),self.cfg['sources'])
        # Old paused batches retain their original scope even if live sources changed.
        scope=await asyncio.to_thread(self.history_audit.job,job,inter.guild_id)
        for cid in {s['channel'] for s in scope['sources']}:
            channel=self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            perms=channel.permissions_for(inter.user)
            if not perms.view_channel or not perms.read_message_history:
                await inter.followup.send('需要核數原始來源嘅查看及讀取記錄權限。');return
        if not status_only and (job not in self.history_tasks or self.history_tasks[job].done()):
            self.history_tasks[job]=asyncio.create_task(self.collect_history(job))
        result=await asyncio.to_thread(self.history_audit.summary,job,inter.guild_id)
        counts='\n'.join(f'{key}: {value}' for key,value in sorted(result['reasons'].items())) or '尚未讀取卡片'
        users='\n'.join(f'<@{uid}>：{count} 次候選' for uid,count in sorted(result['potential'].items(),key=lambda row:-row[1])[:15])
        await inter.followup.send((f'歷史核數 {job}｜{result["state"]}｜完成來源 {result["complete_channels"]}/{result["channels"]}\n'
            f'範圍：<t:{int(result["start"])}:F> 至 <t:{int(result["cutoff"])}:F>\n{counts}\n'
            f'遊戲內60秒重複：{result["cooldown"]}；已見試行得分：{result["preview"]}\n{users}\n'
            '以上只係遊戲候選，未核對歷史文字CD，唔係應補XP。冇改現有積分／週榜／角色；改名、離開、重用卡片會留待核對。')[:1950],allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name='inspect',description='只讀檢查指定討論串戰鬥卡可否識別，不加分')
    @app_commands.default_permissions(manage_guild=True)
    async def inspect(self,inter:discord.Interaction,channel:discord.Thread,message_id:str,raw_private:bool=False):
        if not await self.guard(inter): return
        if not message_id.isdecimal():
            await inter.followup.send('請填訊息 ID。'); return
        perms=channel.permissions_for(inter.user)
        if not perms.view_channel or not perms.read_message_history:
            await inter.followup.send('你未有讀取記錄權限。'); return
        try:
            msg=await channel.fetch_message(int(message_id))
            trusted={'bot':msg.author.id,'channel':channel.id} in self.cfg['sources'] and original_bot_message(msg)
            if not trusted:
                shape=[dict(index=i,has_title=bool(e.title),has_author=bool(e.author.name),
                    has_description=bool(e.description),field_count=len(e.fields)) for i,e in enumerate(msg.embeds)]
                await inter.followup.send(f'來源未獲信任，冇匯出內容或加分。Bot={msg.author.bot}；Webhook={bool(msg.webhook_id)}。\n```json\n'+json.dumps(shape)+'\n```');return
            payload=[e.to_dict() for e in msg.embeds]
            if raw_private:
                if not inter.user.guild_permissions.administrator:
                    await inter.followup.send('原始樣本只限 Administrator，並需查看及讀取記錄權限。');return
                projection=[]
                for item in payload:
                    fields={k:item[k] for k in ('title','description','fields') if k in item}
                    if 'author' in item:fields['author']={'name':item['author'].get('name','')}
                    projection.append(fields)
                compact=re.sub(r'<a?:[A-Za-z0-9_]+:[0-9]+>','',json.dumps(projection,ensure_ascii=False,separators=(',',':')))
                preview=('\n```json\n'+compact+'\n```') if len(compact)<1600 else ''
                await inter.followup.send('私人原始 Bot 格式樣本，可能包含玩家 ID／名稱；只讀，冇加分。'+preview,
                    file=discord.File(io.BytesIO(json.dumps(dict(embeds=payload),ensure_ascii=False,indent=2).encode()),filename='battle_raw_private.json'))
                return
            identity=battle_identity(payload)
            if not identity:
                shape=[dict(index=i,has_title='title' in e,has_author='author' in e,
                    has_description='description' in e,field_count=len(e.get('fields',[]))) for i,e in enumerate(payload)]
                await inter.followup.send('未識別格式，只回傳結構，冇匯出文字或玩家 ID。\n```json\n'+json.dumps(shape)+'\n```');return
            uid,name=identity if identity else (None,None)
            resolved=msg.guild.get_member(uid) if uid else None
            if identity and not uid:
                saved=await asyncio.to_thread(self.ledger.resolve,inter.guild_id,msg.author.id,name)
                resolved=msg.guild.get_member(saved) if saved else None
            fixtures=[]
            for index,embed in enumerate(msg.embeds):
                raw=embed.to_dict();safe={k:raw[k] for k in ('title','description','fields','author') if k in raw}
                if 'author' in safe:safe['author']={'name':safe['author'].get('name','')}
                text=json.dumps(safe,ensure_ascii=False)
                text=re.sub(r'<a?:[A-Za-z0-9_]+:[0-9]+>','',text)
                text=re.sub(r'<@!?[0-9]+>','<@10>',text)
                if name:text=text.replace(name,'player')
                elif index==0:
                    for m in msg.guild.members:
                        if len(m.name)>2:text=text.replace(m.name,'player')
                fixtures.append(json.loads(text))
            proof=json.dumps(dict(embeds=fixtures),ensure_ascii=False,indent=2).encode()
            compact=json.dumps(fixtures,ensure_ascii=False,separators=(',',':'))
            preview=('\n```json\n'+compact+'\n```') if len(compact)<1600 else ''
            await inter.followup.send(f'白名單來源：{trusted}\n可識別格式：{identity is not None}\n玩家可對應：{resolved is not None}\n只讀檢查，冇加分；附件已替換已識別玩家及 mention；用作公開 fixture 前仍需核對。'+preview,
                file=discord.File(io.BytesIO(proof),filename='battle_fixture.json'))
        except discord.HTTPException:
            await inter.followup.send('讀唔到訊息，請檢查 ID 同權限。')


async def setup(bot):
    await bot.add_cog(CommunityLevels(bot))
