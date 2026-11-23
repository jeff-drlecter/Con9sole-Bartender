"""Existing, permission-checked next steps, shared with 03; never assigns roles."""
import discord
import config
from features.language_preferences import language
from features.notification_words import text
from core.private_source import Source, SourceUnavailable, fresh_access
from core.ui import SafeView


def words(member, neutral, hk):
    return hk if language(member)=='hk' else neutral


def help_channel_id(member):
    if any(role.id == config.VERIFIED_ROLE_ID for role in member.roles):
        return config.SUPPORT_CHANNEL_ID
    return config.WELCOME_CHANNEL_ID


async def support_destination(interaction, source_member):
    guild = interaction.guild
    if guild is None or interaction.guild_id != config.GUILD_ID or guild.id != config.GUILD_ID:
        return None
    channel_id = help_channel_id(source_member)
    try:
        member, channel = await fresh_access(guild, interaction.user.id, channel_id)
    except (SourceUnavailable, discord.HTTPException, OSError):
        return None
    if (not isinstance(channel, (discord.TextChannel, discord.ForumChannel))
            or channel.id != channel_id or help_channel_id(member) != channel_id
            or channel.guild.id != config.GUILD_ID
            or channel.nsfw or getattr(member, 'pending', False)):
        return None
    permissions = channel.permissions_for(member)
    if permissions.view_channel and permissions.read_message_history and permissions.send_messages:
        return channel
    return None


async def playtest_destination(interaction, source_member):
    guild = interaction.guild
    if (guild is None or guild.id != config.GUILD_ID or interaction.guild_id != config.GUILD_ID
            or not any(getattr(role, 'id', None) == config.PLAYTEST_ROLE_ID for role in source_member.roles)):
        return None
    try:
        member, forum = await fresh_access(guild, interaction.user.id, config.PLAYTEST_FORUM_ID)
    except (SourceUnavailable, discord.HTTPException, OSError):
        return None
    # fresh_access checks current View Channel and Read Message History. Recheck the
    # opt-in on that same member snapshot before exposing the native age-gated link.
    if (isinstance(forum, discord.ForumChannel) and forum.id == config.PLAYTEST_FORUM_ID
            and forum.is_nsfw() and not member.pending and member.get_role(config.PLAYTEST_ROLE_ID)):
        return forum
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
        member, _, _ = await source.resolve(i)
        view = NextSteps(source, member, return_to)
        if action == 'observe':
            content = words(member,
                '可以先看看。到 <id:customize> 自選聊天、新聞或直播內容；日後也可在這裡選擇遊戲，再到主選單找隊友。',
                '可以先睇吓。去 <id:customize> 自選聊天、新聞或直播內容；之後想玩就喺同一度揀遊戲，再去主選單搵隊友。')
        elif action == 'help':
            # Resolve the source first. Do not await another lookup between the
            # destination authorization and sending its private link.
            target = await support_destination(i, member)
            if target:
                content = words(member,
                    f'請到 {target.mention} 留言給 Helper，說明你遇到的問題。',
                    f'請去 {target.mention} 留言畀 Helper，講低你遇到咩問題。')
            else:
                content = words(member,
                    '目前無法確認你能在求助頻道留言。請先完成入群步驟。若已完成，可在你能發言的頻道詢問 Helper。選擇遊戲請到 <id:customize>。',
                    '暫時確認唔到你能否喺求助頻道留言。請先完成入群步驟。如果已經完成，可以喺你講到嘢嘅頻道問 Helper。揀遊戲請去 <id:customize>。')
        else:
            content = words(member,
                '🎮 到 <id:customize> 選擇遊戲，再到主選單找隊友。找不到想玩的遊戲，可按「找 Helper」或「先觀望」。',
                '🎮 去 <id:customize> 揀遊戲，再去主選單搵隊友。搵唔到啱玩嘅遊戲，可以按「搵 Helper」或者「先觀望」。')
            if action == 'games':
                forum = await playtest_destination(i, member)
                if forum is not None:
                    view.add_item(discord.ui.Button(label='遊戲開發與試玩（18+）', emoji='🧪',
                                                    url=forum.jump_url, row=1))
        kwargs=dict(content=content,embed=None,view=view,allowed_mentions=discord.AllowedMentions.none())
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
