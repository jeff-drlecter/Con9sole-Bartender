"""Existing, permission-checked next steps, shared with 03; never assigns roles."""
import discord
import config
from features.language_preferences import language
from features.notification_words import text
from core.private_source import Source, SourceUnavailable, fresh_access
from core.ui import SafeView


def words(member, neutral, hk):
    return hk if language(member)=='hk' else neutral


async def support_destination(interaction):
    if interaction.guild_id!=config.GUILD_ID or not interaction.guild:return None
    try:
        member,channel=await fresh_access(interaction.guild,interaction.user.id,config.SUPPORT_CHANNEL_ID)
        if not isinstance(channel,(discord.TextChannel,discord.ForumChannel)) or channel.guild.id!=config.GUILD_ID or channel.nsfw:return None
        p=channel.permissions_for(member)
        if p.view_channel and p.read_message_history and p.send_messages:return channel
    except (SourceUnavailable,discord.HTTPException,OSError):pass
    return None


async def show_next_steps(i, *, reason='no_destination', replace=False, return_to=None):
    """03 entry point: await show_next_steps(i, reason='unavailable'|'no_destination').

    Supports an already deferred interaction. return_to is a callback, not a grant.
    """
    source=Source(i.user.id,i.guild_id,i.channel_id)
    if not i.response.is_done():await i.response.defer(ephemeral=True,thinking=not replace)
    try:
        member,_,_=await source.resolve(i)
        kwargs=dict(content=text(member,reason),embed=None,view=NextSteps(source,member,return_to),allowed_mentions=discord.AllowedMentions.none())
    except SourceUnavailable:
        kwargs=dict(content=text(i.user,'denied'),embed=None,view=None,allowed_mentions=discord.AllowedMentions.none())
    if replace:await i.edit_original_response(**kwargs)
    else:await i.followup.send(**kwargs,ephemeral=True)


async def show_route(i,action,*,source=None,return_to=None,replace=False):
    source=source or Source(i.user.id,i.guild_id,i.channel_id)
    if not i.response.is_done():await i.response.defer(ephemeral=True,thinking=not replace)
    try:
        member,_,_=await source.resolve(i)
        if action=='observe':
            content=words(member,'可以先看看。到 <id:customize> 自選聊天、新聞或直播內容；日後也在這裡選擇遊戲，再按「約一局」。','可以先睇吓。去 <id:customize> 自選聊天、新聞或直播內容；之後想玩，就喺同一度揀遊戲，再按「約一局」。')
        elif action=='help':
            target=await support_destination(i)
            content=(words(member,'找不到合適遊戲，或需要協助／建議：','搵唔到啱玩嘅遊戲，或者需要協助／建議：')+target.mention if target else words(member,'目前未能確認你可使用的求助入口。可先選擇遊戲或返回，沒有開放任何新權限。','暫時未能確認你用到嘅求助入口。可以先揀遊戲或者返回，冇開放任何新權限。'))
        else:
            content=words(member,'🎮 到 <id:customize> 選擇遊戲，再按「約一局」。找不到合適遊戲可按「求助／建議」，也可以先觀望。','🎮 去 <id:customize> 揀遊戲，再按「約一局」。搵唔到啱玩嘅可以按「求助／建議」，或者先觀望。')
        await source.resolve(i)
        kwargs=dict(content=content,embed=None,view=NextSteps(source,member,return_to),allowed_mentions=discord.AllowedMentions.none())
    except SourceUnavailable:
        kwargs=dict(content=text(i.user,'denied'),embed=None,view=None,allowed_mentions=discord.AllowedMentions.none())
    if replace:await i.edit_original_response(**kwargs)
    else:await i.followup.send(**kwargs,ephemeral=True)


class NextSteps(SafeView):
    def __init__(self,source,member=None,return_to=None):
        super().__init__(timeout=180)
        self.source,self.return_to=source,return_to
        for action,key in [('games','choose_game'),('help','help'),('observe','observe')]:
            b=discord.ui.Button(label=text(member,key),row=0)
            async def choose(i,action=action):
                if not await self.interaction_check(i):return
                await show_route(i,action,source=self.source,return_to=self.return_to,replace=True)
            b.callback=choose;self.add_item(b)
        b=discord.ui.Button(label=text(member,'back'),row=1);b.callback=self.back;self.add_item(b)

    async def interaction_check(self,i):
        if i.user.id==self.source.owner:return True
        await i.response.send_message(text(i.user,'owner'),ephemeral=True);return False

    async def back(self,i):
        if not await self.interaction_check(i):return
        if not i.response.is_done():await i.response.defer(ephemeral=True)
        try:await self.source.resolve(i)
        except SourceUnavailable:
            await i.edit_original_response(content=text(i.user,'denied'),embed=None,view=None);return
        if self.return_to:await self.return_to(i);return
        menu=i.client.get_cog('Menu')
        if menu:await menu.open_main_menu(i)
        else:await show_next_steps(i,reason='unavailable',replace=True)
