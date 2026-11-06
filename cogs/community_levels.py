"""Opt-in Con9sole leveling; read-only until the owner starts a preview."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import sqlite3
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from features.community_levels import Ledger, REWARD_NAMES, battle_identity, calendar, level_for, threshold

log = logging.getLogger(__name__)
GUILD = discord.Object(id=config.GUILD_ID)


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


class CommunityLevels(commands.Cog):
    levels = app_commands.Group(name='levels',description='Con9sole 會員等級及活躍紀錄',guild_ids=[config.GUILD_ID])

    def __init__(self,bot):
        self.bot=bot
        self.ledger=None
        self.lock=asyncio.Lock()
        self.voice_clock={}
        self.cfg={}

    async def cog_load(self):
        self.ledger=await asyncio.to_thread(Ledger)
        self.cfg=await asyncio.to_thread(self.ledger.settings,config.GUILD_ID)
        self.voice_tick.add_exception_type(sqlite3.OperationalError)
        self.voice_tick.start()

    async def cog_unload(self):
        self.voice_tick.cancel()

    async def configure(self,**changes):
        async with self.lock:
            self.cfg=await asyncio.to_thread(self.ledger.configure,config.GUILD_ID,**changes)

    @staticmethod
    def admin(inter):
        return inter.guild_id==config.GUILD_ID and (inter.user.guild_permissions.administrator or inter.user.guild_permissions.manage_guild)

    async def guard(self,inter):
        if not self.admin(inter):
            await inter.response.send_message('需要管理伺服器權限。',ephemeral=True)
            return False
        await inter.response.defer(ephemeral=True)
        return True

    async def settings_embed(self):
        cfg=self.cfg
        e=discord.Embed(title='🎖️ Con9sole 等級管理',color=0xe5b65b,
                       description=f"狀態：**{cfg['mode']}**\n試行會記錄獨立 XP，但唔派角色／發升級公告。")
        e.add_field(name='文字／Bot 活動',value=f"共用 {max(cfg['text_cooldown'],cfg['activity_cooldown'])} 秒冷卻；每次 1 XP\nBot 活動每日最多 {cfg['activity_daily_cap']} 次",inline=False)
        e.add_field(name='語音',value=f"最少 2 位有效真人；每 {cfg['voice_interval']//60} 分鐘 {cfg['voice_xp']} XP\n排除 AFK、耳聾及舞台聽眾",inline=False)
        e.add_field(name='其他',value=f"Booster 文字／活動 ×{cfg['booster_multiplier']}\n來源 {len(cfg['sources'])} 個｜角色獎勵 {len(cfg['rewards'])} 個\n離開保留 XP；每週一香港時間自動開始新榜",inline=False)
        e.set_footer(text='原有 Amari XP 未自動搬入；正式接管前需核對匯入及停用 Amari 派角色。')
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
        old,new=map(level_for,result)
        # Reconcile on each earned award so a transient permissions/API error is retried.
        pairs=[(int(level),member.guild.get_role(int(rid))) for level,rid in self.cfg['rewards'].items()]
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
        if new>old:
            crossed=[level for level,_ in due if old<level<=new]
            channel=member.guild.get_channel(self.cfg['announcement_channel'])
            if crossed and isinstance(channel,discord.TextChannel):
                name=REWARD_NAMES.get(max(crossed),'會員')
                try:
                    await channel.send(f'🎖️ {member.mention} 升至 **Lv.{new}**，成為【{name}】！',
                        allowed_mentions=discord.AllowedMentions(users=self.cfg['announcement_ping'],roles=False,everyone=False))
                except discord.HTTPException:
                    log.warning('Level announcement failed')

    @commands.Cog.listener()
    async def on_message(self,message):
        if not message.guild or message.guild.id!=config.GUILD_ID or self.cfg['mode']=='off':
            return
        if message.author.bot:
            await self.observe_battle(message)
        elif isinstance(message.author,discord.Member):
            content=message.content.strip()
            if content.startswith((':?','/','!')) or (not content and not message.attachments):
                return
            await self.credit(message.author,message.channel,'text',f'm:{message.id}')

    async def observe_battle(self,message):
        if not message.author.bot or message.webhook_id:
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
            await asyncio.to_thread(self.ledger.bind,message.guild.id,message.author.id,name,uid)
        else:
            uid=await asyncio.to_thread(self.ledger.resolve,message.guild.id,message.author.id,name)
            member=message.guild.get_member(uid) if uid else None
            if not member or member.name!=name:
                return
        await self.credit(member,message.channel,'activity',f'm:{message.id}')

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if payload.guild_id!=config.GUILD_ID or self.cfg['mode']=='off':
            return
        if not any(s['channel']==payload.channel_id for s in self.cfg['sources']):
            return
        channel=self.bot.get_channel(payload.channel_id)
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

    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        # Any eligibility/channel change invalidates elapsed time for the whole room.
        for channel in (before.channel,after.channel):
            if channel and member.guild.id==config.GUILD_ID:
                for key in list(self.voice_clock):
                    if key[0]==channel.id:
                        self.voice_clock.pop(key,None)

    @tasks.loop(seconds=30)
    async def voice_tick(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild or self.cfg.get('mode')=='off':
            self.voice_clock.clear()
            return
        now=time.monotonic()
        present=set()
        for channel in guild.voice_channels+guild.stage_channels:
            if channel.id==guild.afk_channel_id:
                continue
            members=voice_members(channel,self.cfg)
            if len(members)<2:
                continue
            for member in members:
                key=(channel.id,member.id)
                present.add(key)
                start=self.voice_clock.setdefault(key,now)
                if now-start>=self.cfg['voice_interval']:
                    self.voice_clock[key]=now
                    await self.credit(member,channel,'voice',f'v:{channel.id}:{member.id}:{int(time.time())}')
        self.voice_clock={k:v for k,v in self.voice_clock.items() if k in present}

    @voice_tick.before_loop
    async def before_voice(self):
        await self.bot.wait_until_ready()

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
        level=level_for(p['total'])
        earned=p['total']-threshold(level)
        required=threshold(level+1)-threshold(level)
        filled=min(10,earned*10//required)
        e=discord.Embed(title='🎖️ 會員等級',description=f'{target.mention}\n**Lv.{level}** · {p["total"]:,} XP\n'+ '▰'*filled+'▱'*(10-filled)+f' {earned:,}/{required:,}',color=0xe5b65b)
        e.add_field(name='XP 來源',value=f"文字 {p['text']:,}｜互動 {p['activity']:,}｜語音 {p['voice']:,}\n匯入基準 {p['imported']:,}",inline=False)
        e.set_footer(text=f'模式：{self.cfg["mode"]}｜獨立計分，未同步 Amari；管理調整另計')
        await inter.followup.send(embed=e,allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name='leaderboard',description='查看總榜或香港時間每週榜')
    async def leaderboard(self,inter:discord.Interaction,weekly:bool=False):
        await inter.response.defer(ephemeral=True)
        week=calendar(time.time())[1] if weekly else None
        rows=await asyncio.to_thread(self.ledger.leaderboard,inter.guild_id,week)
        text='\n'.join(f'{i}. <@{uid}> · {points:,} XP' for i,(uid,points) in enumerate(rows,1)) or '暫時未有紀錄。'
        await inter.followup.send(embed=discord.Embed(title='🏆 '+(f'每週榜 {week}' if weekly else '會員總榜'),description=text),allowed_mentions=discord.AllowedMentions.none())

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
        async with self.lock:
            values=set(self.cfg[key])
            values.discard(target) if remove else values.add(target)
            self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,**{key:sorted(values)})
        self.voice_clock.clear()
        await inter.followup.send('已更新計分排除設定。')

    @levels.command(name='rates',description='設定冷卻、每日互動上限及語音 XP')
    @app_commands.default_permissions(manage_guild=True)
    async def rates(self,inter:discord.Interaction,cooldown:app_commands.Range[int,30,3600]=60,activity_cap:app_commands.Range[int,1,500]=60,voice_minutes:app_commands.Range[int,1,60]=5,voice_xp:app_commands.Range[int,1,100]=25):
        if not await self.guard(inter): return
        await self.configure(text_cooldown=cooldown,activity_cooldown=cooldown,activity_daily_cap=activity_cap,voice_interval=voice_minutes*60,voice_xp=voice_xp)
        self.voice_clock.clear()
        await inter.followup.send(embed=await self.settings_embed())

    @levels.command(name='reward',description='明確指定等級獎勵角色，避免自動猜測')
    @app_commands.default_permissions(manage_guild=True)
    async def reward(self,inter:discord.Interaction,level:app_commands.Range[int,1,10000],role:discord.Role,remove:bool=False):
        if not await self.guard(inter): return
        me=inter.guild.me
        if not remove and (role.is_default() or role.managed or role>=me.top_role or role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles):
            await inter.followup.send('角色唔適合自動派發；請檢查權限及角色排序。'); return
        async with self.lock:
            rewards=dict(self.cfg['rewards'])
            if remove: rewards.pop(str(level),None)
            else:
                if str(role.id) in [str(r) for l,r in rewards.items() if l!=str(level)]:
                    await inter.followup.send('同一角色不可對應多個等級。'); return
                rewards[str(level)]=role.id
            self.cfg=await asyncio.to_thread(self.ledger.configure,inter.guild_id,rewards=rewards)
        await inter.followup.send('已更新獎勵；正式模式只保留最高合資格等級角色。')

    @levels.command(name='activate',description='完成舊等級核對及停用 Amari 派角色後正式接管')
    @app_commands.default_permissions(manage_guild=True)
    async def activate(self,inter:discord.Interaction,amari_rewards_disabled:bool,baseline_verified:bool,announcement:discord.TextChannel,ping:bool=False):
        if not await self.guard(inter): return
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

    @levels.command(name='inspect',description='只讀檢查指定討論串戰鬥卡可否識別，不加分')
    @app_commands.default_permissions(manage_guild=True)
    async def inspect(self,inter:discord.Interaction,channel:discord.Thread,message_id:str):
        if not await self.guard(inter): return
        if not message_id.isdecimal():
            await inter.followup.send('請填訊息 ID。'); return
        if not channel.permissions_for(inter.user).read_message_history:
            await inter.followup.send('你未有讀取記錄權限。'); return
        try:
            msg=await channel.fetch_message(int(message_id))
            trusted={'bot':msg.author.id,'channel':channel.id} in self.cfg['sources'] and msg.author.bot and not msg.webhook_id
            identity=battle_identity([e.to_dict() for e in msg.embeds]) if trusted else None
            await inter.followup.send(f'白名單來源：{trusted}\n可識別戰鬥格式：{identity is not None}\n呢次檢查唔會加分或建立玩家對應。')
        except discord.HTTPException:
            await inter.followup.send('讀唔到訊息，請檢查 ID 同權限。')


async def setup(bot):
    await bot.add_cog(CommunityLevels(bot))
