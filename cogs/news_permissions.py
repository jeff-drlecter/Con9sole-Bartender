"""Private administrator panel; no scheduled enforcement or announcements."""
import asyncio
import io
import json

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.news_channel_ui import settings
from features import anti_scam_fix as journal, news_permissions as policy
from features.language_preferences import language


def wording(member, neutral, hk):
    return hk if language(member) == 'hk' else neutral


class NewsPermissionPanel(discord.ui.View):
    def __init__(self, cog, actor, plan):
        super().__init__(timeout=600)
        self.cog, self.actor, self.plan = cog, actor, plan
        for mode, label, style in (
            ('preview', '重新檢查', discord.ButtonStyle.secondary),
            ('apply', '套用以上差異', discord.ButtonStyle.primary),
            ('restore', '復原此計劃', discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, style=style)
            button.disabled = mode == 'apply' and (not plan['ops'] or bool(plan['blockers']) or
                any(o['state'] != 'prepared' for o in plan['ops']))
            async def callback(inter, selected=mode):
                await cog.run(inter, selected, plan['id'])
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, inter):
        if inter.user.id == self.actor and inter.guild_id == config.GUILD_ID:
            return True
        await inter.response.send_message('請開啟自己的 /news_permissions。', ephemeral=True)
        return False


class NewsPermissions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def run(self, inter, action='preview', plan_id=''):
        await inter.response.defer(ephemeral=True, thinking=True)
        audit = self.bot.get_cog('PermissionAudit')
        if audit is None or not await audit.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。', ephemeral=True)
            return
        if audit.lock.locked():
            await inter.followup.send('另一項權限操作進行中，請稍後再試。', ephemeral=True)
            return
        async with audit.lock:
            try:
                if action == 'preview':
                    plan = policy.build(await inter.guild.fetch_roles(), await inter.guild.fetch_channels(),
                                        inter.guild_id, inter.user.id, settings())
                    await asyncio.to_thread(journal.save, plan)
                else:
                    plan = await asyncio.to_thread(journal.load, plan_id, inter.guild_id, inter.user.id)
                    if plan.get('scope') != policy.SCOPE:
                        raise ValueError('計劃不屬於新聞權限。')
                    if action not in ('apply', 'restore'):
                        raise ValueError('未知操作。')
                    await policy.execute(inter.guild, plan, lambda: audit.authorized(inter),
                                         restore=action == 'restore')
                if not await audit.authorized(inter):
                    return
                member = await inter.guild.fetch_member(inter.user.id)
                if action == 'preview':
                    heading = wording(member, '新聞權限檢查｜未修改設定', '新聞權限檢查｜未改設定')
                    detail = '\n'.join(o['name'] for o in plan['ops']) or wording(
                        member, '三個新聞頻道已符合設定，無需修改。', '三個新聞頻道已符合設定，唔使改。')
                    if plan['blockers'] and not plan['ops']:
                        detail = '有額外存取設定需要核對，暫不套用。'
                else:
                    heading = wording(member, '新聞權限操作結果', '新聞權限操作結果')
                    detail = journal.summary(plan)
                blockers = '\n'.join(plan['blockers'])
                text = f'**{heading}**\n{detail}\n{blockers}\n計劃：`{plan["id"]}`\n'
                text += wording(member,
                    'Helpers 依新聞選擇查看；Mod／Bot 原有管理存取保留。官方資訊及身份組成員不變。\n此檢查不代表普通成員／手機實測。',
                    'Helpers 跟新聞選擇先睇到；Mod／Bot 原有管理存取保留。官方資訊同身份組成員不變。\n呢個檢查唔代表普通成員／手機實測。')
                attachment = {}
                if len(text) > 1950:
                    attachment['file'] = discord.File(io.BytesIO(json.dumps(plan, ensure_ascii=False,
                        indent=2).encode()), filename='news-permission-plan.json')
                    text = f'**{heading}**\n共 {len(plan["ops"])} 項差異、{len(plan["blockers"])} 項待核對。\n完整清單見附件。計劃：`{plan["id"]}`'
                await inter.followup.send(text, view=NewsPermissionPanel(self, inter.user.id, plan),
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **attachment)
            except (ValueError, OSError, discord.HTTPException) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else '操作未能確認，請先核對結果。'
                await inter.followup.send(detail + '\n如已開始套用，可用原計劃復原；不要重複套用。',
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='news_permissions', description='管理員：檢查及套用三個新聞頻道的查看權限')
    @app_commands.choices(action=[
        app_commands.Choice(name='檢查', value='preview'),
        app_commands.Choice(name='套用指定計劃', value='apply'),
        app_commands.Choice(name='復原指定計劃', value='restore')])
    async def news_permissions(self, inter: discord.Interaction, action: str = 'preview', plan_id: str = ''):
        await self.run(inter, action, plan_id)


async def setup(bot):
    await bot.add_cog(NewsPermissions(bot))
