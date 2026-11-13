"""Opt-in Helper demo: no real help alerts or copying cross-channel content."""
import asyncio
import logging
import os
import time
import re
from datetime import datetime,timezone,timedelta
import discord
from discord.ext import commands,tasks
import config
from core.storage_paths import DATA_DIR
from core.helper_sandbox import ActivityWindow
from core.helper_detection import DetectionStore,detect_help
from core.helper_detection_ui import show_pending
from core.helper_overview import show_overview,example_overview,BackToOverview
from core.helper_pulse import PulseStore,summarize,fragments
from zoneinfo import ZoneInfo

log=logging.getLogger(__name__)
ROOM_ID=1570639281225994301
RSS_ROOM=1570054214850183289


class HelperPanel(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog

    async def interaction_check(self,i): return await self.cog.access(i)

    @discord.ui.button(label='我的總覽',custom_id='helper:sandbox:live:v1',style=discord.ButtonStyle.primary,row=0)
    async def live(self,i,button):
        await show_overview(self.cog,i)

    @discord.ui.button(label='查看示例',custom_id='helper:sandbox:create:v1',row=2)
    async def create(self,i,button):
        await i.response.send_message('【虛構 log 示例】\n20:10 · MH｜💬 3 人、12 則 · 🆘 1 則疑似求助\n20:12 · FC｜🎙️ 1 個 call、4 人\n20:14 · GTA｜🤝 1 則搵隊友',ephemeral=True)

    @discord.ui.button(label='待接應',custom_id='helper:sandbox:manage:v1',style=discord.ButtonStyle.success,row=0)
    async def manage(self,i,button):
        await show_pending(self.cog,i)

    @discord.ui.button(label='值班設定',custom_id='helper:sandbox:duty:v1',row=1)
    async def duty(self,i,button):
        enabled=await asyncio.to_thread(self.cog.store.toggle_duty,i.user.id)
        await i.response.send_message(('🟢 已設為值班' if enabled else '⚪ 已暫停')+'（模擬設定已保存；未啟用真實提醒）。',ephemeral=True)

    @discord.ui.button(label='處理記錄',custom_id='helper:sandbox:history:v1',row=1)
    async def history(self,i,button):
        await show_pending(self.cog,i,closed=True)


class RequestSelect(discord.ui.Select):
    def __init__(self,rows):
        super().__init__(placeholder='選擇測試求助',options=[discord.SelectOption(label=f"#{r['id']} · {r['state']} · {r['title']}"[:100],value=str(r['id'])) for r in rows])

    async def callback(self,i):
        self.view.selected=int(self.values[0])
        await i.response.edit_message(content=f'已選擇測試 #{self.view.selected}。')


class RequestView(discord.ui.View):
    def __init__(self,cog,owner,rows):
        super().__init__(timeout=600)
        self.cog,self.owner,self.selected=cog,owner,None
        self.add_item(RequestSelect(rows))

    async def interaction_check(self,i):
        if i.user.id!=self.owner:
            await i.response.send_message('請開自己嘅跟進選單。',ephemeral=True)
            return False
        return await self.cog.access(i)

    async def act(self,i,action):
        if self.selected is None:
            await i.response.send_message('請先選擇求助。',ephemeral=True)
            return
        await i.response.defer(ephemeral=True)
        try:
            label=await asyncio.to_thread(self.cog.store.transition,self.selected,i.user.id,action,time.time(),i.user.guild_permissions.administrator)
            await self.cog.refresh()
            await i.followup.send(f'✅ 測試 #{self.selected}：{label}。',ephemeral=True)
        except ValueError as exc: await i.followup.send(str(exc),ephemeral=True)

    @discord.ui.button(label='我跟進',style=discord.ButtonStyle.primary,row=1)
    async def claim(self,i,button): await self.act(i,'claim')

    @discord.ui.button(label='已處理',style=discord.ButtonStyle.success,row=1)
    async def done(self,i,button): await self.act(i,'done')

    @discord.ui.button(label='需要其他 Helper',row=1)
    async def handoff(self,i,button): await self.act(i,'handoff')


class HelperSandbox(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.enabled=os.getenv('HELPER_SANDBOX','')=='1'
        self.store=None
        self.pulse=None
        self.channel=None
        self.panel=None
        self.tester_id=None
        self.window=ActivityWindow(time.time())
        self.lock=asyncio.Lock()

    async def cog_load(self):
        if not self.enabled: return
        self.store=DetectionStore(DATA_DIR/'helper_sandbox.sqlite3')
        self.pulse=PulseStore(DATA_DIR/'helper_pulse.sqlite3')
        await asyncio.to_thread(self.store.set,'pulse_version','1')
        await asyncio.to_thread(self.store.set,'detector_version','1')
        await asyncio.to_thread(self.store.set,'overview_version','1')
        self.panel=HelperPanel(self)
        self.bot.add_view(self.panel)
        self.tick.start()
        self.backfill.start()
        self.pulse_tick.start()

    async def cog_unload(self):
        self.pulse_tick.cancel()
        self.backfill.cancel()
        self.tick.cancel()
        if self.panel: self.panel.stop()

    def game_categories(self,guild):
        return {c.category_id for c in guild.voice_channels if c.name==config.TEMP_VC_HUB_NAME and c.category_id
                and not any(w in c.category.name.casefold() for w in ('archived','封存','hidden'))}

    def is_game(self,channel):
        return channel.guild.id==config.GUILD_ID and channel.category_id in self.game_categories(channel.guild)

    def help_source(self,channel):
        if not channel or channel.guild.id!=config.GUILD_ID: return False
        if isinstance(channel,discord.Thread):
            if channel.type==discord.ChannelType.private_thread: return False
            parent=channel.parent
        else: parent=channel
        if not isinstance(parent,(discord.TextChannel,discord.ForumChannel)) or not self.is_game(parent): return False
        if isinstance(parent,discord.ForumChannel): return True
        return bool(re.search('吹水|討論|求助|組隊',parent.name))

    def can_read_source(self,channel,member):
        if not self.help_source(channel): return False
        p=channel.permissions_for(member)
        return p.view_channel and p.read_message_history

    @staticmethod
    def help_text(message):
        title=message.channel.name+'\n' if isinstance(message.channel,discord.Thread) and message.id==message.channel.id else ''
        return title+(message.content or '')

    async def observe_help(self,message,emit=True):
        if not self.enabled or not self.store or not message.guild or message.author.bot or not self.help_source(message.channel): return
        if message.reference and message.reference.message_id:
            await asyncio.to_thread(self.store.reply,message.reference.message_id,message.author.id)
        if isinstance(message.channel,discord.Thread) and message.id!=message.channel.id:
            await asyncio.to_thread(self.store.reply,message.channel.id,message.author.id)
        await asyncio.to_thread(self.store.observe,message.id,message.channel.id,message.author.id,message.created_at.timestamp(),detect_help(self.help_text(message)),time.time())
        if emit and self.pulse and detect_help(self.help_text(message)):
            row=await asyncio.to_thread(self.store.detection,message.id)
            if row and row['state'] in {'open','claimed','handoff'}:
                await self.record_pulse(message,'help')

    def pulse_source(self,channel):
        if not self.help_source(channel): return False
        parent=channel.parent if isinstance(channel,discord.Thread) else channel
        if parent.category is None: return False
        name=(parent.category.name+' '+parent.name).casefold()
        return not any(word in name for word in ('admin','管理','hidden','archive','封存','金主','staff','private','私密','測試'))

    async def record_pulse(self,message,kind):
        if not self.pulse or not self.pulse_source(message.channel): return
        parent=message.channel.parent if isinstance(message.channel,discord.Thread) else message.channel
        key=f'{kind}:{message.id}'
        if kind=='newcomer': key=f'newcomer:{message.author.id}:{int(time.time()//86400)}'
        await asyncio.to_thread(self.pulse.record,key,time.time(),parent.category_id,message.channel.id,kind,message.author.id,message.id)

    async def record_attention_pulse(self,message):
        if not self.pulse or not self.pulse_source(message.channel): return
        for kind in {'lfg','newcomer'}:
            if any(r['message']==message.id and r['kind']==kind and not (kind=='lfg' and r['replied']) for r in self.window.attention):
                await self.record_pulse(message,kind)

    def observe_attention(self,message):
        if not self.help_source(message.channel) or message.author.bot: return
        now=time.time()
        at=message.created_at.timestamp()
        if not now-1800<=at<=now+300: return
        joined=getattr(message.author,'joined_at',None)
        newcomer=bool(joined and now-7*86400<=joined.timestamp()<=now)
        text=re.sub(r'```.*?```','',self.help_text(message).casefold(),flags=re.S)
        text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))
        lfg=bool(re.search(r'有[冇無沒]人.{0,15}(?:打|玩|一齊|組)|搵.{0,8}隊友|徵.{0,8}隊友|缺.{0,4}人|\blfg\b|looking for (?:group|players)',text))
        if re.search(r'夠人|滿人|組滿|已成團|搵到隊友|找到隊友|found (?:a )?(?:team|group)|full now',text): lfg=False
        self.window.note_attention(message.id,message.channel.id,message.author.id,at,newcomer=newcomer,lfg=lfg)
        reference=getattr(message,'reference',None)
        if reference and reference.message_id: self.window.attention_reply(reference.message_id,message.author.id)
        if isinstance(message.channel,discord.Thread) and message.id!=message.channel.id:
            self.window.attention_reply(message.channel.id,message.author.id)

    def attention_lines(self,member,now):
        lines=[]
        for row in reversed(self.window.attention):
            if row['at']<now-1800 or (row['kind']=='lfg' and row['replied']): continue
            channel=self.bot.get_channel(row['channel']) or member.guild.get_thread(row['channel'])
            if not self.can_read_source(channel,member): continue
            label='近 7 日加入成員發言' if row['kind']=='newcomer' else '搵隊友，未觀察到直接回覆'
            room=discord.utils.escape_markdown(channel.name[:40])
            link=f'https://discord.com/channels/{config.GUILD_ID}/{row["channel"]}/{row["message"]}'
            lines.append(f'**{room}** · {label} · [去接應]({link})')
        return lines

    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.enabled or not message.guild or message.author.bot: return
        if isinstance(message.channel,discord.TextChannel) and self.is_game(message.channel):
            self.window.add(message.channel.id,message.author.id,time.time())
        self.observe_attention(message)
        await self.record_pulse(message,'chat')
        await self.record_attention_pulse(message)
        await self.observe_help(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if not self.enabled or payload.guild_id!=config.GUILD_ID: return
        channel=self.bot.get_channel(payload.channel_id)
        if not self.help_source(channel): return
        try:
            message=await channel.fetch_message(payload.message_id)
            self.observe_attention(message)
            await self.observe_help(message)
        except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        if self.enabled and self.store and payload.guild_id==config.GUILD_ID:
            self.window.attention_delete(payload.message_id)
            if self.pulse: await asyncio.to_thread(self.pulse.withdraw,payload.message_id)
            await asyncio.to_thread(self.store.withdraw,payload.message_id,time.time())

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        if self.enabled and self.store and payload.guild_id==config.GUILD_ID:
            for message_id in payload.message_ids:
                self.window.attention_delete(message_id)
                if self.pulse: await asyncio.to_thread(self.pulse.withdraw,message_id)
                await asyncio.to_thread(self.store.withdraw,message_id,time.time())

    @tasks.loop(count=1)
    async def backfill(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild: return
        channels=[c for c in [*guild.text_channels,*guild.threads] if self.help_source(c)]
        after=datetime.now(timezone.utc)-timedelta(hours=6)
        scanned=0
        for channel in channels[:60]:
            if not self.can_read_source(channel,guild.me): continue
            try:
                messages=[m async for m in channel.history(limit=30,after=after)]
                for message in reversed(messages): await self.observe_help(message,emit=False)
                scanned+=1
            except discord.HTTPException: continue
        await asyncio.to_thread(self.store.set,'detector_scan',f'{scanned} channels; last 6h / max 30 per channel; active public threads only')
        log.info('Helper detection initial scan complete: %s channels',scanned)

    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        if not self.enabled or member.bot or member.guild.id!=config.GUILD_ID or before.channel==after.channel: return
        now=time.time()
        if before.channel and not any(not m.bot for m in before.channel.members): self.window.voice_started.pop(before.channel.id,None)
        if after.channel and self.is_game(after.channel) and sum(not m.bot for m in after.channel.members)==1:
            self.window.voice_started.setdefault(after.channel.id,now)
        for category_id in {c.category_id for c in (before.channel,after.channel) if c and c.name!=config.TEMP_VC_HUB_NAME}:
            await self.record_voice_pulse(member.guild,category_id)

    async def record_voice_pulse(self,guild,category_id):
        if not self.pulse or category_id not in self.game_categories(guild): return
        category=guild.get_channel(category_id)
        if not category or any(w in category.name.casefold() for w in ('admin','管理','hidden','archive','封存','金主','staff')): return
        occupied=[c for c in guild.voice_channels if c.category_id==category_id and c.name!=config.TEMP_VC_HUB_NAME and any(not m.bot for m in c.members)]
        people={m.id for c in occupied for m in c.members if not m.bot}
        now=time.time()
        await asyncio.to_thread(self.pulse.record,f'voice:{category_id}:{int(now*1000000)}',now,category_id,0,'voice',0,0,dict(rooms=len(occupied),people=len(people)))

    async def access(self,i):
        valid=(self.enabled and self.channel is not None and i.guild_id==config.GUILD_ID and i.channel_id==self.channel.id
               and isinstance(i.user,discord.Member) and self.channel.permissions_for(i.user).view_channel
               and (i.user.guild_permissions.administrator or any(r.id in {*config.HELPER_ROLE_IDS,self.tester_id} for r in i.user.roles)))
        if not valid: await i.response.send_message(f'請到 <#{ROOM_ID}> 使用 Helper Dashboard。',ephemeral=True)
        return valid

    async def bootstrap(self):
        guild=self.bot.get_guild(config.GUILD_ID)
        if not guild: return
        rss=guild.get_channel(RSS_ROOM)
        tester=discord.utils.get(guild.roles,name='🧪 Tester')
        helpers=[guild.get_role(r) for r in config.HELPER_ROLE_IDS]
        helpers=[r for r in helpers if r]
        if not rss or not rss.category or not tester or not helpers or not guild.me: raise RuntimeError('Missing verified sandbox category/roles')
        self.tester_id=tester.id
        await asyncio.to_thread(self.store.set,'tester_role',tester.id)
        key=await asyncio.to_thread(self.store.get,'dashboard_channel')
        # Existing deployment: identify the owned channel by immutable identity.
        # Names/topics are editable display copy, not access or ownership markers.
        if key is not None and key != str(ROOM_ID):
            raise RuntimeError('Unexpected helper sandbox channel identity')
        channel=guild.get_channel(ROOM_ID)
        if (not isinstance(channel,discord.TextChannel) or channel.id!=ROOM_ID
                or channel.guild.id!=config.GUILD_ID
                or channel.permissions_for(guild.default_role).view_channel):
            raise RuntimeError('Unsafe or missing helper sandbox target')
        for role in [tester,*helpers]:
            if not channel.permissions_for(role).view_channel or not channel.permissions_for(role).read_message_history:
                raise RuntimeError('Helper/Tester sandbox access missing')
        await asyncio.to_thread(self.store.set,'dashboard_channel',ROOM_ID)
        self.channel=channel
        message_id=await asyncio.to_thread(self.store.get,'dashboard_panel')
        if not message_id:
            if not await asyncio.to_thread(self.store.reserve,'dashboard_panel'): return
            message=await channel.send(embed=await self.demo_embed(),view=HelperPanel(self),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.store.set,'dashboard_panel',message.id)
            log.info('Helper sandbox ready channel=%s message=%s',channel.id,message.id)
        elif message_id=='reserved': raise RuntimeError('Unconfirmed panel creation; requires inspection')
        else: await self.refresh()

    async def demo_embed(self):
        from core.helper_dashboard import dashboard_embed
        return dashboard_embed(self)

    async def publish_pulse(self):
        if not self.pulse or not self.channel: return
        guild=self.channel.guild
        if self.channel.permissions_for(guild.default_role).view_channel: return
        batch=await asyncio.to_thread(self.pulse.claim,time.time())
        if not batch: return
        try:
            valid=[]
            for event in batch['events']:
                category=guild.get_channel(event['category'])
                if not category or event['category'] not in self.game_categories(guild): continue
                if any(w in category.name.casefold() for w in ('admin','管理','hidden','archive','封存','金主','staff')): continue
                if event['kind']!='voice':
                    source=self.bot.get_channel(event['channel']) or guild.get_thread(event['channel'])
                    if not self.pulse_source(source): continue
                    if event['kind']=='help':
                        row=await asyncio.to_thread(self.store.detection,event['message'])
                        if not row or row['state'] not in {'open','claimed','handoff'}: continue
                valid.append(event)
            lines=[]
            groups=summarize(valid)
            for category_id,group in groups:
                category=guild.get_channel(category_id)
                label=discord.utils.escape_markdown(category.name[:40])
                at=datetime.fromtimestamp(group['at'],ZoneInfo('Asia/Hong_Kong')).strftime('%H:%M')
                line=f'{at} · **{label}**｜'+' · '.join(fragments(group))
                if len('\n'.join(lines+[line]))>1750: break
                lines.append(line)
            if len(lines)<len(groups): lines.append(f'另有 {len(groups)-len(lines)} 個遊戲區有活動。')
            if not lines:
                await asyncio.to_thread(self.pulse.finish,batch['bucket'],'skipped')
                return
            message=await self.channel.send('\n'.join(lines),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.pulse.finish,batch['bucket'],'sent',message.id)
            await asyncio.to_thread(self.store.set,'pulse_latest',message.id)
            log.info('Helper pulse log posted: channel=%s message=%s',self.channel.id,message.id)
        except Exception as exc:
            await asyncio.to_thread(self.pulse.finish,batch['bucket'],'uncertain',0,type(exc).__name__)
            log.exception('Helper pulse send uncertain; not automatically resent')

    @tasks.loop(minutes=1)
    async def pulse_tick(self):
        try:
            if not self.channel: return
            await self.publish_pulse()
        except Exception: log.exception('Helper pulse loop needs inspection')

    def live_embed(self,member):
        guild=member.guild
        now=time.time()
        categories=self.game_categories(guild)
        grouped={}
        for channel_id,count in self.window.counts(now).items():
            ch=guild.get_channel(channel_id)
            if not ch or ch.category_id not in categories: continue
            permissions=ch.permissions_for(member)
            if not permissions.view_channel or not permissions.read_message_history: continue
            group=grouped.setdefault(ch.category_id,{'users':set(),'messages':0,'channels':[]})
            group['users'].update(count['users'])
            group['messages']+=count['messages']
            group['channels'].append(ch)
        chat=[]
        for cid,data in sorted(grouped.items(),key=lambda item:-item[1]['messages'])[:8]:
            category=guild.get_channel(cid)
            name=discord.utils.escape_markdown(category.name[:70])
            link=data['channels'][0].jump_url
            chat.append(f"**{name}** · {len(data['users'])} 人／{data['messages']} 則 · [去睇]({link})")
        voice=[]
        for ch in guild.voice_channels:
            if ch.category_id not in categories or ch.name==config.TEMP_VC_HUB_NAME: continue
            permissions=ch.permissions_for(member)
            if not permissions.view_channel or not permissions.connect: continue
            members=[m for m in ch.members if not m.bot]
            if not members: continue
            started=self.window.voice_started.get(ch.id)
            duration=f' · 觀察到開房 <t:{int(started)}:R>' if started else ' · 開始時間未記錄'
            voice.append(f"**{discord.utils.escape_markdown(ch.category.name[:45])}** · {len(members)} 人{duration} · [去頻道]({ch.jump_url})")
        embed=discord.Embed(title='🧭 即時社群活動｜只供你查看',description=f'文字：最近 30 分鐘內、Bot 自 <t:{int(self.window.started)}:t> 起收到嘅活動。只計人類訊息；冇資料唔代表冇人傾計。')
        embed.add_field(name='💬 活躍遊戲區',value='\n'.join(chat)[:1024] or '暫未記錄到你可查看嘅遊戲區活動。',inline=False)
        embed.add_field(name='🎙️ 而家開緊 call',value='\n'.join(voice[:8])[:1024] or '暫無你可查看及加入嘅遊戲語音房。',inline=False)
        embed.add_field(name='🆘 疑似求助',value='已自動偵測；返回看板按「待接應」查看及跟進。未啟用 ping。',inline=False)
        note='只涵蓋設有「開一個小隊 call」嘅遊戲分類；聊天統計不含討論串；不轉貼私密聊天內容。'
        if now<self.window.truncated_until: note+=' 活動量超過暫存上限，計數不完整。'
        embed.set_footer(text=note)
        return embed

    async def refresh(self):
        async with self.lock:
            await asyncio.to_thread(self.store.prune,time.time())
            if not self.channel: return
            key=await asyncio.to_thread(self.store.get,'dashboard_panel')
            if not key or key=='reserved': return
            message=await self.channel.fetch_message(int(key))
            await message.edit(embed=await self.demo_embed(),view=HelperPanel(self),allowed_mentions=discord.AllowedMentions.none())

    @tasks.loop(minutes=2)
    async def tick(self):
        try:
            if not self.channel: await self.bootstrap()
            else: await self.refresh()
        except Exception: log.exception('Helper sandbox needs inspection')

    @pulse_tick.before_loop
    @backfill.before_loop
    @tick.before_loop
    async def ready(self): await self.bot.wait_until_ready()


async def setup(bot): await bot.add_cog(HelperSandbox(bot))
