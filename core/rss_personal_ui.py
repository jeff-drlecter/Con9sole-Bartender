"""Persistent sandbox entry panel and private, member-owned preference controls."""
import asyncio
import time
import discord
from core.rss_preferences import OPTIONS, keywords, matches, fixtures, personal_preview
from core.rss_featured_ui import show_featured
from core.rss_wording import rss_text


class NewsCardPanel(discord.ui.View):
    """Compact public card controls, restored across bot restarts."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, interaction):
        return await self.cog.personal_access(interaction)

    @discord.ui.button(label='我的情報', style=discord.ButtonStyle.primary, custom_id='rss:card:news:v1')
    async def news(self, interaction, button):
        await show_news(self.cog, interaction)

    @discord.ui.button(label='調整偏好', custom_id='rss:card:preferences:v1')
    async def preferences(self, interaction, button):
        pref = await asyncio.to_thread(self.cog.preferences.get, interaction.user.id)
        await interaction.response.send_message(rss_text(interaction.user, 'preferences'),
            view=PreferencesView(self.cog, interaction.user.id, pref, interaction.user), ephemeral=True)

    @discord.ui.button(label='新聞頻道接收', custom_id='rss:card:channels:v1')
    async def channels(self, interaction, button):
        await self.cog.channel_preferences_entry(interaction)


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
        await interaction.response.send_message(rss_text(interaction.user, 'preferences'),view=PreferencesView(self.cog,interaction.user.id,pref,interaction.user),ephemeral=True)


    @discord.ui.button(label='今日精選',custom_id='rss:sandbox:today:v1',row=1)
    async def today(self,interaction,button):
        await show_featured(self.cog,interaction,'today')

    @discord.ui.button(label='本月精選',custom_id='rss:sandbox:month:v1',row=1)
    async def month(self,interaction,button):
        await show_featured(self.cog,interaction,'month')

    @discord.ui.button(label='最近熱門',custom_id='rss:sandbox:hot:v1',row=1)
    async def hot(self,interaction,button):
        await show_featured(self.cog,interaction,'hot')


async def show_news(cog,interaction,demo=False):
    await interaction.response.defer(ephemeral=True)
    pref=await asyncio.to_thread(cog.preferences.get,interaction.user.id)
    now=time.time()
    articles=([a for a in fixtures(now) if matches(a,pref)] if demo else
              await asyncio.to_thread(personal_preview,cog.store,cog.digest_config,cog.sources,pref,now))
    if not demo and cog.store_news_available(interaction):
        from core.store_sources import combine_articles
        extra=await asyncio.to_thread(cog.store_news.preview,cog.digest_config,pref,now)
        articles=combine_articles(articles+extra,config=cog.digest_config)
    label='🧪 虛構範例・我的情報' if demo else '我的情報・真實新聞'
    content = rss_text(interaction.user, 'fixture' if demo else 'scope')
    if not demo: content += '\n' + cog.store_news_scope(interaction)
    if not articles: content += '\n' + rss_text(interaction.user, 'empty')
    await interaction.followup.send(content,embed=cog.render({'kind':'digest','articles':articles},now,label) if articles else None,
                                    ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class Choice(discord.ui.Select):
    def __init__(self,key,pref):
        self.key=key
        super().__init__(placeholder={'platforms':'平台','stores':'商店（不限商店會包含全部）','kinds':'內容類型','regions':'商店地區（與用語設定分開）'}[key],
                         min_values=1,max_values=len(OPTIONS[key]),
                         options=[discord.SelectOption(label=label,value=value,default=value in pref[key]) for value,label in OPTIONS[key].items()])

    async def callback(self,interaction):
        # Fresh read prevents separate settings panels from overwriting other fields.
        pref=await asyncio.to_thread(self.view.cog.preferences.get,interaction.user.id)
        pref[self.key]=list(self.values)
        await asyncio.to_thread(self.view.cog.preferences.put,interaction.user.id,pref)
        await interaction.response.edit_message(content=rss_text(interaction.user, 'saved'),view=PreferencesView(self.view.cog,interaction.user.id,pref,interaction.user))


class KeywordModal(discord.ui.Modal,title='個人關鍵字'):
    include=discord.ui.TextInput(label='想看的字（任一符合；逗號分隔）',required=False,max_length=400)
    exclude=discord.ui.TextInput(label='不想看的字（排除優先；逗號分隔）',required=False,max_length=400)

    def __init__(self,cog,owner,pref,member=None):
        super().__init__()
        self.cog,self.owner=cog,owner
        self.include.label=rss_text(member, 'include')
        self.exclude.label=rss_text(member, 'exclude')
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
    def __init__(self,cog,owner,pref,member=None):
        super().__init__(timeout=600)
        self.cog,self.owner=cog,owner
        for key in OPTIONS: self.add_item(Choice(key,pref))
        if not cog.digest_config.simulation:
            self.remove_item(self.demo)

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message(rss_text(interaction.user, 'own'),ephemeral=True)
            return False
        return await self.cog.personal_access(interaction)

    @discord.ui.button(label='關鍵字',row=4)
    async def edit_keywords(self,interaction,button):
        pref=await asyncio.to_thread(self.cog.preferences.get,self.owner)
        await interaction.response.send_modal(KeywordModal(self.cog,self.owner,pref,interaction.user))

    @discord.ui.button(label='查看我的情報',row=4,style=discord.ButtonStyle.primary)
    async def news(self,interaction,button):
        await show_news(self.cog,interaction)

    @discord.ui.button(label='虛構資料試篩選',row=4)
    async def demo(self,interaction,button):
        await show_news(self.cog,interaction,True)

