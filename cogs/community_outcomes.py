"""Admin-private outcomes; the sampler never sends messages or awards XP."""
import asyncio
import logging
import time
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from core.permissions import is_server_admin
from core.storage_paths import DATA_DIR
from features.community_outcomes import Outcomes, display, window, test_channel
from features.wording import text as wording_text

log = logging.getLogger(__name__)


class CommunityOutcomes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Outcomes(DATA_DIR / 'community_outcomes.sqlite3')
        # Explicit known test IDs allow historical exclusion after rename/deletion.
        self.excluded = {int(v) for v in os.getenv('OUTCOMES_TEST_CHANNEL_IDS', '').split(',') if v.strip()}
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
            if (not channel or channel == guild.afk_channel or session.get('ended') is not None
                    or not p or p['guild'] != guild.id or p['status'] != 'live' or p.get('session') != session['id']):
                continue
            await asyncio.to_thread(self.store.observe, guild.id, session['id'], p['id'],
                list(channel.members), test=bool(p.get('analytics_test') or test_channel(channel)
                    or test_channel(guild.get_channel(p['channel'])) or p['channel'] in self.excluded
                    or channel.id in self.excluded))

    @tasks.loop(seconds=5)
    async def sample(self):
        try:
            await self.observe()
        except Exception:
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
            await inter.followup.send('約局資料未就緒，無法提供統計。', ephemeral=True)
            return
        now = time.time()
        start, end = window(period, now)
        snapshot = plans.book.all()
        # Also exclude identifiable historical test destinations without rewriting them.
        excluded = self.excluded | {p['channel'] for p in snapshot
            if test_channel(inter.guild.get_channel(p['channel']))}
        result = await asyncio.to_thread(self.store.report, inter.guild_id, snapshot, start, end,
                                         excluded_channels=excluded, as_of=now)
        if not await self.authorized(inter):
            await inter.followup.send('權限已改變，統計未送出。', ephemeral=True)
            return
        await inter.followup.send(wording_text(inter.user, display(result)), ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(CommunityOutcomes(bot))
