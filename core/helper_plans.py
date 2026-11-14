"""Read-only SquadPlans adapter; shared counts and freshly authorized private details."""
import time
import discord
import config
from features.language_preferences import language
from features.squad_plans import deadline

WAITING = {'open', 'due', 'gathering'}
ACTIVE = WAITING | {'live'}
NONE = discord.AllowedMentions.none()


def copy(member, neutral, hk):
    return hk if language(member) == 'hk' else neutral


def public_source(channel, *, voice=False):
    """Only universally readable sources; any role/member denial fails closed.

    A role-gated game area is NOT public merely because the Bot can read it.
    Do not infer authorization from channel/category names or cached members.
    """
    if not channel or isinstance(channel, discord.Thread):
        return False
    try:
        needed = ('view_channel', 'connect') if voice else ('view_channel', 'read_message_history')
        perms = channel.permissions_for(channel.guild.default_role)
        return (all(getattr(perms, key, False) for key in needed)
                and not any(getattr(ow, key, None) is False
                            for ow in channel.overwrites.values() for key in needed))
    except (AttributeError, TypeError):
        return False


def provider(cog):
    bot = getattr(cog, 'bot', None)
    get_cog = getattr(bot, 'get_cog', None)
    plans = get_cog('SquadPlans') if get_cog else None
    # No raw-record fallback when Part 2 has not been deployed.
    return plans if callable(getattr(plans, 'member_status', None)) else None


def relevant(plan, guild_id, now):
    return (plan.get('guild') == guild_id and plan.get('message')
            and plan.get('status') in ACTIVE
            and (plan['status'] == 'live' or now <= deadline(plan)))


def unfilled(summary):
    capacity = summary['capacity']
    return capacity is not None and summary['party'] + summary['registered'] < capacity


async def shared_counts(cog):
    plans = provider(cog)
    if not plans:
        return None
    from features.squad_plans import public_status  # Part 2's roster-free schema
    guild = cog.channel.guild
    waiting = recruiting = 0
    sources = {}
    for plan in plans.book.all():
        if not relevant(plan, guild.id, time.time()):
            continue
        cid = plan['channel']
        if cid not in sources:
            try:
                sources[cid] = await guild.fetch_channel(cid)
            except discord.HTTPException:
                sources[cid] = None
        source = sources[cid]
        if (not isinstance(source, discord.TextChannel) or source.guild.id != guild.id
                or not public_source(source)):
            continue
        current = plans.book.get(plan['id'])
        if current != plan:  # a move/edit/cancellation during the fetch needs a new scan
            continue
        summary = public_status(current)
        waiting += summary['status'] in WAITING
        recruiting += unfilled(summary)
    return waiting, recruiting


async def fresh_access(cog, interaction):
    """Recheck Dashboard access as well as source access on every private action."""
    if (not cog.enabled or cog.channel is None or interaction.guild_id != config.GUILD_ID
            or interaction.guild is None or interaction.channel_id != cog.channel.id):
        return None
    try:
        member = await interaction.guild.fetch_member(interaction.user.id)
        channel = await interaction.guild.fetch_channel(cog.channel.id)
    except discord.HTTPException:
        return None
    p = channel.permissions_for(member)
    roles = {*config.HELPER_ROLE_IDS, cog.tester_id}
    if (channel.guild.id == config.GUILD_ID and p.view_channel and p.read_message_history
            and (member.guild_permissions.administrator or any(r.id in roles for r in member.roles))):
        return member
    return None


async def authorized_status(plans, guild, user_id, key):
    before = plans.book.get(key)
    if not before or not relevant(before, guild.id, time.time()):
        return None
    summary = await plans.member_status(guild, user_id, key)
    current = plans.book.get(key)
    if (summary is None or current != before or summary.get('id') != key
            or not summary.get('permissions', {}).get('read')
            or not relevant(current, guild.id, time.time())):
        return None
    return summary, f'https://discord.com/channels/{guild.id}/{current["channel"]}/{current["message"]}'


def clean(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value).replace('\n', ' ')[:100]))


def detail(summary, member=None):
    state = {'open':'預約中', 'due':'待開局', 'gathering':'集合中', 'live':'進行中'}[summary['status']]
    total = summary['party'] + summary['registered']
    capacity = summary['capacity']
    missing = '未設定目標人數' if capacity is None else f'尚欠 {max(0, capacity-total)} 人'
    note = copy(member, '不代表已到場。', '唔代表已到場。')
    return (f'**{clean(summary["game"])}** · {state}\n{clean(summary["mode"])}\n'
            f'<t:{int(summary["start"])}:f> · {missing}\n'
            f'發起時已有 {summary["party"]} 人／已確認報名 {summary["registered"]} 人；{note}')


class HelperPlansView(discord.ui.View):
    def __init__(self, cog, owner, rows, member):
        super().__init__(timeout=180)
        self.cog, self.owner = cog, owner
        if rows:
            select = discord.ui.Select(placeholder=copy(member, '選擇可查看的約局', '揀可查看嘅約局'),
                options=[discord.SelectOption(label=clean(s['game'])[:80], value=s['id']) for s, _ in rows])
            async def choose(i):
                await show_plans(cog, i, key=select.values[0], edit=True)
            select.callback = choose
            self.add_item(select)
        button = discord.ui.Button(label='刷新', style=discord.ButtonStyle.primary)
        async def refresh(i):
            await show_plans(cog, i, edit=True)
        button.callback = refresh
        self.add_item(button)

    async def interaction_check(self, i):
        if i.user.id == self.owner:
            return True  # show_plans performs fresh Dashboard and source checks
        await i.response.send_message(copy(i.user, '請開啟自己的約局概覽。', '請開自己嘅約局概覽。'), ephemeral=True)
        return False


async def show_plans(cog, i, *, key=None, edit=False):
    await i.response.defer(ephemeral=True)
    member = await fresh_access(cog, i)
    view, embed = None, None
    if member is None:
        content = copy(i.user, '目前無法查看，請重新開啟 Helper Dashboard。', '而家無法查看，請重新開 Helper Dashboard。')
    elif not (plans := provider(cog)):
        content = copy(member, '約局概覽暫未就緒，請稍後再試。', '約局概覽未準備好，請稍後再試。')
    else:
        rows = []
        if key:
            row = await authorized_status(plans, i.guild, member.id, key)
            if row:
                rows.append(row)
        else:
            candidates = sorted((p for p in plans.book.all() if relevant(p, i.guild.id, time.time())), key=lambda p:p['start'])
            for plan in candidates[:50]:
                row = await authorized_status(plans, i.guild, member.id, plan['id'])
                if row and (row[0]['status'] in WAITING or unfilled(row[0])):
                    rows.append(row)
                if len(rows) >= 10:
                    break
        view = HelperPlansView(cog, member.id, rows, member)
        content = copy(member, '只顯示你可查看的約局；操作請回原卡。最多顯示 10 局，未列出不代表沒有。',
            '只顯示你睇得到嘅約局；操作請返原卡。最多顯示 10 局，未列出唔代表冇。')
        if not rows:
            content += '\n' + copy(member, '暫無可顯示的約局。未選擇遊戲時，可到 <id:customize> 選擇遊戲，再按刷新。',
                '暫時冇可顯示嘅約局。未揀遊戲可以去 <id:customize> 揀返，再按刷新。')
        else:
            embed = discord.Embed(title='待開局／招募未滿')
            for summary, url in rows:
                text = detail(summary, member) + f'\n[查看原卡]({url})'
                if len(embed) + len(text) > 5500:
                    break
                embed.add_field(name='約局', value=text[:1024], inline=False)
    # Refresh and selection replace the same PRIVATE reply; never write to the board.
    kwargs = dict(content=content, embed=embed, view=view, allowed_mentions=NONE)
    if edit:
        await i.edit_original_response(**kwargs)
    else:
        await i.followup.send(**kwargs, ephemeral=True)
