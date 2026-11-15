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
from features.co_participation import CoParticipation
from features.language_preferences import language
from features.squad_outcome_state import session_origin
from features.wording import text as wording_text

def source_contract(plan):
    try:
        from features.plan_services import contract
    except ImportError:
        return dict(guild=plan['guild'],plan=plan['id'],session=plan.get('session'),
                    source=dict(channel=plan['channel'],message=plan.get('message')),
                    origin=plan.get('origin','legacy'),created_at=plan.get('created_at'),test=plan.get('analytics_test'))
    return contract(plan)


log = logging.getLogger(__name__)


class CommunityOutcomes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Outcomes(DATA_DIR / 'community_outcomes.sqlite3')
        # Explicit known test IDs allow historical exclusion after rename/deletion.
        self.excluded = {int(v) for v in os.getenv('OUTCOMES_TEST_CHANNEL_IDS', '').split(',') if v.strip()}
        self.run_id = uuid.uuid4().hex
        self.observation_lock = asyncio.Lock()
        self.coplay = CoParticipation()
        self.last_success = None
        self.last_error = None
        self.sample.start()

    def cog_unload(self):
        self.sample.cancel()

    async def observe(self):
        if not hasattr(self, 'observation_lock'):
            self.observation_lock = asyncio.Lock()
            self.coplay = CoParticipation()
        async with self.observation_lock:
            try:
                await self._observe()
            except Exception:
                self.coplay.reset()
                self.run_id = uuid.uuid4().hex  # Never bridge an unrecordable DB failure.
                raise

    async def _observe(self):
        if not self.bot.is_ready():
            self.coplay.reset()
            if getattr(self, 'run_id', None):
                await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False, guild=config.GUILD_ID)
            return
        cards, plans = self.bot.get_cog('SquadCards'), self.bot.get_cog('SquadPlans')
        guild = self.bot.get_guild(config.GUILD_ID)
        if not cards or not plans or not guild:
            self.last_error = 'sources_unavailable'
            self.coplay.reset()
            if getattr(self, 'run_id', None):
                await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False, guild=config.GUILD_ID)
            return
        samples = {}
        now = time.time()
        locations = {m.id: c.id for c in getattr(guild, "voice_channels", []) for m in c.members if not m.bot}
        for key, session in list(cards.state['sessions'].items()):
            channel = guild.get_channel(int(key))
            p = plans.book.get(session.get('plan_id'))
            origin = session_origin(session, p, guild.id)
            if not channel or channel == guild.afk_channel or origin not in ('linked', 'natural'):
                continue
            contract = source_contract(p) if p else None
            samples[(guild.id, session['id'], channel.id)] = {m.id for m in channel.members if not m.bot}
            await asyncio.to_thread(self.store.observe, guild.id, session['id'], p['id'] if p else None,
                list(channel.members), test=bool(test_channel(channel) or channel.id in self.excluded
                    or (p and (p.get('analytics_test') or p.get('test') or p.get('is_test')
                               or test_channel(guild.get_channel(p['channel'])) or p['channel'] in self.excluded))),
                source=dict(channel=contract['source']['channel'] if contract else channel.id, voice=channel.id, origin=origin,
                            plan_origin=contract['origin'] if contract else None))
        for (gid, sid, voice), qualified in self.coplay.sample(samples, locations, now):
            await asyncio.to_thread(self.store.mark_coplay, gid, sid, voice, qualified)
        if getattr(self, 'run_id', None):
            await asyncio.to_thread(self.store.heartbeat, self.run_id, success=True, guild=guild.id)
            self.last_success = now
            self.last_error = None

    @tasks.loop(seconds=5)
    async def sample(self):
        try:
            await self.observe()
        except Exception:
            try:
                await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False, guild=config.GUILD_ID)
            except Exception:
                pass  # A failed store cannot record its own outage; keep retrying.
            self.last_error = 'observation_failed'
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
                self.last_error = 'observation_failed'
                if getattr(self, 'run_id', None):
                    await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False, guild=config.GUILD_ID)
                log.exception('Outcome voice observation unavailable')

    @commands.Cog.listener()
    async def on_disconnect(self):
        # A quick reconnect still invalidates unobserved partial intervals.
        async with self.observation_lock:
            self.coplay.reset()
            self.last_error = 'gateway_disconnected'
            self.run_id = uuid.uuid4().hex
            await asyncio.to_thread(self.store.heartbeat, self.run_id, success=False, guild=config.GUILD_ID)

    def health_status(self):
        return dict(available=self.bot.is_ready() and self.sample.is_running() and self.last_error is None
                    and self.last_success is not None and 0 <= time.time()-self.last_success <= 10,
                    heartbeat=self.last_success, error=self.last_error)

    async def menu_entry(self, inter):
        if not await self.authorized(inter):
            await inter.response.send_message(wording_text(inter.user,'只限本伺服器管理員。'),ephemeral=True)
            return
        view=discord.ui.View(timeout=180)
        for label, method in [('約局成效','report'),('首次觀察／再次到場','returns_report')]:
            button=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary)
            async def choose(i, method=method):
                if i.user.id!=inter.user.id or i.guild_id!=inter.guild_id:
                    await i.response.send_message('請開啟自己的管理選單。',ephemeral=True)
                    return
                await getattr(type(self),method).callback(self,i)
            button.callback=choose
            view.add_item(button)
        await inter.response.send_message('選擇私人統計範圍。',view=view,ephemeral=True)

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
        excluded = self.excluded  # Stored event source, never today's name as historical evidence.
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

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(origin=[app_commands.Choice(name='全部已知來源',value='all'),
                                 app_commands.Choice(name='連接約局',value='linked'),
                                 app_commands.Choice(name='自然語音',value='natural')])
    @app_commands.command(name='observed_returns',description='私人查看首次觀察及 7／28 日再次到場（管理員）')
    async def returns_report(self, inter: discord.Interaction, days: app_commands.Range[int,1,90] = 60, origin: str = 'all'):
        from features.observed_returns import returns, render
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send(wording_text(inter.user,'只限本伺服器管理員。'),ephemeral=True)
            return
        now=time.time()
        from datetime import datetime, timedelta
        from features.observed_returns import HK
        start=(datetime.fromtimestamp(now,HK).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=days-1)).timestamp()
        try:
            result=await asyncio.to_thread(returns,self.store.path,inter.guild_id,start,now,now,
                excluded_channels=self.excluded, origins=('linked','natural') if origin=='all' else (origin,))
        except Exception:
            log.exception('Return report unavailable')
            await inter.followup.send('統計資料暫時無法讀取；缺漏未當作零。',ephemeral=True)
            return
        if not await self.authorized(inter):
            await inter.followup.send(wording_text(inter.user,'權限已改變，統計未送出。'),ephemeral=True)
            return
        await inter.followup.send(render(result,language(inter.user)),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(CommunityOutcomes(bot))
