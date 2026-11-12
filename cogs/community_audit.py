"""One owner for member, message, voice and server logs in the existing private channels."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.community_audit import AuditStore, event_id
from core.permissions import is_server_admin
from core.storage_paths import DATA_DIR
from core.audit_monitor import WriteFailures
from core.audit_privacy import require_private_audit_channel
from features.audit_format import safe, who, where, changes, role_label, identity_footer, ACTIONS

log = logging.getLogger(__name__)
ROUTES = {
    'server': config.LOG_CHANNEL_ID,
    'message': 1421103987599610018,
    'member': 1421128161491419186,
    'voice': 1421143797571784895,
}
# Do not copy log content back into itself or a second log destination.
EXCLUDED = set(ROUTES.values()) | {1400830921883521166}
NONE = discord.AllowedMentions.none()


def preview(message, content=None):
    if message and hasattr(message.channel,'is_nsfw') and message.channel.is_nsfw():
        return '年齡限制頻道：只記錄事件資料。'
    text = getattr(message,'content','') if content is None else content
    return safe(text or '（無文字／未能取得）',850)


class CommunityAudit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = None
        self.last_error = None
        self.disconnected = False
        self.lock = asyncio.Lock()
        self.voice_started = {}
        self.last_prune = 0
        self.route_due = {}
        self.heartbeat = time.time()
        self.write_failed = False
        self.write_failures = WriteFailures()
        self.failure_lock = asyncio.Lock()

    async def cog_load(self):
        self.write_failures = await asyncio.to_thread(WriteFailures, DATA_DIR / 'audit_write_failures.json')
        self.write_failed = self.write_failures.pending
        self.store = await asyncio.to_thread(AuditStore, DATA_DIR / 'community_audit.sqlite3')
        self.deliver.start()

    async def cog_unload(self):
        self.deliver.cancel()
        task=self.deliver.get_task()
        if task:
            await asyncio.gather(task,return_exceptions=True)

    async def emit(self, category, title, description, *, key=None, subject=None):
        try:
            payload={'title':title[:200],'description':description[:3500]}
            if subject is not None:
                payload['author']={'name':str(getattr(subject,'display_name',None) or getattr(subject,'name',None) or '成員')[:100],
                                   'url':f'https://discord.com/users/{int(subject.id)}'}
                avatar=getattr(subject,'display_avatar',None)
                if avatar: payload['author']['icon_url']=str(avatar)
            key = await asyncio.to_thread(self.store.append,category,
                payload,key=key)
            return key
        except Exception:
            async with self.failure_lock:
                self.write_failed=True
                try: await asyncio.to_thread(self.write_failures.record)
                except Exception: log.exception('Could not persist audit write-failure counter; in-memory warning retained')
            self.last_error='事件寫入失敗；請查看執行日誌。'
            log.exception('Audit event persistence failed: category=%s',category)

    async def acknowledge_write_failures(self,count,actor):
        async with self.failure_lock:
            changed=await asyncio.to_thread(self.write_failures.acknowledge,count,actor)
            self.write_failed=self.write_failures.pending
            return changed

    def destination(self, category):
        guild=self.bot.get_guild(config.GUILD_ID)
        channel=guild.get_channel(ROUTES[category]) if guild else None
        if not isinstance(channel,discord.TextChannel):
            raise RuntimeError('missing audit channel: '+category)
        permissions=channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            raise RuntimeError('missing audit delivery permissions: '+category)
        if channel.permissions_for(guild.default_role).view_channel:
            raise RuntimeError('audit channel is visible to everyone: '+category)
        require_private_audit_channel(channel)
        return channel

    @tasks.loop(seconds=3)
    async def deliver(self):
        async with self.lock:
            for category in ROUTES:
                if self.route_due.get(category,0)>time.time():
                    continue
                try:
                    rows=await asyncio.to_thread(self.store.pending,category)
                    if not rows:
                        continue
                    channel=self.destination(category)
                    embeds=[]; keys=[]; total=0
                    for key,stamp,payload in rows:
                        embed=discord.Embed(title=payload['title'],description=payload['description'],
                                            color=0x5865F2,timestamp=datetime.fromtimestamp(stamp,timezone.utc))
                        if payload.get('author'): embed.set_author(**payload['author'])
                        identities=identity_footer(payload['description'])
                        embed.set_footer(text=f'Bartender 日誌 v2｜事件 {key}'+('\n'+identities if identities else ''))
                        if embeds and total+len(embed)>5500:
                            break
                        embeds.append(embed); keys.append(key); total+=len(embed)
                    if not await asyncio.to_thread(self.store.claim,keys):
                        continue
                    try:
                        message=await channel.send(embeds=embeds,allowed_mentions=NONE,silent=True)
                    except discord.HTTPException as exc:
                        # 4xx means rejected; a server/network failure may have accepted the message.
                        state='pending' if 400<=exc.status<500 else 'uncertain'
                        await asyncio.to_thread(self.store.finish,keys,state,error=f'HTTP {exc.status}')
                        self.last_error=f'{category}：HTTP {exc.status}（{state}）'
                    except asyncio.CancelledError:
                        await asyncio.shield(asyncio.to_thread(self.store.finish,keys,'uncertain',error='delivery cancelled'))
                        raise
                    except Exception as exc:
                        await asyncio.to_thread(self.store.finish,keys,'uncertain',error=type(exc).__name__)
                        self.last_error=f'{category}：結果未能確認'
                        log.exception('Audit delivery uncertain: category=%s',category)
                    else:
                        await asyncio.to_thread(self.store.finish,keys,'sent',message_id=message.id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.route_due[category]=time.time()+60
                    self.last_error=f'{category}：路由／儲存失敗，事件保留待送'
                    log.exception('Audit delivery deferred: category=%s',category)
            if time.time()-self.last_prune>3600:
                try:
                    await asyncio.to_thread(self.store.prune)
                except Exception:
                    log.exception('Audit retention maintenance failed; retrying next hour')
                self.last_prune=time.time()
            self.heartbeat=time.time()

    @deliver.before_loop
    async def before_delivery(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # Restart the sender if an unexpected database error stopped it.
        if not self.deliver.is_running():
            self.deliver.start()
        await self.emit('server','日誌系統已連線',
            '四類日誌由 Bartender 接管。斷線期間事件不能補回；未確認送出結果不會自動重發。')

    @commands.Cog.listener()
    async def on_disconnect(self):
        self.disconnected=True
        self.voice_started.clear()

    @commands.Cog.listener()
    async def on_resumed(self):
        if self.disconnected:
            await self.emit('server','日誌連線已恢復','可能有斷線期間未收到的事件；不推算缺失內容。')
            self.disconnected=False

    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.guild.id==config.GUILD_ID:
            created=int(member.created_at.timestamp())
            await self.emit('member','成員加入',f'{who(member)}\n帳戶建立：<t:{created}:f>',
                            key=f'join:{member.id}:{member.joined_at.timestamp()}',subject=member)

    @commands.Cog.listener()
    async def on_member_remove(self,member):
        if member.guild.id==config.GUILD_ID:
            await self.emit('member','成員離開',f'{who(member)}\n離開原因未確認；封鎖／移除請對照官方審核事件。',subject=member)

    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        if after.guild.id!=config.GUILD_ID:
            return
        lines=changes(before,after,[('nick','暱稱'),('timed_out_until','禁言至'),('pending','入會審核')])
        b={r.id:r for r in before.roles}; a={r.id:r for r in after.roles}
        if a.keys()-b.keys(): lines.append('🟢 新增身份組：'+', '.join(role_label(a[i]) for i in sorted(a.keys()-b.keys())))
        if b.keys()-a.keys(): lines.append('🔴 移除身份組：'+', '.join(role_label(b[i]) for i in sorted(b.keys()-a.keys())))
        if lines:
            await self.emit('member','成員資料變更',who(after)+'\n'+'\n'.join(lines),subject=after)

    @commands.Cog.listener()
    async def on_user_update(self,before,after):
        guild=self.bot.get_guild(config.GUILD_ID)
        if guild and guild.get_member(after.id):
            lines=changes(before,after,[('name','用戶名稱'),('global_name','顯示名稱'),('avatar','頭像')])
            if lines: await self.emit('member','帳戶資料變更',who(guild.get_member(after.id))+'\n'+'\n'.join(lines),subject=guild.get_member(after.id))

    @commands.Cog.listener()
    async def on_member_ban(self,guild,user):
        if guild.id==config.GUILD_ID: await self.emit('member','成員被封鎖',who(user),subject=user)

    @commands.Cog.listener()
    async def on_member_unban(self,guild,user):
        if guild.id==config.GUILD_ID: await self.emit('member','解除成員封鎖',who(user),subject=user)

    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        if member.guild.id!=config.GUILD_ID or member.bot:
            return
        if before.channel!=after.channel:
            key=member.id
            elapsed=''
            if before.channel:
                started=self.voice_started.pop(key,None)
                elapsed=f'\n上一頻道停留約 {int(time.monotonic()-started)} 秒' if started else '\n上一頻道時長未知（重啟／斷線或加入時間未觀察到）'
            if after.channel: self.voice_started[key]=time.monotonic()
            title='加入語音' if before.channel is None else ('離開語音' if after.channel is None else '切換語音')
            await self.emit('voice',title,f'{who(member)}\n{where(before.channel)} → {where(after.channel)}{elapsed}',subject=member)
        lines=changes(before,after,[('mute','伺服器靜音'),('deaf','伺服器拒聽'),('self_stream','分享畫面'),('self_video','視訊')])
        if lines: await self.emit('voice','語音狀態變更',who(member)+'\n'+where(after.channel or before.channel)+'\n'+'\n'.join(lines),subject=member)

    def message_scope(self,payload):
        return payload.guild_id==config.GUILD_ID and payload.channel_id not in EXCLUDED

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if not self.message_scope(payload) or 'content' not in payload.data:
            return
        old=payload.cached_message
        if old and (old.author.bot or getattr(old,'webhook_id',None)):
            return
        if payload.data.get('author',{}).get('bot'):
            return
        content=payload.data['content']
        if old and old.content==content:
            return
        raw_author=payload.data.get('author',{})
        author=who(old.author) if old else (f"<@{int(raw_author['id'])}>" if raw_author.get('id') else '作者未快取，無法確認。')
        guild=self.bot.get_guild(config.GUILD_ID)
        channel=guild.get_channel_or_thread(payload.channel_id) if guild else None
        restricted=channel and channel.is_nsfw()
        previous=preview(old) if old else '未快取原文，無法還原。'
        current='年齡限制頻道：只記錄事件資料。' if restricted else preview(old,content)
        stamp=payload.data.get('edited_timestamp','')
        key='edit:'+str(payload.message_id)+':'+hashlib.sha256((stamp+content).encode()).hexdigest()[:24]
        await self.emit('message','訊息編輯',f'{author}\n頻道：<#{payload.channel_id}>｜訊息 ID：{payload.message_id}\n'
                        f'**修改前**\n{previous}\n**修改後**\n{current}\n'
                        f'https://discord.com/channels/{config.GUILD_ID}/{payload.channel_id}/{payload.message_id}',key=key,subject=old.author if old else None)

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        if not self.message_scope(payload):
            return
        message=payload.cached_message
        if message and (message.author.bot or getattr(message,'webhook_id',None)):
            return
        author=who(message.author) if message else '作者未快取，無法確認。'
        body=preview(message) if message else '未快取原文，無法還原。'
        attachments=len(message.attachments) if message else '未知'
        await self.emit('message','訊息刪除',f'{author}\n頻道：<#{payload.channel_id}>｜訊息 ID：{payload.message_id}\n'
                        f'{body}\n附件數：{attachments}（不下載）\n刪除操作者未確認。',key=f'delete:{payload.message_id}',subject=message.author if message else None)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        if self.message_scope(payload):
            ids=sorted(payload.message_ids)
            digest=hashlib.sha256(','.join(map(str,ids)).encode()).hexdigest()[:24]
            await self.emit('message','批次刪除訊息',f'頻道：<#{payload.channel_id}>\n共 {len(ids)} 條；快取 {len(payload.cached_messages)} 條。\n'
                            '訊息 ID（最多列出 40 條）：'+', '.join(map(str,ids[:40]))+'\n不另複製原文／附件；操作者請對照官方審核。',key='bulk:'+digest)

    async def object_event(self,category,title,obj,description='',*,kind='channel',deleted=False):
        if obj.guild.id==config.GUILD_ID:
            label=role_label(obj,deleted=deleted) if kind=='role' else (f'**{safe(obj.name,100)}**（已刪除｜ID `{obj.id}`）' if deleted else where(obj))
            await self.emit(category,title,f'{label}\n{description}')

    @commands.Cog.listener()
    async def on_guild_channel_create(self,channel): await self.object_event('server','建立頻道',channel)
    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel): await self.object_event('server','刪除頻道',channel,deleted=True)
    @commands.Cog.listener()
    async def on_guild_channel_update(self,before,after):
        lines=changes(before,after,[('name','名稱'),('topic','主題'),('category_id','分類'),('slowmode_delay','慢速模式'),('nsfw','年齡限制'),('user_limit','人數上限')])
        if before.overwrites!=after.overwrites: lines.append('頻道權限覆寫已變更；詳見官方審核事件。')
        if lines: await self.object_event('server','頻道設定變更',after,'\n'.join(lines))
    @commands.Cog.listener()
    async def on_guild_role_create(self,role): await self.object_event('server','建立身份組',role,kind='role')
    @commands.Cog.listener()
    async def on_guild_role_delete(self,role): await self.object_event('server','刪除身份組',role,kind='role',deleted=True)
    @commands.Cog.listener()
    async def on_guild_role_update(self,before,after):
        lines=changes(before,after,[('name','名稱'),('permissions','權限'),('colour','顏色'),('hoist','獨立顯示'),('mentionable','可被提及')])
        if lines: await self.object_event('server','身份組設定變更',after,'\n'.join(lines),kind='role')
    @commands.Cog.listener()
    async def on_guild_update(self,before,after):
        lines=changes(before,after,[('name','名稱'),('verification_level','驗證等級'),('mfa_level','管理員雙重驗證'),('explicit_content_filter','內容過濾')])
        if lines and after.id==config.GUILD_ID: await self.emit('server','伺服器設定變更','\n'.join(lines))
    @commands.Cog.listener()
    async def on_guild_emojis_update(self,guild,before,after):
        if guild.id==config.GUILD_ID:
            b={e.id:e.name for e in before}; a={e.id:e.name for e in after}
            if a!=b: await self.emit('server','表情符號變更',f'新增：{safe({k:a[k] for k in a.keys()-b.keys()},700)}\n刪除：{safe({k:b[k] for k in b.keys()-a.keys()},700)}\n改名：{safe({k:(b[k],a[k]) for k in a.keys()&b.keys() if a[k]!=b[k]},700)}')
    @commands.Cog.listener()
    async def on_thread_create(self,thread):
        await self.object_event('server','建立討論串',thread)
    @commands.Cog.listener()
    async def on_thread_update(self,before,after):
        lines=changes(before,after,[('name','名稱'),('archived','封存'),('locked','鎖定')])
        if lines: await self.object_event('server','討論串變更',after,'\n'.join(lines))
    @commands.Cog.listener()
    async def on_raw_thread_delete(self,payload):
        if payload.guild_id==config.GUILD_ID: await self.emit('server','刪除討論串',f'討論串 ID：{payload.thread_id}｜母頻道 ID：{payload.parent_id}',key=f'thread-delete:{payload.thread_id}')

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self,entry):
        if entry.guild.id!=config.GUILD_ID:
            return
        actor_user=entry.user
        if actor_user is not None: actor_user=entry.guild.get_member(actor_user.id) or actor_user
        actor=who(actor_user) if actor_user else (f'<@{entry.user_id}>' if entry.user_id else '未知')
        target=getattr(entry.target,'id',None)
        kind=entry.action.target_type
        target_label=f'ID `{target}`' if target else '未提供'
        if target and kind=='role':
            obj=entry.guild.get_role(target) or entry.target
            if not getattr(obj,'name',None):
                from types import SimpleNamespace
                obj=SimpleNamespace(id=target,name=getattr(entry.before,'name',None) or getattr(entry.after,'name',None) or '未快取名稱')
            target_label=role_label(obj,deleted=entry.action.name=='role_delete')
        elif target and (kind=='user' or isinstance(entry.target,(discord.Member,discord.User))):
            target_label=who(entry.guild.get_member(target) or entry.target)
        elif target and kind in {'channel','thread'}:
            target_label=f'**{safe(getattr(entry.target,"name","未快取名稱"),100)}** · <#{target}>'
        action=ACTIONS.get(entry.action.name,entry.action.name.replace('_',' '))
        detail=f'**操作者**\n{actor}\n**對象**\n{target_label}\n原因：{safe(entry.reason or "未提供",500)}\n審核編號：`{entry.id}`'
        # This entry is authoritative only for its own target/action, never guessed onto a message.
        fields=[('name','名稱'),('permissions','權限'),('topic','主題'),('roles','身份組'),('communication_disabled_until','禁言至'),('mute','靜音'),('deaf','拒聽'),('nsfw','年齡限制')]
        detail+='\n'+'\n'.join(changes(entry.before,entry.after,fields))
        extra=getattr(entry,'extra',None)
        if extra:
            channel=getattr(extra,'channel',None)
            if channel: detail+=f'\n頻道：<#{channel.id}>'
            count=getattr(extra,'count',None)
            if count is not None: detail+=f'\n涉及數量：{count}'
        await self.emit('server','官方審核｜'+action,detail,key=f'audit:{entry.id}',subject=actor_user)

    async def menu_entry(self,inter):
        await self.show_status(inter)

    async def authorized(self,inter):
        current=inter.guild.get_member(inter.user.id) if inter.guild else None
        if inter.guild_id==config.GUILD_ID and is_server_admin(current):
            return True
        await inter.response.send_message('只限本伺服器管理員。',ephemeral=True)
        return False

    async def show_status(self,inter):
        if not await self.authorized(inter): return
        await inter.response.defer(ephemeral=True)
        states,recent=await asyncio.to_thread(self.store.summary)
        embed=discord.Embed(title='📋 社群日誌 v2',description='四類獨立路由｜靜默批次派送｜本機紀錄保留最多 30 日／20,000 筆（未解決事件優先保留）')
        for category,cid in ROUTES.items():
            try:
                self.destination(category); status='可派送'
            except RuntimeError as exc: status=str(exc)
            embed.add_field(name=category,value=f'<#{cid}>｜{status}',inline=False)
        guild=inter.guild
        embed.add_field(name='事件接收',value=f'Gateway 已連線：{self.bot.is_ready()}｜審核權限：{guild.me.guild_permissions.view_audit_log}｜訊息內容 Intent：{self.bot.intents.message_content}',inline=False)
        embed.add_field(name='佇列',value=str(states)+'\n'+f'派送循環：{self.deliver.is_running()}｜最近錯誤：{self.last_error or "無"}',inline=False)
        embed.add_field(name='寫入失敗紀錄',value=f'累計：{self.write_failures.count}｜待人工確認：{self.write_failed}（成功寫入不會清除此警號）',inline=False)
        if recent: embed.add_field(name='待送／待查事件（完整 ID）',value='\n'.join(f'{key}｜{cat}｜{state}' for key,cat,state,error in recent)[:1000],inline=False)
        embed.set_footer(text='未快取刪除訊息無法還原；斷線期間不補記；結果不明需人工核對；Discord 已發日誌不會定時刪除。')
        from features.audit_review import AuditHomeView
        monitor=self.bot.get_cog('AuditMonitor')
        monitor_status='未載入' if monitor is None else f'循環：{monitor.watch.is_running()}｜異常項目：{len(monitor.latest)}｜提示卡：{monitor.card.state.get("delivery","未需要發送")}｜提示錯誤：{monitor.last_error or "無"}'
        embed.add_field(name='獨立故障監察',value=monitor_status,inline=False)
        await inter.followup.send(embed=embed,view=AuditHomeView(self,inter.user.id),ephemeral=True,allowed_mentions=NONE)

    @app_commands.command(name='logging',description='管理員：核對四類日誌、測試路由及處理結果未明事件')
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def logging_command(self,inter:discord.Interaction,action:Literal['status','test','review','monitor_test','retry','ack']='status',event:str|None=None):
        if action=='status': return await self.show_status(inter)
        if action=='review':
            from features.audit_review import open_reviews
            return await open_reviews(self,inter)
        if not await self.authorized(inter): return
        await inter.response.defer(ephemeral=True)
        if action=='monitor_test':
            monitor=self.bot.get_cog('AuditMonitor')
            if monitor is None:
                return await inter.followup.send('故障監察尚未載入。',ephemeral=True)
            return await monitor.demo(inter)
        if action=='test':
            keys=[]
            for category in ROUTES:
                self.destination(category)
            for category in ROUTES:
                keys.append(await self.emit(category,'🧪 日誌路由驗收',f'管理員 {who(inter.user)} 測試 {category} 路由。\n身份組顯示樣本：{role_label(inter.guild.me.top_role)}\n這是明確標示的測試事件，不代表真實成員／訊息操作。',subject=inter.user))
            await inter.followup.send('四類測試已排入佇列；請核對各頻道實際收到。\n'+'\n'.join(str(k) for k in keys),ephemeral=True,allowed_mentions=NONE)
        else:
            changed=await asyncio.to_thread(self.store.resolve,event or '',action,inter.user.id)
            if changed: await self.emit('server','日誌待查事件處理',f'操作人：{who(inter.user)}\n事件：{safe(event,120)}\n處理：{action}（重試可能產生重複，ack 只代表人工確認）')
            await inter.followup.send('已更新事件狀態。' if changed else '未找到結果未明事件，沒有變更。',ephemeral=True,allowed_mentions=NONE)


async def setup(bot):
    await bot.add_cog(CommunityAudit(bot))
