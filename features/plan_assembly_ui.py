"""Controls shared by the original reservation and its scheduled assembly reminder."""
from types import SimpleNamespace

import discord

from core.ui import SafeView
from features.plan_services import AccessError, source
from features.squad_plans import ACTIVE, confirmed, deadline


def voice_link(plan, *, row):
    return discord.ui.Button(label='🎧 加入語音', style=discord.ButtonStyle.link, row=row,
                             url=f"https://discord.com/channels/{plan['guild']}/{plan['voice']}")


async def authorize_assembly(cog, interaction, key, generation, surface):
    """Bind the interaction to this occurrence, source and bot-owned public message."""
    from cogs.squad_plans import allowed

    plan = cog.book.get(key)
    if (not plan or not interaction.guild or interaction.guild_id != plan['guild']
            or interaction.channel_id != plan['channel']):
        raise ValueError('請重新開啟原約局卡。')
    member, channel = await source(cog, interaction.guild, interaction.user.id, plan)
    plan = cog.book.get(key)
    assembly = plan.get('assembly') or {}
    if (assembly.get('generation') != generation or plan['status'] not in ACTIVE
            or cog.book.clock() > deadline(plan)
            or getattr(channel, 'category_id', None) != getattr(interaction.channel, 'category_id', None)
            or not allowed(SimpleNamespace(user=member, channel=channel, guild_id=plan['guild']))):
        raise ValueError('時間、狀態或權限已變更，請重新開啟原卡。')
    if surface != 'private':
        expected = plan['message'] if surface == 'card' else assembly['due'].get('message')
        message = interaction.message
        if not message or message.id != expected or message.author.id != cog.bot.user.id:
            raise ValueError('請從目前的約局卡或集合提醒操作。')
    return plan


def add_preference_button(view, cog, plan, member):
    assembly = plan.get('assembly')
    if not assembly or plan['status'] not in ACTIVE:
        return
    host = member.id == plan['owner']
    if not host and (member.id not in confirmed(plan) or cog.book.clock() >= plan['start']):
        return
    enabled = assembly['host'] if host else member.id in assembly['members']
    purpose = '到時及催開局時 @ 我' if host else '到時在原頻道 @ 我'
    action = ('host_' if host else 'due_') + ('off' if enabled else 'on')
    button = discord.ui.Button(label=('關閉：' if enabled else '開啟：') + purpose, row=1)

    async def change(interaction):
        if interaction.user.id != member.id:
            await interaction.response.send_message('請從原卡開啟自己的設定。', ephemeral=True)
            return
        await interaction.response.defer()
        async with cog.lock:
            try:
                await authorize_assembly(cog, interaction, plan['id'], assembly['generation'], 'private')
                updated = cog.book.assembly_action(plan['id'], member.id, action, assembly['generation'])
                if host:
                    await cog.refresh(updated)
            except (AccessError, ValueError):
                await interaction.followup.send('設定未更新，請從原卡重新開啟。', ephemeral=True)
                return
        from cogs.squad_plans import ReminderView
        await interaction.edit_original_response(content='已更新集合提醒設定。',
            view=ReminderView(cog, plan['id'], interaction.user))

    button.callback = change
    view.add_item(button)


def add_assembly_buttons(view, cog, plan, *, surface):
    from features.plan_assembly_state import unopened

    now = cog.book.clock()
    if (plan['status'] not in ACTIVE or now < plan['start'] or now > deadline(plan)
            or not unopened(plan)):
        return
    assembly = plan['assembly']
    row = 2 if surface == 'card' else 0
    for action, label in [('start', '🎙️ 確認開局'), ('wait', '🙋 我到咗'), ('nudge', '🔔 提醒發起人開局')]:
        if action == 'nudge':
            if not assembly['host']:
                continue
            if assembly['nudge']:
                label = '已處理催開'
        button = discord.ui.Button(label=label, row=row,
            style=discord.ButtonStyle.primary if action == 'start' else discord.ButtonStyle.secondary,
            disabled=action == 'nudge' and bool(assembly['nudge']),
            custom_id=f"assembly:{plan['id']}:{assembly['generation']}:{surface}:{action}")

        async def callback(interaction, action=action):
            await assembly_click(cog, interaction, plan['id'], assembly['generation'], surface, action)

        button.callback = callback
        view.add_item(button)


async def assembly_click(cog, interaction, key, generation, surface, action):
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with cog.lock:
        try:
            p = await authorize_assembly(cog, interaction, key, generation, surface)
            if action == 'start':
                if p['owner'] != interaction.user.id or cog.book.clock() < p['start']:
                    raise ValueError('預約時間到後，只有發起人可以確認開局。')
                from cogs.squad_plans import prepare_plan_voice
                content = await prepare_plan_voice(cog, interaction, p)
            else:
                p = cog.book.assembly_action(key, interaction.user.id, action, generation)
                await cog.refresh(p)
                content = ('已登記等候。語音開放後可從這裡加入。' if action == 'wait'
                           else '已登記提醒發起人的要求。每局只會催一次。')
        except AccessError:
            content = '目前無法核對原卡或你的權限。'
        except ValueError as exc:
            content = str(exc)
    await interaction.followup.send(content, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class AssemblyView(SafeView):
    def __init__(self, cog, plan):
        super().__init__(timeout=None)
        if plan['status'] in {'gathering', 'live'} and plan.get('voice'):
            self.add_item(voice_link(plan, row=0))
        else:
            add_assembly_buttons(self, cog, plan, surface='notice')
