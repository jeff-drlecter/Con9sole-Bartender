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
import uuid
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from features.community_levels import Ledger, REWARD_NAMES, battle_identity, calendar, level_for, threshold, render_notice
from features.level_history import HistoryAudit
from features.level_activation import readiness as activation_readiness,commit as activation_commit,role_plan as activation_role_plan,pending_count as activation_pending
from features.level_role_drill import restore as restore_role_drill
from features.level_migration import create_backup
from features.level_bonus import prepare as prepare_bonus,apply as apply_bonus
from features.level_migration import digest as manifest_digest
from features.level_baseline import stage_public,build_manifest,save_plan,load_plan,apply_plan,role_mapping
from core.storage_paths import DATA_DIR
from core.sqlite_storage import connect_sqlite

log = logging.getLogger(__name__)
GUILD = discord.Object(id=config.GUILD_ID)
# Release gate: turn on only after the evidence checklist in LEVEL_AUDIT.md passes.
REPLACEMENT_READY = True
# Owner-authorized historical compensation uses the existing ordinary 1-XP rate.
HISTORICAL_BASE_POLICY_ACCEPTED = True


def reward_role_safe(role, me):
    powers = ('administrator', 'manage_guild', 'manage_roles', 'kick_members',
              'ban_members', 'moderate_members', 'manage_channels', 'manage_webhooks',
              'manage_messages', 'manage_threads', 'mention_everyone')
    return not (role.is_default() or role.managed or role >= me.top_role or
                any(getattr(role.permissions, p, False) for p in powers))



def replacement_preflight(guild,rewards,announcement=None):
    """Require all verified roles and current Discord permissions before activation."""
    expected=role_mapping([dict(id=r.id,name=r.name) for r in guild.roles])
    actual={int(level):int(rid) for level,rid in rewards.items()}
    if actual!=expected:raise ValueError('獎勵需完整對應全部10個已核對等級角色。')
    me=guild.me
    if not me or not me.guild_permissions.manage_roles:raise ValueError('Bot 缺少管理角色權限。')
    for rid in actual.values():
        role=guild.get_role(rid)
        if role is None or not reward_role_safe(role,me):raise ValueError('等級角色失效、權限不安全或高於 Bot。')
    if announcement is not None:
        perms=announcement.permissions_for(me)
        if not (perms.view_channel and perms.send_messages):raise ValueError('Bot 未能查看／發送升級公告。')
    return actual


def eligible(member, channel, cfg):
    if member.bot or any(r.id in cfg['excluded_roles'] for r in member.roles):
        return False
    ids = {channel.id, getattr(channel,'parent_id',None), getattr(channel,'category_id',None)}
    return not ids.intersection(cfg['excluded_channels'])


def afk_id(guild):
    return getattr(guild.afk_channel,'id',None)


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
        self.history_channels={}
        self.history_discovery=set()
        self.role_restore_after=0
        self.departing_members={}

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
                       description=f"狀態：**{cfg['mode']}**\n"+({'active':'已正式計分及維護等級角色；公告按設定發送。','preview':'試行計分中，暫不派角色或發升級公告。','off':'計分已暫停，現有 XP 會保留。'}[cfg['mode']]))
        cap_note=f"Bot 活動每日最多 {cfg['activity_daily_cap']} 次" if cfg['activity_daily_cap'] else 'Bot 活動冇額外每日上限'
        e.add_field(name='文字／Bot 活動',value=f"共用 {max(cfg['text_cooldown'],cfg['activity_cooldown'])} 秒冷卻；每次 1 XP\n{cap_note}",inline=False)
        e.add_field(name='語音',value=f"最少 2 位有效真人；每 {cfg['voice_interval']//60} 分鐘 {cfg['voice_xp']} XP\n排除 AFK、耳聾及舞台聽眾",inline=False)
        e.add_field(name='其他',value=f"Booster 文字／活動 ×{cfg['booster_multiplier']}\n來源 {len(cfg['sources'])} 個｜角色獎勵 {len(cfg['rewards'])} 個\n離開清分 {cfg['clear_on_leave']}；每週一香港時間自動開始新榜",inline=False)
        if cfg['mode']=='active':
            pending=await asyncio.to_thread(activation_pending,self.ledger,config.GUILD_ID)
            e.add_field(name='角色核對',value='已完成' if not pending else f'剩餘 {pending} 人，會自動續行。',inline=False)
        e.set_footer(text='已正式接管等級、角色及公告。' if cfg['mode']=='active' else ('已完成實測；接管前需停用 Amari 派角色及公告。' if REPLACEMENT_READY else '試行驗收中；基線已搬遷，正式角色及公告尚未開啟。'))
        return e

    async def credit(self,member,channel,source,event,now=None):
        if not member or member.guild.id!=config.GUILD_ID or self.cfg['mode']=='off' or not eligible(member,channel,self.cfg):
            return
        multiplier=self.cfg['booster_multiplier'] if member.premium_since else 1
        stamp = time.time() if now is None else now
        async with self.lock:
            if self.cfg['mode']=='off' or not eligible(member,channel,self.cfg):return
            if not await self.ensure_current_membership(member,time.time()):return
            joined=self.member_joined(member)
            if joined is not None and now is not None and now<joined:return
            if source=='voice':
                cohort=voice_members(channel,self.cfg) if channel.id!=afk_id(channel.guild) else []
                if not self.gateway_confirmed or not self.bot.is_ready() or len(cohort)<2 or member.id not in {m.id for m in cohort}:
                    return
            result=await asyncio.to_thread(self.ledger.award,config.GUILD_ID,member.id,source,event,
                                          stamp,multiplier=multiplier)
        if result and self.cfg['mode']=='active':
            from features.daily_bar import get_daily_bar_task
            if source in ('text', 'voice') and get_daily_bar_task(member.guild.id,
                    now=datetime.fromtimestamp(stamp, timezone.utc)).key == source:
                from types import SimpleNamespace
                try:
                    await self.task_credit(SimpleNamespace(user=member, guild_id=member.guild.id, channel=channel), now=stamp)
                except Exception:
                    log.exception('Daily task reward remains retryable: user=%s', member.id)
            await self.apply_rewards(member,result)
        return result

    @staticmethod
    def member_joined(member):
        joined=getattr(member,'joined_at',None)
        return joined.timestamp() if isinstance(joined,datetime) else None

    async def ensure_current_membership(self,member,now):
        """Caller holds ledger lock; reject queued actions from an older membership."""
        joined=self.member_joined(member)
        if joined is None:return not isinstance(member,discord.Member)
        get_member=getattr(member.guild,'get_member',None)
        current=get_member(member.id) if callable(get_member) else member
        if current is None or self.member_joined(current)!=joined:return False
        if self.cfg['mode']=='active':
            return await asyncio.to_thread(self.ledger.ensure_membership,member.guild.id,member.id,joined,now,
                previous_join=self.departing_members.get(member.id))
        return True

    async def drink_credit(self,interaction):
        return await self.action_credit(interaction,f'drink:{interaction.id}')

    async def daily_task_status(self, interaction, *, now=None):
        from features.daily_bar import get_daily_bar_task, get_daily_bar_completion
        from datetime import datetime, timezone
        stamp = time.time() if now is None else now
        current = datetime.fromtimestamp(stamp, timezone.utc)
        task = get_daily_bar_task(interaction.guild_id, now=current)
        completion = await asyncio.to_thread(get_daily_bar_completion, interaction.guild_id, interaction.user.id, now=current)
        joined = self.member_joined(interaction.user) or 0
        valid_completion = completion is not None and completion['task_key'] == task.key and datetime.fromisoformat(completion['completed_at']).timestamp() >= joined
        progress = task.target if valid_completion else 0
        if task.key in ('text', 'voice'):
            progress = min(task.target, await asyncio.to_thread(self.ledger.daily_task_count,
                interaction.guild_id, interaction.user.id, task.key, stamp, joined=joined))
        proof = await asyncio.to_thread(self.ledger.event_proof, interaction.guild_id,
            f'daily-task:{calendar(stamp)[0]}:{interaction.user.id}')
        if proof:
            reward = '✅ 已入帳 +5 XP（計入本週排名）'
        elif valid_completion or progress >= task.target:
            reward = '⏳ 已完成，獎勵待核對；符合計分資格後重新整理即可重試。'
        else:
            reward = '🎁 完成額外 +5 XP；每人每日一次。'
        if self.cfg.get('mode') != 'active' and not proof:
            reward += '\n等級系統暫未正式計分，現時不會發放 XP。'
        return dict(progress=progress, reward_state=reward, now=current)

    async def task_credit(self, interaction, *, now=None):
        from features.daily_bar import get_daily_bar_task, get_daily_bar_completion, complete_daily_bar_task
        from datetime import datetime, timezone
        now = time.time() if now is None else now
        member = interaction.user
        if not member or not interaction.guild_id or member.guild.id != config.GUILD_ID:
            return None
        current = datetime.fromtimestamp(now, timezone.utc)
        async with self.lock:
            if self.cfg['mode'] != 'active' or not eligible(member, interaction.channel, self.cfg):
                return None
            if not await self.ensure_current_membership(member, now):
                return None
            joined = self.member_joined(member) or 0
            task = get_daily_bar_task(interaction.guild_id, now=current)
            if task.key in ('text', 'voice'):
                progress = await asyncio.to_thread(self.ledger.daily_task_count, interaction.guild_id,
                    member.id, task.key, now, joined=joined)
                if progress >= task.target:
                    await asyncio.to_thread(complete_daily_bar_task, guild_id=interaction.guild_id,
                        user_id=member.id, feature_key=task.key, joined_since=joined, now=current)
            completed = await asyncio.to_thread(get_daily_bar_completion, interaction.guild_id, member.id, now=current)
            if completed is None or completed['task_key'] != task.key or datetime.fromisoformat(completed['completed_at']).timestamp() < joined:
                return None
            result = await asyncio.to_thread(self.ledger.daily_bonus, interaction.guild_id, member.id, calendar(now)[0], now)
        if result:
            await self.apply_rewards(member, result)
            return '📅 每日任務獎勵 +5 XP！'
        return None

    async def action_credit(self,interaction,event):
        result=await self.credit(interaction.user,interaction.channel,'activity',f'i:{event}')
        if not result or self.cfg['mode']!='active':
            return None
        before,after=result
        text=f'會員 XP +{after-before}'
        if level_for(after)>level_for(before):
            text+=f' · 升至 Lv.{level_for(after)}！'
        return text

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
            async with self.lock:
                if not await self.ensure_current_membership(member,time.time()):return False
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
        if any(role is None for _,role in pairs):
            log.warning('Configured level role missing; reconciliation blocked without changing roles')
            return False
        if isinstance(member,discord.Member) and any(not reward_role_safe(role,member.guild.me) for _,role in pairs):
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
        members=[] if channel.id == afk_id(channel.guild) else voice_members(channel,self.cfg)
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
        joined=self.member_joined(member)
        self.departing_members[member.id]=joined
        async with self.role_lock:
            async with self.lock:
                if self.cfg['mode']=='active' and self.cfg['clear_on_leave']:
                    current=member.guild.get_member(member.id) if callable(getattr(member.guild,'get_member',None)) else None
                    if current is not None and self.member_joined(current)!=joined:
                        await self.ensure_current_membership(current,time.time())
                    await asyncio.to_thread(self.ledger.member_left,member.guild.id,member.id,time.time(),joined)

    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.bot or member.guild.id!=config.GUILD_ID or self.cfg['mode']!='active':return
        async with self.lock:
            await self.ensure_current_membership(member,time.time())

    async def reconcile_memberships(self):
        if self.cfg.get('mode')!='active':return
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild:return
        async with self.lock:
            for member in getattr(guild,'members',[]):
                if not member.bot:await self.ensure_current_membership(member,time.time())

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
        await self.reconcile_memberships()
        await self.reconcile_sources()

    @commands.Cog.listener()
    async def on_resumed(self):
        self.gateway_confirmed=True
        self.voice_clock.clear()
        await self.reconcile_memberships()
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
        pending=await asyncio.to_thread(self.ledger.pending_roles,config.GUILD_ID,20)
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
        if not guild or not self.bot.is_ready() or not self.gateway_confirmed:
            self.voice_clock.clear()
            return
        await self.retry_role_drill(guild)
        if self.cfg.get('mode')=='off':
            self.voice_clock.clear()
            return
        try:
            async with asyncio.timeout(5):await self.repair_pending()
        except TimeoutError:
            log.warning('Role repair timed out; queued jobs retained and voice timer continues')
        now=time.monotonic()
        for channel in guild.voice_channels+guild.stage_channels:
            members=self.reconcile_voice_members(channel,now)
            for member in members:
                if not self.gateway_confirmed or not self.bot.is_ready() or self.cfg.get('mode')=='off':
                    self.voice_clock.clear()
                    return
                key=(channel.id,member.id)
                start=self.voice_clock.get(key)
                current=voice_members(channel,self.cfg) if channel.id!=afk_id(channel.guild) else []
                if start is None or len(current)<2 or member.id not in {m.id for m in current}:
                    continue
                if now-start>=self.cfg['voice_interval']:
                    await self.credit(member,channel,'voice',f'v:{channel.id}:{member.id}:{int(time.time())}')
                    # A listener may have removed/replaced clocks while the DB write awaited.
                    if not self.gateway_confirmed or not self.bot.is_ready() or self.cfg.get('mode')=='off':
                        self.voice_clock.clear()
                        return
                    if self.voice_clock.get(key)==start:
                        current=voice_members(channel,self.cfg) if channel.id!=afk_id(channel.guild) else []
                        if len(current)>=2 and member.id in {m.id for m in current}:
                            self.voice_clock[key]=now
            # Reconcile current membership, preserving clocks listeners added during awaits.
            self.reconcile_voice_members(channel,time.monotonic())
        channel_ids={c.id for c in guild.voice_channels+guild.stage_channels}
        for key in list(self.voice_clock):
            if key[0] not in channel_ids:self.voice_clock.pop(key,None)

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

    async def leaderboard_entry(self,inter):
        await self.leaderboard.callback(self,inter,weekly=False,page=1,period=None)

    async def weekly_entry(self,inter):
        await self.leaderboard.callback(self,inter,weekly=True,page=1,period=None)

    @levels.command(name='voice_check',description='唯讀核對現有語音出席、排除原因、計時及語音XP')
    @app_commands.default_permissions(manage_guild=True)
    async def voice_check(self,inter:discord.Interaction):
        if not await self.guard(inter):return
        task=self.voice_tick.get_task()
        error=None
        if task and task.done() and not task.cancelled():
            failure=task.exception()
            if failure:error=f'{type(failure).__name__}: {str(failure)[:180]}'
        lines=[f'模式 {self.cfg["mode"]}｜Gateway {self.gateway_confirmed}｜Ready {self.bot.is_ready()}｜計時工作 {self.voice_tick.is_running()}｜Failed {self.voice_tick.failed()}',
            f'語音 {self.cfg["voice_xp"]} XP/{self.cfg["voice_interval"]} 秒；只讀，不重設計時。']
        if error:lines.append('工作錯誤：'+error)
        now=time.monotonic()
        for channel in inter.guild.voice_channels+inter.guild.stage_channels:
            humans=[m for m in channel.members if not m.bot]
            if not humans or not channel.permissions_for(inter.user).view_channel:continue
            valid=voice_members(channel,self.cfg) if channel.id!=afk_id(inter.guild) else []
            lines.append(f'{channel.name}：真人 {len(humans)}，有效 {len(valid)}')
            for member in humans:
                state=member.voice
                reasons=[]
                if not eligible(member,channel,self.cfg):reasons.append('排除頻道／角色')
                if channel.id==afk_id(inter.guild):reasons.append('AFK頻道')
                if state:
                    if state.self_deaf or state.deaf:reasons.append('耳聾')
                    if state.afk:reasons.append('AFK')
                    if state.suppress:reasons.append('舞台聽眾')
                else:reasons.append('未有VoiceState')
                clock=self.voice_clock.get((channel.id,member.id))
                elapsed='未開始' if clock is None else f'{max(0,int(now-clock))}秒'
                profile=await asyncio.to_thread(self.ledger.profile,inter.guild_id,member.id)
                lines.append(f'<@{member.id}>：{",".join(reasons) or "有效"}；計時 {elapsed}；語音XP {profile["voice"]}')
        await inter.followup.send('\n'.join(lines)[:1900],allowed_mentions=discord.AllowedMentions.none(),ephemeral=True)

    @levels.command(name='rank',description='查看等級、升級進度及 XP 來源')
    async def rank(self,inter:discord.Interaction,member:discord.Member|None=None):
        await inter.response.defer(ephemeral=True,thinking=True)
        target=member or inter.user
        p=await asyncio.to_thread(self.ledger.profile,inter.guild_id,target.id)
        position=await asyncio.to_thread(self.ledger.rank_position,inter.guild_id,target.id)
        level=level_for(p['total'])
        earned=p['total']-threshold(level)
        required=threshold(level+1)-threshold(level)
        filled=min(10,earned*10//required)
        e=discord.Embed(title='🎖️ 我的會員卡' if target.id==inter.user.id else '🎖️ 會員卡',description=f'{target.mention}\n**Lv.{level}** · {p["total"]:,} XP\n'+ '▰'*filled+'▱'*(10-filled)+f' {earned:,}/{required:,}',color=0xe5b65b)
        e.add_field(name='總榜排名',value=str(position) if position else '未上榜')
        e.add_field(name='XP 來源',value=f"文字 {p['text']:,}｜互動 {p['activity']:,}｜語音 {p['voice']:,}\n匯入基準 {p['imported']:,}",inline=False)
        e.set_footer(text=f'模式：{self.cfg["mode"]}｜'+('已正式接管；管理調整另計' if self.cfg['mode']=='active' else '試行／暫停資料；管理調整另計'))
        from features.collection_milestones import collection_snapshot
        from features.drink_views import MemberCardView
        try:
            collection=await asyncio.to_thread(collection_snapshot,inter.guild_id,target.id)
            e.add_field(name='🍾 酒吧收藏',value=f'已收藏 {len(collection["names"]):,} 款酒',inline=False)
            title=next((a['label'] for a in collection['awards'] if a['milestone_id']==collection['selected']),None)
            if title:
                titles=self.bot.get_cog('TitleRoles')
                status=await titles.status(inter.guild,target.id,collection) if titles else 'Role 同步功能未載入'
                e.add_field(name='🏅 展示稱號',value=discord.utils.escape_markdown(title)+'\n'+status,inline=False)
        except Exception:
            log.exception('Could not load member card collection')
            e.add_field(name='🍾 酒吧收藏',value='暫時讀取唔到，請稍後再試。',inline=False)
        await inter.followup.send(embed=e,view=MemberCardView(),allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name='leaderboard',description='查看總榜或香港時間每週榜')
    async def leaderboard(self,inter:discord.Interaction,weekly:bool=False,page:app_commands.Range[int,1,10000]=1,period:str|None=None):
        await inter.response.defer(ephemeral=True,thinking=True)
        if period and not re.fullmatch(r'(?:[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])|amari-legacy)',period):
            await inter.followup.send('期數請填 YYYY-Www，或 amari-legacy。'); return
        week=period or (calendar(time.time())[1] if weekly else None)
        rows=await asyncio.to_thread(self.ledger.leaderboard,inter.guild_id,week,page)
        text='\n'.join(f'{i}. <@{uid}> · {points:,} XP' for i,(uid,points) in enumerate(rows,(page-1)*10+1)) or '暫時未有紀錄。'
        from features.drink_views import LevelBoardView
        embed=discord.Embed(title='🏆 '+(f'期數 {week}' if week else '等級總榜'),description=text)
        embed.set_footer(text=f'第 {page} 頁｜會員經驗排名')
        await inter.followup.send(embed=embed,view=LevelBoardView(self,week,page,len(rows)==10),allowed_mentions=discord.AllowedMentions.none())

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
        await self.reconcile_sources()
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
                if self.cfg['mode']=='active':
                    try:
                        channel=inter.guild.get_channel(self.cfg['announcement_channel'])
                        if not isinstance(channel,discord.TextChannel):raise ValueError('公告頻道不存在。')
                        replacement_preflight(inter.guild,rewards,channel)
                    except ValueError as exc:
                        await inter.followup.send(str(exc));return
                self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,rewards=rewards)
        await inter.followup.send('已更新獎勵；正式模式只保留最高合資格等級角色。')

    @levels.command(name='rewards_sync',description='核對全部10個既有等級角色；只設定對應，不派角色')
    @app_commands.default_permissions(manage_guild=True)
    async def rewards_sync(self,inter:discord.Interaction,commit:bool=False):
        if not await self.guard(inter):return
        try:
            async with self.role_lock:
                async with self.lock:
                    if self.cfg['mode']=='active':raise ValueError('請先暫停正式模式。')
                    mapping=role_mapping([dict(id=r.id,name=r.name) for r in inter.guild.roles])
                    replacement_preflight(inter.guild,mapping)
                    if commit:
                        self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,rewards={str(k):v for k,v in mapping.items()})
            lines='\n'.join(f'Lv{level} → <@&{rid}>' for level,rid in sorted(mapping.items()))
            await inter.followup.send(('已設定全部10個獎勵對應；未派角色。' if commit else '角色對應預覽；未改設定。')+'\n'+lines,allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:await inter.followup.send(str(exc))

    @levels.command(name='role_drill',description='核對測試帳號既有等級角色；選填演練移除並立即還原')
    @app_commands.default_permissions(manage_guild=True)
    async def role_drill_command(self,inter:discord.Interaction,member:discord.Member,run:bool=False):
        if not await self.guard(inter):return
        try:
            async with self.role_lock:
                async with self.lock:
                    if self.cfg['mode']=='active':raise ValueError('演練只可喺試行／暫停模式。')
                    if member.bot:raise ValueError('只可用真人測試帳號。')
                    mapping=replacement_preflight(inter.guild,self.cfg['rewards'])
                    current=await inter.guild.fetch_member(member.id)
                    original=[r for r in current.roles if r.id in set(mapping.values())]
                    if len(original)!=1:raise ValueError('演練帳號需有且只有一個已核對等級角色。')
                    if not run:
                        await inter.followup.send(f'只讀預覽：<@{member.id}> 目前持有 <@&{original[0].id}>。演練只移除呢個既有等級角色再立即還原；不改XP或其他角色。',allowed_mentions=discord.AllowedMentions.none(),ephemeral=True);return
                    prior=self.cfg.get('role_drill')
                    if prior and prior['state'] in ('pending','rollback'):raise ValueError('上一次演練尚待還原；唔會開始另一批。')
                    if current.joined_at is None:raise ValueError('測試帳號加入時間未能核對。')
                    batch=uuid.uuid4().hex[:16];backup=DATA_DIR/'level_backups'/f'roles-{batch}.sqlite3'
                    marker=dict(id=batch,user=member.id,joined_at=current.joined_at.timestamp(),mapping={str(k):v for k,v in mapping.items()},roles=[r.id for r in original],state='pending',actor=inter.user.id,backup_path=str(backup),backup_sha=None,remove_succeeded=False,remove_observed=False)
                    self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,role_drill=marker)
                    sha=await asyncio.to_thread(create_backup,self.ledger,backup)
                    marker={**marker,'backup_sha':sha}
                    self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,role_drill=marker)
                    try:
                        await current.remove_roles(*original,reason='Con9sole 測試帳號角色還原演練')
                        removed=await inter.guild.fetch_member(member.id)
                        if removed.joined_at!=current.joined_at or any(r.id in {o.id for o in original} for r in removed.roles):raise ValueError('未能確認原角色已移除；會先還原。')
                        marker={**marker,'remove_succeeded':True,'remove_observed':True}
                        self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,role_drill=marker)
                    finally:
                        try:await restore_role_drill(inter.guild,self.ledger,marker,reward_role_safe)
                        finally:self.cfg=await asyncio.to_thread(self.ledger.settings,inter.guild_id)
            await inter.followup.send('測試角色已移除及還原，現有角色核對一致；已備份，冇改XP／其他角色。',ephemeral=True)
        except (ValueError,discord.HTTPException,sqlite3.Error) as exc:
            await inter.followup.send(('演練未完成；如已移除會保留還原工作：'+str(exc))[:1500],ephemeral=True)

    async def retry_role_drill(self,guild):
        if time.monotonic()<self.role_restore_after:return
        async with self.role_lock:
            async with self.lock:
                self.cfg=await asyncio.to_thread(self.ledger.settings,guild.id)
                marker=self.cfg.get('role_drill')
                if not marker or marker['state'] not in ('pending','rollback'):return
                try:
                    async with asyncio.timeout(8):
                        await restore_role_drill(guild,self.ledger,marker,reward_role_safe)
                except Exception:
                    self.role_restore_after=time.monotonic()+60
                    log.exception('Test role restore remains pending; voice timer continues')
                finally:self.cfg=await asyncio.to_thread(self.ledger.settings,guild.id)

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
            publication=await asyncio.to_thread(self.ledger.begin_weekly_publication,inter.guild_id,period)
            if not publication['claimed']:
                await inter.followup.send('呢個期數已發佈過。' if publication['state']=='sent' else
                    '呢個期數送出結果未能確認；請管理員核對原頻道，暫時唔會自動重發。');return
            try:
                message=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            except (Exception,asyncio.CancelledError) as exc:
                definite=isinstance(exc,discord.HTTPException) and 400<=exc.status<500 and exc.status!=408
                await asyncio.shield(asyncio.to_thread(self.ledger.finish_weekly_publication,inter.guild_id,period,
                    publication['attempt'],'failed' if definite else 'uncertain'))
                if isinstance(exc,asyncio.CancelledError):raise
                await inter.followup.send('未能發佈，可以稍後再試。' if definite else
                    '發佈結果未能確認；請先核對原頻道，暫時唔會自動重發。');return
            mid=getattr(message,'id',None)
            await asyncio.to_thread(self.ledger.finish_weekly_publication,inter.guild_id,period,
                publication['attempt'],'sent',mid if type(mid) is int else None)
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

    @levels.command(name='activation_preview',description='只讀預覽全員等級角色新增／移除／保留／暫緩；不改角色')
    @app_commands.default_permissions(manage_guild=True)
    async def activation_preview_command(self,inter:discord.Interaction):
        if not await self.guard(inter):return
        try:
            if inter.guild.member_count and len(inter.guild.members)<inter.guild.member_count:raise ValueError('成員清單未齊。')
            replacement_preflight(inter.guild,self.cfg['rewards'])
            managed=set(self.cfg['rewards'].values())
            members=[dict(user=m.id,roles=sorted(r.id for r in m.roles if r.id in managed)) for m in inter.guild.members if not m.bot]
            plan=await asyncio.to_thread(activation_role_plan,self.ledger,inter.guild_id,self.cfg['rewards'],members)
            counts=plan['counts']
            await inter.followup.send(f'角色接管預覽：變更 {counts["change"]}｜保留 {counts["keep"]}｜未有profile保持不動 {counts["untouched"]}｜暫緩 {counts["hold"]}。\n摘要：{plan["digest"]}\n有暫緩項目唔會啟動；缺少積分唔會當0XP清除角色。',file=discord.File(io.BytesIO(json.dumps(plan,ensure_ascii=False,indent=2).encode()),filename='activation_roles_private.json'),allowed_mentions=discord.AllowedMentions.none(),ephemeral=True)
        except ValueError as exc:await inter.followup.send(str(exc),ephemeral=True)

    @levels.command(name='activate',description='完成舊等級核對及停用 Amari 派角色後正式接管')
    @app_commands.default_permissions(manage_guild=True)
    async def activate(self,inter:discord.Interaction,amari_rewards_disabled:bool,baseline_verified:bool,announcement:discord.TextChannel,ping:bool=False,preview_digest:str|None=None):
        if not await self.guard(inter): return
        if not REPLACEMENT_READY:
            await inter.followup.send('正式派角色／公告尚未通過驗收：基線搬遷、實際計分對照及還原演練需完成驗收。簡化角色基線可用 baseline 指令另行處理。')
            return
        if not amari_rewards_disabled or not baseline_verified or not self.cfg['rewards']:
            await inter.followup.send('請先核對舊等級基準、設定獎勵角色，並停用 Amari 派角色，避免兩套系統互相覆蓋。'); return
        try:
            async with self.role_lock:
                async with self.lock:
                    if self.cfg['mode']=='active':
                        await inter.followup.send('已正式接管，唔會重複建立切換。');return
                    replacement_preflight(inter.guild,self.cfg['rewards'],announcement)
                    if not self.gateway_confirmed or not self.bot.is_ready():raise ValueError('Gateway 未準備好，暫時唔接管。')
                    if inter.guild.member_count and len(inter.guild.members)<inter.guild.member_count:raise ValueError('成員清單未齊，暫時唔接管。')
                    now=time.time()
                    evidence=await asyncio.to_thread(activation_readiness,self.ledger,inter.guild_id,self.cfg,now)
                    managed=set(self.cfg['rewards'].values())
                    members=[dict(user=m.id,roles=sorted(r.id for r in m.roles if r.id in managed)) for m in inter.guild.members if not m.bot]
                    members.sort(key=lambda row:row['user'])
                    backup=DATA_DIR/'level_backups'/f'active-{uuid.uuid4().hex[:16]}.sqlite3'
                    intent=dict(actor=inter.user.id,stamp=now,members=members,mapping=self.cfg['rewards'],prior_mode=self.cfg['mode'],backup_path=str(backup))
                    self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,activation_intent=intent)
                    sha=await asyncio.to_thread(create_backup,self.ledger,backup)
                    changes=dict(announcement_channel=announcement.id,announcement_ping=ping,backup_path=str(backup),backup_sha=sha)
                    replacement_preflight(inter.guild,self.cfg['rewards'],announcement)
                    current=[dict(user=m.id,roles=sorted(r.id for r in m.roles if r.id in managed)) for m in inter.guild.members if not m.bot]
                    current.sort(key=lambda row:row['user'])
                    if current!=members:raise ValueError('成員角色喺備份期間改變，請重新核對。')
                    self.cfg=await asyncio.to_thread(activation_commit,self.ledger,inter.guild_id,changes,members,evidence,now,preview_digest)
        except (ValueError,sqlite3.Error) as exc:
            await inter.followup.send(str(exc));return
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
            await inter.followup.send('請用 baseline 混合搬遷流程：完整公開榜優先，其餘按最高等級角色起點；會先備份及封存試行重疊分數。舊 CSV 路徑唔直接提交。')
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
        inventory=await asyncio.to_thread(self.ledger.engagement_inventory,inter.guild_id,scope['start']-60,scope['cutoff']+60)
        result=await asyncio.to_thread(self.history_audit.summary,job,inter.guild_id,inventory)
        counts='\n'.join(f'{key}: {value}' for key,value in sorted(result['reasons'].items())) or '尚未讀取卡片'
        users='\n'.join(f'<@{uid}>：{count} 次候選' for uid,count in sorted(result['potential'].items(),key=lambda row:-row[1])[:15])
        await inter.followup.send((f'歷史核數 {job}｜{result["state"]}｜完成來源 {result["complete_channels"]}/{result["channels"]}\n'
            f'範圍：<t:{int(result["start"])}:F> 至 <t:{int(result["cutoff"])}:F>\n{counts}\n'
            f'遊戲內60秒重複：{result["cooldown"]}；目前仍保留得分：{result["preview"]}；已封存須重新對帳：{result["archived_candidates"]}\n{users}\n'
            '以上只係遊戲候選，未核對歷史文字CD，唔係應補XP。冇改現有積分／週榜／角色；改名、離開、重用卡片會留待核對。')[:1950],allowed_mentions=discord.AllowedMentions.none())

    async def collect_history_text(self,job):
        """Read-only, restartable text timing evidence; never store message bodies."""
        try:
            scope=await asyncio.to_thread(self.history_audit.job,job,config.GUILD_ID)
            text=await asyncio.to_thread(self.history_audit.text_scope,job)
            policy=text['policy'];users=set(policy['users'])
            await asyncio.to_thread(self.history_audit.text_state,job,'running')
            for cid,cursor,done in text['cursors']:
                if done:continue
                channel=self.bot.get_channel(cid) or self.history_channels.get(cid) or await self.bot.fetch_channel(cid)
                if channel.guild.id!=config.GUILD_ID:raise ValueError('Foreign text scope')
                perms=channel.permissions_for(channel.guild.me)
                if not (perms.view_channel and perms.read_message_history):raise ValueError('Text history permission missing')
                after=discord.Object(id=cursor) if cursor else datetime.fromtimestamp(scope['start']-policy['cooldown'],timezone.utc)
                before=datetime.fromtimestamp(policy['cutoff'],timezone.utc)
                pending=[];count=0
                async for msg in channel.history(limit=None,after=after,before=before,oldest_first=True):
                    if msg.author.id in users and not msg.author.bot and (msg.content.strip() or msg.attachments):
                        pending.append((msg.id,msg.author.id,msg.created_at.timestamp()))
                    cursor=msg.id;count+=1
                    if count%100==0:
                        await asyncio.to_thread(self.history_audit.text_checkpoint,job,cid,cursor,pending)
                        pending=[]
                await asyncio.to_thread(self.history_audit.text_checkpoint,job,cid,cursor,pending,True)
            await asyncio.to_thread(self.history_audit.text_state,job,'complete')
        except asyncio.CancelledError:
            await asyncio.to_thread(self.history_audit.text_state,job,'paused');raise
        except (discord.HTTPException,ValueError,sqlite3.Error):
            await asyncio.to_thread(self.history_audit.text_state,job,'paused')
            log.warning('Historical text timing audit paused; no XP changed')

    @levels.command(name='history_text',description='唯讀核對歷史文字及遊戲共用CD；不補分，可續跑')
    @app_commands.default_permissions(manage_guild=True)
    async def history_text_command(self,inter:discord.Interaction,status_only:bool=False):
        if not await self.guard(inter):return
        discovery_job=None
        try:
            latest=await asyncio.to_thread(self.history_audit.latest,inter.guild_id)
            if not latest:raise ValueError('請先完成 history_audit。')
            job=latest[0];scope=await asyncio.to_thread(self.history_audit.job,job,inter.guild_id)
            if scope['state']!='complete':raise ValueError('遊戲核數未完成。')
            if not status_only:
                if job in self.history_discovery:raise ValueError('呢個批次正在探索頻道；唔會重複開始。')
                self.history_discovery.add(job);discovery_job=job
                await inter.followup.send('已開始探索文字頻道及封存討論串；暫時未補分。完成範圍核對後會另行回報。',ephemeral=True)
                with connect_sqlite(self.ledger.path) as db:
                    applied=db.execute("SELECT plan,manifest FROM hybrid_plans WHERE guild=? AND state='applied'",(inter.guild_id,)).fetchall()
                if len(applied)!=1:raise ValueError('需要唯一已套用基線批次。')
                plan,encoded=applied[0];baseline=json.loads(encoded)
                inventory=await asyncio.to_thread(self.ledger.engagement_inventory,inter.guild_id,scope['start']-60,scope['cutoff']+60)
                summary=await asyncio.to_thread(self.history_audit.summary,job,inter.guild_id,inventory)
                users=sorted(summary['potential'])
                if self.cfg['excluded_roles']:raise ValueError('歷史排除身份組未有時序證據，需先核對。')
                if not set(users)<={row['user_id'] for row in baseline['rows']}:raise ValueError('候選用家未有已核對基線。')
                channels={c.id:c for c in inter.guild.channels if hasattr(c,'history')}
                channels.update({c.id:c for c in await inter.guild.active_threads()})
                for parent in inter.guild.channels:
                    if isinstance(parent,(discord.TextChannel,discord.ForumChannel)):
                        async for thread in parent.archived_threads(limit=None):channels[thread.id]=thread
                        if isinstance(parent,discord.TextChannel):
                            async for thread in parent.archived_threads(limit=None,private=True):channels[thread.id]=thread
                selected=[]
                for channel in channels.values():
                    ids={channel.id,getattr(channel,'parent_id',None),getattr(channel,'category_id',None)}
                    if ids.intersection(self.cfg['excluded_channels']):continue
                    perms=channel.permissions_for(inter.guild.me)
                    admin_perms=channel.permissions_for(inter.user)
                    if not (perms.view_channel and perms.read_message_history and admin_perms.view_channel and admin_perms.read_message_history):
                        raise ValueError('部分文字頻道／討論串未能完整讀取，唔會聲稱CD核對完成。')
                    selected.append(channel.id)
                policy=dict(baseline=plan,cutoff=min(scope['cutoff'],baseline['cutover']),users=users,
                    cooldown=max(self.cfg['text_cooldown'],self.cfg['activity_cooldown']),
                    excluded_channels=sorted(self.cfg['excluded_channels']),excluded_roles=sorted(self.cfg['excluded_roles']))
                self.history_channels.update(channels)
                await asyncio.to_thread(self.history_audit.start_text,job,inter.guild_id,selected,policy)
                key='text:'+job
                if key not in self.history_tasks or self.history_tasks[key].done():self.history_tasks[key]=asyncio.create_task(self.collect_history_text(job))
            text=await asyncio.to_thread(self.history_audit.text_scope,job)
            if text['state']!='complete':
                complete=sum(bool(c[2]) for c in text['cursors'])
                await inter.followup.send(f'文字CD核數 {text["state"]}｜已完成 {complete}/{len(text["cursors"])} 個範圍；未有私人核數結果，冇補分。',ephemeral=True)
                return
            await self.check_history_scope(inter,text)
            complete=sum(bool(c[2]) for c in text['cursors'])
            message=f'文字CD核數 {job}｜{text["state"]}｜完成頻道／討論串 {complete}/{len(text["cursors"])}。只保留用家ID及時間，冇保存訊息內容。'
            if text['state']=='complete':
                replay=await asyncio.to_thread(self.history_audit.text_replay,job,inter.guild_id)
                message+='\n'+'\n'.join(f'<@{uid}>：合併後 {row["combined"]} − 原文字 {row["text_only"]} = {row["base_xp"]} 基礎XP候選' for uid,row in list(replay['users'].items())[:10])
                message+='\n只反映保留中嘅歷史；已刪訊息及歷史Booster倍數未知。未補分。'
                await inter.followup.send(message,file=discord.File(io.BytesIO(json.dumps(replay,ensure_ascii=False,indent=2).encode()),filename='history_cd_private.json'),allowed_mentions=discord.AllowedMentions.none(),ephemeral=True)
            else:await inter.followup.send(message,allowed_mentions=discord.AllowedMentions.none(),ephemeral=True)
        except (ValueError,discord.HTTPException,sqlite3.OperationalError) as exc:
            await inter.followup.send(('核數未完成：'+str(exc))[:1500],ephemeral=True)
        except Exception as exc:
            log.exception('Historical text command failed')
            await inter.followup.send(f'文字核數暫停（{type(exc).__name__}）；未補分。',ephemeral=True)
        finally:
            if discovery_job:self.history_discovery.discard(discovery_job)

    async def check_history_scope(self,inter,text):
        if all(getattr(getattr(viewer,'guild_permissions',None),'administrator',False) for viewer in (inter.user,inter.guild.me)):
            return  # Discord Administrator bypasses channel overwrites and private-thread membership.
        for cid,_,_ in text['cursors']:
            channel=self.bot.get_channel(cid) or self.history_channels.get(cid) or await self.bot.fetch_channel(cid)
            if channel.guild.id!=inter.guild_id:raise ValueError('核數頻道不屬於呢個伺服器。')
            for viewer in (inter.user,inter.guild.me):
                perms=channel.permissions_for(viewer)
                if not (perms.view_channel and perms.read_message_history):raise ValueError('需要所有原始文字核數頻道嘅查看及讀取權限。')

    @levels.command(name='history_bonus',description='預覽歷史基礎XP補償；接受估算政策後按核對摘要一次性提交')
    @app_commands.default_permissions(manage_guild=True)
    async def history_bonus_command(self,inter:discord.Interaction,commit:bool=False,base_only:bool=False,digest:str|None=None):
        if not await self.guard(inter):return
        try:
            latest=await asyncio.to_thread(self.history_audit.latest,inter.guild_id)
            if not latest:raise ValueError('未有歷史核數。')
            job=latest[0];scope=await asyncio.to_thread(self.history_audit.job,job,inter.guild_id)
            text=await asyncio.to_thread(self.history_audit.text_scope,job)
            await self.check_history_scope(inter,text)
            replay=await asyncio.to_thread(self.history_audit.text_replay,job,inter.guild_id)
            members={m.id for m in inter.guild.members if not m.bot}
            manifest=await asyncio.to_thread(prepare_bonus,self.ledger,inter.guild_id,inter.user.id,job,scope['start'],replay,members)
            sha=manifest_digest(manifest)
            existing=self.cfg.get('historical_bonus')
            if existing:
                await inter.followup.send('歷史補償已完成；呢個基線唔會重複加分。');return
            if not commit:
                lines=[]
                for row in manifest['users']:
                    profile=await asyncio.to_thread(self.ledger.profile,inter.guild_id,row['user'])
                    lines.append(f'<@{row["user"]}>：+{row["amount"]:,}（{profile["total"]:,} → {profile["total"]+row["amount"]:,} XP）')
                await inter.followup.send('歷史補分預覽，未改分。\n'+'\n'.join(lines[:10])+f'\n摘要：{sha}\n政策：按現存記錄重播共用CD，補普通基礎XP；不推斷已刪訊息及歷史Booster倍數。舊週榜不補造。',file=discord.File(io.BytesIO(json.dumps(manifest,ensure_ascii=False,indent=2).encode()),filename='history_bonus_private.json'),allowed_mentions=discord.AllowedMentions.none())
                return
            if not HISTORICAL_BASE_POLICY_ACCEPTED:raise ValueError('歷史估算政策未選定；目前只提供補分預覽。')
            if not base_only or digest!=sha:raise ValueError('提交需接受普通基礎XP估算政策，並提供完全相同嘅預覽摘要。')
            for row in manifest['users']:
                member=await inter.guild.fetch_member(row['user'])
                if member.bot:raise ValueError('補分對象必須係現有真人。')
            backup=DATA_DIR/'level_backups'/f'history-{sha[:20]}.sqlite3'
            async with self.role_lock:
                async with self.lock:
                    current={m.id for m in inter.guild.members if not m.bot}
                    fresh=await asyncio.to_thread(self.history_audit.text_replay,job,inter.guild_id)
                    if manifest_digest(fresh)!=manifest_digest(replay):raise ValueError('核數證據已改變，請重新預覽。')
                    self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,mode='off')
                    result=await asyncio.to_thread(apply_bonus,self.ledger,manifest,backup,time.time(),actor=inter.user.id,current_users=current,accept_base_only=True)
                    self.cfg=await asyncio.to_thread(self.ledger.settings,inter.guild_id)
            self.voice_clock.clear()
            await inter.followup.send(f'歷史補償已完成（同批次不重複）：{result["count"]} 人；已備份。現時OFF，冇改週榜／冷卻／角色；可用管理面板恢復試行。')
        except (ValueError,discord.HTTPException,sqlite3.Error) as exc:await inter.followup.send(str(exc)[:1500])

    @staticmethod
    def baseline_roster(guild):
        return [dict(id=m.id,roles=sorted(r.id for r in m.roles),
            aliases=sorted({a for a in (m.name,m.global_name,m.nick,m.display_name) if a})) for m in guild.members if not m.bot]

    @levels.command(name='baseline',description='公開榜XP優先，其餘按最高等級角色起點；預覽／備份後搬遷')
    @app_commands.default_permissions(manage_guild=True)
    async def baseline_command(self,inter:discord.Interaction,data:str|None=None,commit:bool=False,plan:str|None=None):
        if not await self.guard(inter):return
        try:
            if self.cfg['mode']=='active':raise ValueError('請先暫停正式派角色模式。')
            guild=inter.guild
            if guild.member_count and len(guild.members)<guild.member_count:
                await guild.chunk(cache=True)
            if guild.member_count and len(guild.members)<guild.member_count:raise ValueError('成員清單未齊，唔會建立搬遷。')
            members=self.baseline_roster(guild)
            roles=[dict(id=r.id,name=r.name) for r in guild.roles]
            if commit:
                if not plan or data is not None:raise ValueError('提交只需已核對嘅 plan ID。')
                backup=DATA_DIR/'level_backups'/f'hybrid-{plan}.sqlite3'
                async with self.role_lock:
                    async with self.lock:
                        self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,mode='off')
                        result=await asyncio.to_thread(apply_plan,self.ledger,guild=inter.guild_id,actor=inter.user.id,
                            plan=plan,members=self.baseline_roster(guild),roles=[dict(id=r.id,name=r.name) for r in guild.roles],backup_path=backup,now=time.time())
                        self.cfg=await asyncio.to_thread(self.ledger.settings,inter.guild_id)
                self.voice_clock.clear()
                await inter.followup.send(f'基線已搬入（或同批次已完成）：{result["count"]} 人。已備份；原有試行重疊記錄已封存。現時 OFF，冇派角色／發公告；舊 Amari 週榜未搬遷，歷史補分未套用。')
                return
            if data is None:raise ValueError('請提供完整公開榜分頁資料，或用 plan＋commit 提交已核對預覽。')
            async with self.lock:
                capture=await asyncio.to_thread(stage_public,self.ledger,inter.guild_id,data,time.time())
                if not capture['complete']:
                    await inter.followup.send(f'已接收公開榜 {capture["received"]}/{capture["parts"]} 部分；未改積分。');return
                manifest=build_manifest(inter.guild_id,inter.user.id,members,roles,capture['rows'],capture['observed_at'],capture['batch'])
                for row in manifest['rows']:
                    row['old_preview_total']=(await asyncio.to_thread(self.ledger.profile,inter.guild_id,row['user_id']))['total']
                token=await asyncio.to_thread(save_plan,self.ledger,manifest)
            exact=sum(r['kind']=='public_board' for r in manifest['rows'])
            floor=sum(r['kind']=='role_floor' for r in manifest['rows'])
            top=sorted(manifest['rows'],key=lambda r:-r['baseline'])[:12]
            detail='\n'.join(f'<@{r["user_id"]}>：{r["baseline"]:,} XP（{r["kind"]}）' for r in top)
            text=(f'基線預覽 {token}\n公開榜 {len(capture["rows"])} 行；榜單對應 {exact} 人；角色起點 {floor} 人。'
                f'\nUnknown已離開 {manifest["unknown_departed"]}；未能唯一對應榜單 {len(manifest["unresolved_ranks"])}；'
                f'衝突暫緩 {len(manifest["conflicts"])}；無基線證據 {len(manifest["skipped"])}。\n{detail}'
                '\n未改積分。提交會替換基線，封存舊試行總分，保留榜單觀察時間後嘅新版事件；歷史補分另計，舊週XP未知。')
            await inter.followup.send(text[:1950],allowed_mentions=discord.AllowedMentions.none(),
                file=discord.File(io.BytesIO(json.dumps(manifest,ensure_ascii=False,indent=2).encode()),filename='baseline_preview_private.json'))
        except (ValueError,discord.HTTPException) as exc:
            await inter.followup.send(str(exc) if isinstance(exc,ValueError) else '未能讀取成員／角色；未提交基線。')

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
