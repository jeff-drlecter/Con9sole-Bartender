"""Admin-private outcomes; the sampler never sends messages or awards XP."""
import asyncio
import logging
import time
import os
import uuid
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from core.permissions import is_server_admin
from core.storage_paths import DATA_DIR
from features.community_outcomes import Outcomes, display, window, test_channel
from features.language_preferences import language
from features.squad_outcome_state import session_origin
from features.wording import text as wording_text

log = logging.getLogger(__name__)


class CommunityOutcomes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Outcomes(DATA_DIR / 'community_outcomes.sqlite3')
        # Explicit known test IDs allow historical exclusion after rename/deletion.
        self.excluded = {int(v) for v in os.getenv('OUTCOMES_TEST_CHANNEL_IDS', '').split(',') if v.strip()}
        self.run_id = uuid.uuid4().hex
        self.sample.start()

    def cog_unload(self):
        self.sample.cancel()

    async def observe(self):
        if not self.bot.is_ready():
            return
        cards, plans = self.bot.get_cog('SquadCards'), self.bot.get_cog('SquadPlans')
        guild = self.bot.get_guild(config.GUILD_ID)
        if not cards or not plans or not guild:
            return
        for key, session in list(cards.state['sessions'].items()):
            channel = guild.get_channel(int(key))
            p = plans.book.get(session.get('plan_id'))
            origin = session_origin(session, p, guild.id)
            if not channel or channel == guild.afk_channel or origin not in ('linked', 'natural'):
                continue
            await asyncio.to_thread(self.store.observe, guild.id, session['id'], p['id'] if p else None,
                list(channel.members), test=bool(test_channel(channel) or channel.id in self.excluded
                    or (p and (p.get('analytics_test') or p.get('test') or p.get('is_test')
                               or test_channel(guild.get_channel(p['channel'])) or p['channel'] in self.excluded))))
        if getattr(self, 'run_id', None):
            await asyncio.to_thread(self.store.heartbeat, self.run_id, success=True)

    @tasks.loop(seconds=5)
    async def sample(self):
        try:
            await self.observe()
        except Exception:
            try:
                await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False)
            except Exception:
                pass  # A failed store cannot record its own outage; keep retrying.
            log.exception('Outcome observation unavailable; no attendance inferred')

    @sample.before_loop
    async def before_sample(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id == config.GUILD_ID and before.channel != after.channel:
            try:
                await self.observe()
            except Exception:
                log.exception('Outcome voice observation unavailable')

    async def menu_entry(self, inter):
        await type(self).report.callback(self, inter, 'week')

    async def authorized(self, inter):
        if inter.guild_id != config.GUILD_ID or inter.guild is None:
            return False
        try:
            member = await inter.guild.fetch_member(inter.user.id)
        except discord.HTTPException:
            return False
        return not member.bot and is_server_admin(member)

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(period=[app_commands.Choice(name='香港今天', value='day'),
                                 app_commands.Choice(name='香港本週（星期一開始）', value='week'),
                                 app_commands.Choice(name='香港上週', value='previous_week')])
    @app_commands.command(name='community_outcomes', description='私人查看約局成效與資料缺漏（管理員）')
    async def report(self, inter: discord.Interaction, period: str = 'week'):
        await inter.response.defer(ephemeral=True, thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send(wording_text(inter.user, '只限本伺服器管理員。'), ephemeral=True)
            return
        plans = self.bot.get_cog('SquadPlans')
        if not plans:
            await inter.followup.send(wording_text(inter.user, '約局資料未就緒，無法提供統計。'), ephemeral=True)
            return
        now = time.time()
        start, end = window(period, now)
        snapshot = plans.book.all()
        # Also exclude identifiable historical test destinations without rewriting them.
        excluded = self.excluded | {p['channel'] for p in snapshot
            if test_channel(inter.guild.get_channel(p['channel']))}
        try:
            result = await asyncio.to_thread(self.store.report, inter.guild_id, snapshot, start, end,
                                             excluded_channels=excluded, as_of=now)
        except Exception:
            log.exception('Outcome report unavailable; missing data must not become zero')
            await inter.followup.send(wording_text(inter.user, '統計資料暫時無法讀取，請稍後再試；未將缺漏當作零。'), ephemeral=True)
            return
        if not await self.authorized(inter):
            await inter.followup.send(wording_text(inter.user, '權限已改變，統計未送出。'), ephemeral=True)
            return
        await inter.followup.send(wording_text(inter.user, display(result, language(inter.user))), ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(CommunityOutcomes(bot))
