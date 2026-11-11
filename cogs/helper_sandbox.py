"""Opt-in Helper demo: no real help alerts or copying cross-channel content."""
import asyncio
import logging
import os
import time
import discord
from discord.ext import commands,tasks
import config
from core.storage_paths import DATA_DIR
from core.helper_sandbox import HelperStore,ActivityWindow

log=logging.getLogger(__name__)
ROOM='helper-模擬區'
TOPIC='Helper sandbox v1 — 虛構求助流程；真實活動只按個人原有權限顯示。'
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

    @discord.ui.button(label='新增測試求助',custom_id='helper:sandbox:create:v1')
    async def create(self,i,button):
        await i.response.defer(ephemeral=True)
        try:
            key,created=await asyncio.to_thread(self.cog.store.create,i.user.id,time.time())
            await self.cog.refresh()
            await i.followup.send(f"{'已建立' if created else '你已有'}測試求助 #{key}。按「跟進求助」試接手。",ephemeral=True)
        except ValueError as exc: await i.followup.send(str(exc),ephemeral=True)

    @discord.ui.button(label='跟進求助',custom_id='helper:sandbox:manage:v1')
    async def manage(self,i,button):
        rows=await asyncio.to_thread(self.cog.store.active)
        if not rows:
            await i.response.send_message('暫無未完成測試；先按「新增測試求助」。',ephemeral=True)
            return
        await i.response.send_message('選擇虛構求助，再試接手、轉交或完成。',view=RequestView(self.cog,i.user.id,rows),ephemeral=True)

    @discord.ui.button(label='值班／暫停（模擬）',custom_id='helper:sandbox:duty:v1',row=1)
    async def duty(self,i,button):
        enabled=await asyncio.to_thread(self.cog.store.toggle_duty,i.user.id)
        await i.response.send_message(('🟢 已設為值班' if enabled else '⚪ 已暫停')+'（模擬設定已保存；未啟用真實提醒）。',ephemeral=True)

    @discord.ui.button(label='測試歷史',custom_id='helper:sandbox:history:v1',row=1)
    async def history(self,i,button):
        rows=await asyncio.to_thread(self.cog.store.history)
        lines=[f"#{r['request_id']} · {r['action']} · {'系統範例' if r['actor']==0 else '<@'+str(r['actor'])+'>'} · <t:{int(r['at'])}:R>" for r in rows]
        await i.response.send_message('\n'.join(lines) or '暫無測試記錄。',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


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
        self.store=HelperStore(DATA_DIR/'helper_sandbox.sqlite3')
        self.panel=HelperPanel(self)
        self.bot.add_view(self.panel)
        self.tick.start()

    async def cog_unload(self):
        self.tick.cancel()
        if self.panel: self.panel.stop()

    def game_categories(self,guild):
        return {c.category_id for c in guild.voice_channels if c.name==config.TEMP_VC_HUB_NAME and c.category_id
                and not any(w in c.category.name.casefold() for w in ('archived','封存','hidden'))}

    def is_game(self,channel):
        return channel.guild.id==config.GUILD_ID and channel.category_id in self.game_categories(channel.guild)

    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.enabled or not message.guild or message.author.bot or not isinstance(message.channel,discord.TextChannel): return
        if self.is_game(message.channel): self.window.add(message.channel.id,message.author.id,time.time())

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
            if any(c.name==ROOM and c.topic!=TOPIC for c in guild.text_channels):
                raise RuntimeError('Existing channel name is not owned by this sandbox')
            candidates=[c for c in guild.text_channels if c.name==ROOM and c.topic==TOPIC]
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
        if not isinstance(channel,discord.TextChannel) or channel.name!=ROOM or channel.topic!=TOPIC or channel.permissions_for(guild.default_role).view_channel:
            raise RuntimeError('Unsafe or missing helper sandbox target')
        for role in [tester,*helpers]:
            if not channel.permissions_for(role).view_channel or not channel.permissions_for(role).read_message_history:
                raise RuntimeError('Helper/Tester sandbox access missing')
        self.channel=channel
        if not await asyncio.to_thread(self.store.get,'seeded'):
            await asyncio.to_thread(self.store.create,0,time.time()-720)
            await asyncio.to_thread(self.store.set,'seeded','1')
        message_id=await asyncio.to_thread(self.store.get,'panel')
        if not message_id:
            if not await asyncio.to_thread(self.store.reserve,'panel'): return
            message=await channel.send(embed=await self.demo_embed(),view=HelperPanel(self),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.store.set,'panel',message.id)
            log.info('Helper sandbox ready channel=%s message=%s',channel.id,message.id)
        elif message_id=='reserved': raise RuntimeError('Unconfirmed panel creation; requires inspection')

    async def demo_embed(self):
        rows=await asyncio.to_thread(self.store.active)
        embed=discord.Embed(title='🧭 Helper 動態沙盤｜虛構示範',description='呢張共用看板係測試資料。按「即時活動」先睇你有權查看嘅真實遊戲區；唔會監聽語音或轉貼聊天內容。')
        lines=[]
        for r in rows[:8]:
            owner=f"<@{r['owner']}>" if r['owner'] else '未有人接手'
            state={'open':'待接應','claimed':'跟進中','handoff':'需要其他 Helper'}[r['state']]
            lines.append(f"**#{r['id']} {state}** · {r['title']}\n{owner} · 建立 <t:{int(r['created'])}:R>")
        embed.add_field(name=f'🆘 測試求助（{len(rows)} 個未完成）',value='\n'.join(lines)[:1024] or '全部測試已完成；可以新增一個。',inline=False)
        embed.add_field(name='💬 傾計示意（虛構）',value='GTA｜近半小時 6 人、18 則訊息\nHelldivers｜近半小時 3 人、7 則訊息',inline=False)
        embed.add_field(name='🎙️ 開 call 示意（虛構）',value='FC｜4 人開緊 call · 35 分鐘',inline=False)
        history=await asyncio.to_thread(self.store.history)
        embed.add_field(name='最近測試記錄',value='\n'.join(f"#{r['request_id']} · {r['action']} · <t:{int(r['at'])}:R>" for r in history[:5]) or '暫無記錄',inline=False)
        embed.set_footer(text='每 2 分鐘更新同一張看板 · Helper / Tester 可睇歷史 · 無真實求助通知')
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
        embed.add_field(name='🆘 真實求助',value='本輪未啟用真實求助偵測／通知；請用共用看板試流程。',inline=False)
        note='只涵蓋設有「開一個小隊 call」嘅遊戲分類；不含討論串／私密聊天內容。'
        if now<self.window.truncated_until: note+=' 活動量超過暫存上限，計數不完整。'
        embed.set_footer(text=note)
        return embed

    async def refresh(self):
        async with self.lock:
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

    @tick.before_loop
    async def ready(self): await self.bot.wait_until_ready()


async def setup(bot): await bot.add_cog(HelperSandbox(bot))
