import asyncio
import time
import discord
from core.helper_detection import detect_help


def short(text,length=140):
    return discord.utils.escape_markdown(' '.join(text.split())[:length])


async def show_pending(cog,i,closed=False):
    await i.response.defer(ephemeral=True)
    rows=await asyncio.to_thread(cog.store.candidates,time.time(),closed)
    visible=[]
    checked=0
    # Permission-filter before fetching: no hidden-channel counts or excerpts leak.
    for row in rows:
        channel=cog.bot.get_channel(row['channel_id'])
        if channel is None: channel=i.guild.get_thread(row['channel_id'])
        if not cog.can_read_source(channel,i.user): continue
        checked+=1
        if checked>20: break
        try: message=await channel.fetch_message(row['message_id'])
        except discord.NotFound:
            await asyncio.to_thread(cog.store.withdraw,row['message_id'],time.time())
            continue
        except discord.HTTPException: continue
        if not closed and not detect_help(cog.help_text(message)):
            await asyncio.to_thread(cog.store.withdraw,row['message_id'],time.time())
            continue
        visible.append((row,message))
        if len(visible)>=8: break
    embed=discord.Embed(title='🆘 求助處理記錄' if closed else '🆘 待接應｜自動偵測、待人確認',description='只顯示你有權閱讀嘅原訊息。關鍵字可能誤判；「有人回覆」唔代表已解決。')
    for row,message in visible:
        state={'open':'待確認','claimed':'跟進中','handoff':'待轉交','done':'已完成','dismissed':'非求助'}[row['state']]
        name=short(message.channel.name,50)+' · '+state
        owner=f" · 負責 <@{row['owner']}>" if row['owner'] else ''
        reply='有人回覆' if row['replied'] else '未觀察到直接回覆'
        content=short(cog.help_text(message)) or '（內容已變更）'
        embed.add_field(name=name,value=f"{content}\n[去原訊息]({message.jump_url}) · {reply}{owner}\n{row['reason']} · <t:{int(row['created'])}:R>",inline=False)
    if not visible: embed.description+='\n目前冇可顯示嘅項目。只掃指定遊戲吹水／討論區；唔代表所有問題已解決。'
    await i.followup.send(embed=embed,view=DetectionView(cog,i.user.id,visible) if visible and not closed else None,
        ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class CandidateSelect(discord.ui.Select):
    def __init__(self,visible):
        super().__init__(placeholder='選擇需要接應嘅訊息',options=[discord.SelectOption(label=(message.channel.name+'｜'+short(message.content,60))[:100],value=str(row['message_id'])) for row,message in visible])
    async def callback(self,i):
        self.view.selected=int(self.values[0])
        await i.response.edit_message(content='已選擇；按「我跟進」後，到原頻道回覆。')


class DetectionView(discord.ui.View):
    def __init__(self,cog,owner,visible):
        super().__init__(timeout=600)
        self.cog,self.owner,self.selected=cog,owner,None
        self.add_item(CandidateSelect(visible))
    async def interaction_check(self,i):
        if i.user.id!=self.owner:
            await i.response.send_message('請開自己嘅待接應清單。',ephemeral=True)
            return False
        return await self.cog.access(i)
    async def act(self,i,action):
        await i.response.defer(ephemeral=True)
        row=await asyncio.to_thread(self.cog.store.detection,self.selected) if self.selected else None
        channel=(self.cog.bot.get_channel(row['channel_id']) or i.guild.get_thread(row['channel_id'])) if row else None
        if not row or not self.cog.can_read_source(channel,i.user):
            await i.followup.send('請先選擇你仍有權閱讀嘅訊息。',ephemeral=True)
            return
        try:
            message=await channel.fetch_message(row['message_id'])
            if not detect_help(self.cog.help_text(message)):
                await asyncio.to_thread(self.cog.store.withdraw,row['message_id'],time.time())
                await i.followup.send('原訊息已變更，不再符合求助條件。',ephemeral=True)
                return
            label=await asyncio.to_thread(self.cog.store.act,self.selected,i.user.id,action,time.time(),i.user.guild_permissions.administrator)
            await i.followup.send(label+'。\n'+message.jump_url,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            await asyncio.to_thread(self.cog.store.withdraw,row['message_id'],time.time())
            await i.followup.send('原訊息已刪除。',ephemeral=True)
        except discord.HTTPException:
            await i.followup.send('暫時無法核對原訊息，未作更改。',ephemeral=True)
        except ValueError as exc: await i.followup.send(str(exc),ephemeral=True)
    @discord.ui.button(label='我跟進',row=1,style=discord.ButtonStyle.primary)
    async def claim(self,i,button): await self.act(i,'claim')
    @discord.ui.button(label='已處理',row=1,style=discord.ButtonStyle.success)
    async def done(self,i,button): await self.act(i,'done')
    @discord.ui.button(label='轉交',row=1)
    async def handoff(self,i,button): await self.act(i,'handoff')
    @discord.ui.button(label='不是求助',row=1)
    async def dismiss(self,i,button): await self.act(i,'dismiss')
