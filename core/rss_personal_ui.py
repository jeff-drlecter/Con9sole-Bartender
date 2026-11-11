"""Persistent sandbox entry panel and private, member-owned preference controls."""
import asyncio
import time
import discord
from core.rss_preferences import OPTIONS, keywords, matches, fixtures, personal_preview


class PersonalPanel(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog

    async def interaction_check(self,interaction):
        return await self.cog.personal_access(interaction)

    @discord.ui.button(label='我的情報',style=discord.ButtonStyle.primary,custom_id='rss:sandbox:personal:v1')
    async def news(self,interaction,button):
        await show_news(self.cog,interaction)

    @discord.ui.button(label='調整偏好',custom_id='rss:sandbox:preferences:v1')
    async def preferences(self,interaction,button):
        pref=await asyncio.to_thread(self.cog.preferences.get,interaction.user.id)
        await interaction.response.send_message('揀完會自動儲存。關鍵字可留空；只影響你嘅私人摘要。',view=PreferencesView(self.cog,interaction.user.id,pref),ephemeral=True)


async def show_news(cog,interaction,demo=False):
    await interaction.response.defer(ephemeral=True)
    pref=await asyncio.to_thread(cog.preferences.get,interaction.user.id)
    now=time.time()
    articles=([a for a in fixtures(now) if matches(a,pref)] if demo else
              await asyncio.to_thread(personal_preview,cog.store,cog.digest_config,cog.sources,pref,now))
    label='🧪 虛構範例・我的情報' if demo else '🧪 我的情報・真實新聞'
    content=('虛構資料，只供測試；唔係真實優惠。' if demo else
             '最近 24 小時｜按平台文字線索分類，可能漏收。Steam／Epic 限免資料尚未接入；冇已核實優惠就唔會冒充限免。')
    if not articles: content+='\n目前冇符合偏好嘅內容。可以調整篩選，或用「虛構資料試篩選」。'
    await interaction.followup.send(content,embed=cog.render({'kind':'digest','articles':articles},now,label) if articles else None,
                                    ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class Choice(discord.ui.Select):
    def __init__(self,key,pref):
        self.key=key
        super().__init__(placeholder={'platforms':'平台','stores':'商店（不限商店會包含全部）','kinds':'內容類型'}[key],
                         min_values=1,max_values=len(OPTIONS[key]),
                         options=[discord.SelectOption(label=label,value=value,default=value in pref[key]) for value,label in OPTIONS[key].items()])

    async def callback(self,interaction):
        # Fresh read prevents separate settings panels from overwriting other fields.
        pref=await asyncio.to_thread(self.view.cog.preferences.get,interaction.user.id)
        pref[self.key]=list(self.values)
        await asyncio.to_thread(self.view.cog.preferences.put,interaction.user.id,pref)
        await interaction.response.edit_message(content='✅ 已儲存。按「睇我的情報」試效果。',view=PreferencesView(self.view.cog,interaction.user.id,pref))


class KeywordModal(discord.ui.Modal,title='個人關鍵字'):
    include=discord.ui.TextInput(label='想睇嘅字（任一符合；逗號分隔）',required=False,max_length=400)
    exclude=discord.ui.TextInput(label='唔想睇嘅字（排除優先；逗號分隔）',required=False,max_length=400)

    def __init__(self,cog,owner,pref):
        super().__init__()
        self.cog,self.owner=cog,owner
        self.include.default=', '.join(pref['include'])
        self.exclude.default=', '.join(pref['exclude'])

    async def on_submit(self,interaction):
        if interaction.user.id!=self.owner or not await self.cog.personal_access(interaction): return
        pref=await asyncio.to_thread(self.cog.preferences.get,self.owner)
        pref.update(include=keywords(self.include.value),exclude=keywords(self.exclude.value))
        try: await asyncio.to_thread(self.cog.preferences.put,self.owner,pref)
        except ValueError as exc:
            await interaction.response.send_message(str(exc),ephemeral=True)
            return
        await interaction.response.send_message('✅ 關鍵字已儲存。',ephemeral=True)


class PreferencesView(discord.ui.View):
    def __init__(self,cog,owner,pref):
        super().__init__(timeout=600)
        self.cog,self.owner=cog,owner
        for key in OPTIONS: self.add_item(Choice(key,pref))

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message('請用自己嘅「調整偏好」。',ephemeral=True)
            return False
        return await self.cog.personal_access(interaction)

    @discord.ui.button(label='關鍵字',row=3)
    async def edit_keywords(self,interaction,button):
        pref=await asyncio.to_thread(self.cog.preferences.get,self.owner)
        await interaction.response.send_modal(KeywordModal(self.cog,self.owner,pref))

    @discord.ui.button(label='睇我的情報',row=3,style=discord.ButtonStyle.primary)
    async def news(self,interaction,button):
        await show_news(self.cog,interaction)

    @discord.ui.button(label='虛構資料試篩選',row=3)
    async def demo(self,interaction,button):
        await show_news(self.cog,interaction,True)
