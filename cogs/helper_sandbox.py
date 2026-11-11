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

log=logging.getLogger(__name__)
ROOM='helper-模擬區'
LEGACY_TOPIC='Helper sandbox v1 — 虛構求助流程；真實活動只按個人原有權限顯示。'
TOPIC='Helper sandbox v2 — 自動偵測吹水／討論區疑似求助；按原有權限查看，未啟用 ping。'
RSS_ROOM=1570054214850183289


class HelperPanel(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog

    async def interaction_check(self,i): return await self.cog.access(i)

    @discord.ui.button(label='即時活動（私密）',custom_id='helper:sandbox:live:v1',style=discord.ButtonStyle.primary)
    async def live(self,i,button):
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=self.cog.live_embed(i.user),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label='偵測示例',custom_id='helper:sandbox:create:v1')
    async def create(self,i,button):
        examples=['MH 連唔到朋友個場，有冇人知點搞？','請問點樣配裝？','有冇人今晚打機？','搞掂咗，唔使幫啦','我可以幫你']
        lines=[('🆘 疑似求助' if detect_help(text) else '— 不列入')+'｜'+text for text in examples]
        await i.response.send_message('同一套偵測規則嘅示例（虛構）：\n'+'\n'.join(lines),ephemeral=True)

    @discord.ui.button(label='待接應（自動偵測）',custom_id='helper:sandbox:manage:v1',style=discord.ButtonStyle.success)
    async def manage(self,i,button):
        await show_pending(self.cog,i)

    @discord.ui.button(label='值班／暫停（模擬）',custom_id='helper:sandbox:duty:v1',row=1)
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
        self.channel=None
        self.panel=None
        self.tester_id=None
        self.window=ActivityWindow(time.time())
        self.lock=asyncio.Lock()

    async def cog_load(self):
        if not self.enabled: return
        self.store=DetectionStore(DATA_DIR/'helper_sandbox.sqlite3')
        await asyncio.to_thread(self.store.set,'detector_version','1')
        self.panel=HelperPanel(self)
        self.bot.add_view(self.panel)
        self.tick.start()
        self.backfill.start()

    async def cog_unload(self):
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

    async def observe_help(self,message):
        if not self.enabled or not self.store or not message.guild or message.author.bot or not self.help_source(message.channel): return
        if message.reference and message.reference.message_id:
            await asyncio.to_thread(self.store.reply,message.reference.message_id,message.author.id)
        if isinstance(message.channel,discord.Thread) and message.id!=message.channel.id:
            await asyncio.to_thread(self.store.reply,message.channel.id,message.author.id)
        await asyncio.to_thread(self.store.observe,message.id,message.channel.id,message.author.id,message.created_at.timestamp(),detect_help(self.help_text(message)),time.time())

    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.enabled or not message.guild or message.author.bot: return
        if isinstance(message.channel,discord.TextChannel) and self.is_game(message.channel):
            self.window.add(message.channel.id,message.author.id,time.time())
        await self.observe_help(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if not self.enabled or payload.guild_id!=config.GUILD_ID: return
        channel=self.bot.get_channel(payload.channel_id)
        if not self.help_source(channel): return
        try: await self.observe_help(await channel.fetch_message(payload.message_id))
        except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        if self.enabled and self.store and payload.guild_id==config.GUILD_ID:
            await asyncio.to_thread(self.store.withdraw,payload.message_id,time.time())

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        if self.enabled and self.store and payload.guild_id==config.GUILD_ID:
            for message_id in payload.message_ids:
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
                for message in reversed(messages): await self.observe_help(message)
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

    async def access(self,i):
        valid=(self.enabled and self.channel is not None and i.guild_id==config.GUILD_ID and i.channel_id==self.channel.id
               and isinstance(i.user,discord.Member) and self.channel.permissions_for(i.user).view_channel
               and (i.user.guild_permissions.administrator or any(r.id in {*config.HELPER_ROLE_IDS,self.tester_id} for r in i.user.roles)))
        if not valid: await i.response.send_message('只限 Helper／Tester 喺指定沙盤使用。',ephemeral=True)
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
        key=await asyncio.to_thread(self.store.get,'channel')
        if key and key!='reserved': channel=guild.get_channel(int(key))
        else:
            if any(c.name==ROOM and c.topic not in {TOPIC,LEGACY_TOPIC} for c in guild.text_channels):
                raise RuntimeError('Existing channel name is not owned by this sandbox')
            candidates=[c for c in guild.text_channels if c.name==ROOM and c.topic in {TOPIC,LEGACY_TOPIC}]
            if len(candidates)>1: raise RuntimeError('Ambiguous helper sandbox channels')
            channel=candidates[0] if candidates else None
            if channel is None:
                if not await asyncio.to_thread(self.store.reserve,'channel'): raise RuntimeError('Unconfirmed channel creation; requires inspection')
                overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),
                    guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,embed_links=True,read_message_history=True)}
                for role in [tester,*helpers]:
                    overwrites[role]=discord.PermissionOverwrite(view_channel=True,read_message_history=True,send_messages=True,add_reactions=True,use_application_commands=True)
                channel=await guild.create_text_channel(ROOM,category=rss.category,topic=TOPIC,overwrites=overwrites,reason='Authorized Helper/Tester sandbox demo')
            await asyncio.to_thread(self.store.set,'channel',channel.id)
        if not isinstance(channel,discord.TextChannel) or channel.name!=ROOM or channel.topic not in {TOPIC,LEGACY_TOPIC} or channel.permissions_for(guild.default_role).view_channel:
            raise RuntimeError('Unsafe or missing helper sandbox target')
        for role in [tester,*helpers]:
            if not channel.permissions_for(role).view_channel or not channel.permissions_for(role).read_message_history:
                raise RuntimeError('Helper/Tester sandbox access missing')
        if channel.topic==LEGACY_TOPIC:
            channel=await channel.edit(topic=TOPIC,reason='Switch sandbox to automatic help detection')
        self.channel=channel
        message_id=await asyncio.to_thread(self.store.get,'panel')
        if not message_id:
            if not await asyncio.to_thread(self.store.reserve,'panel'): return
            message=await channel.send(embed=await self.demo_embed(),view=HelperPanel(self),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.store.set,'panel',message.id)
            log.info('Helper sandbox ready channel=%s message=%s',channel.id,message.id)
        elif message_id=='reserved': raise RuntimeError('Unconfirmed panel creation; requires inspection')
        else: await self.refresh()

    async def demo_embed(self):
        embed=discord.Embed(title='🧭 Helper 動態沙盤｜自動偵測求助',description='Bot 留意遊戲吹水區、討論區及公開討論串嘅疑似求助。成員照常傾計，唔需要開單。')
        embed.add_field(name='🆘 待接應',value='按「待接應（自動偵測）」睇你有權閱讀嘅求助原文、連結及跟進狀態。\n我跟進 → 到原頻道幫手 → 已處理；誤判可按「不是求助」。',inline=False)
        embed.add_field(name='偵測方式',value='求助／請教、點樣做、點解、連唔到／搞唔掂等線索。單純問「有冇人打機」唔當求助。\n只標示疑似；有人直接回覆亦唔會自動當已解決。',inline=False)
        embed.add_field(name='💬🎙️ 其他活動',value='按「即時活動」睇遊戲區聊天人數及現有 call。',inline=False)
        embed.add_field(name='目前範圍',value='有小隊 call 入口嘅遊戲分類：吹水／討論／求助／組隊文字頻道，以及公開論壇討論串。\n啟動時最多 60 個頻道，各檢查近 6 小時最新 30 則；之後偵測新訊息及編輯。',inline=False)
        embed.set_footer(text='沙盤自動偵測已開 · 未 ping Helper · 私人清單按原有權限顯示 · 記錄保留 7 日')
        return embed

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
            key=await asyncio.to_thread(self.store.get,'panel')
            if not key or key=='reserved': return
            message=await self.channel.fetch_message(int(key))
            await message.edit(embed=await self.demo_embed(),view=HelperPanel(self),allowed_mentions=discord.AllowedMentions.none())

    @tasks.loop(minutes=2)
    async def tick(self):
        try:
            if not self.channel: await self.bootstrap()
            else: await self.refresh()
        except Exception: log.exception('Helper sandbox needs inspection')

    @backfill.before_loop
    @tick.before_loop
    async def ready(self): await self.bot.wait_until_ready()


async def setup(bot): await bot.add_cog(HelperSandbox(bot))
