"""Voice recruitment cards. Configure with /squad_setup; first-arrival user ping only."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.json_storage import atomic_write_json, load_json_object
from core.permissions import is_admin_or_helper
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)
TARGET = discord.Object(id=config.GUILD_ID)


def humans(channel):
    return [m for m in channel.members if not m.bot]


# Shared labels are kept separate from version-specific options.
GAME_LABELS = {"fc": "EA SPORTS FC", "2k": "NBA 2K", "2k27": "NBA 2K27"}
MODE_PRESETS = {
    "fc": ("Clubs 球會", "Clubs Rush", "UT Rush", "合作賽季", "友誼賽"),
    "2k": ("REC", "Park", "The Theatre", "MyTEAM 合作"),
    "2k27": ("REC", "Park", "The Theatre", "Crew HQ", "MyTEAM 合作", "Street Kings 打電腦"),
}


def game_profile(channel, session):
    if session.get("profile") == "other":
        return ""
    if session.get("profile") in GAME_LABELS:
        return session["profile"]
    name = str(getattr(getattr(channel, "category", None), "name", "")).casefold()
    if "2k" in name:
        return "2k"
    if "fc" in name:
        return "fc"
    return ""


class ModePicker(discord.ui.Select):
    def __init__(self, cog, key, session, profile):
        self.cog, self.key, self.session, self.profile = cog, key, session, profile
        options = [discord.SelectOption(label="未定／唔填", value="__none__")]
        options += [discord.SelectOption(label=mode, value=mode,
                                        default=mode == session.get("mode"))
                    for mode in MODE_PRESETS.get(profile, ())]
        options.append(discord.SelectOption(label="自訂模式", value="__custom__"))
        super().__init__(placeholder="玩咩模式？（選填）", options=options, row=1)

    async def callback(self, interaction):
        async with self.cog.lock:
            session = self.cog.state["sessions"].get(self.key)
            channel = self.cog.bot.get_channel(int(self.key))
            if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
                await interaction.response.send_message("呢場已結束，或者你冇修改權限。", ephemeral=True)
                return
            value = self.values[0]
            if value == "__custom__":
                await interaction.response.send_modal(Details(self.cog, self.key, session))
                return
            if self.profile != game_profile(channel, session):
                await interaction.response.send_message("遊戲設定已改，請重新開啟招募設定。", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            session["mode"] = "" if value == "__none__" else value
            if self.profile:
                session["profile"] = self.profile
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.followup.send("已更新遊戲模式。", ephemeral=True)


class GamePicker(discord.ui.Select):
    def __init__(self, cog, key, session, profile):
        self.cog, self.key, self.session = cog, key, session
        options = [discord.SelectOption(label=label, value=value, default=profile == value)
                   for value, label in GAME_LABELS.items()]
        options.append(discord.SelectOption(label="其他遊戲／自訂", value="other"))
        super().__init__(placeholder="遊戲／版本（選填）", options=options, row=0)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock:
            session = self.cog.state["sessions"].get(self.key)
            channel = self.cog.bot.get_channel(int(self.key))
            if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
                await interaction.followup.send("呢場已結束，或者你冇修改權限。", ephemeral=True)
                return
            profile = self.values[0]
            if profile == "other":
                session["profile"] = "other"
                session["mode"] = ""
                session["game"] = ""
            else:
                session.update(profile=profile, game=GAME_LABELS[profile], mode="")
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.edit_original_response(
            content="遊戲已更新，模式同人數都可以唔填。",
            view=RecruitmentChoices(self.cog, self.key, session))


class Details(discord.ui.Modal, title="組隊狀態"):
    game = discord.ui.TextInput(label="玩緊乜？（選填）", max_length=100, required=False)
    mode = discord.ui.TextInput(label="模式（選填／自訂）", max_length=100, required=False)
    missing = discord.ui.TextInput(label="仲缺幾人？（留空＝不限人數）", max_length=2, required=False)

    def __init__(self, cog, key, session):
        super().__init__()
        self.cog, self.key, self.session = cog, key, session
        self.game.default = session.get("game", "")
        self.mode.default = session.get("mode", "")
        self.missing.default = "" if not session.get("missing") else str(session["missing"])

    async def on_submit(self, interaction):
        value = str(self.missing.value).strip()
        if value and (not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 99):
            await interaction.response.send_message("請填 1–99，或者留空代表不限人數。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock:
            session = self.cog.state["sessions"].get(self.key)
            channel = self.cog.bot.get_channel(int(self.key))
            if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
                await interaction.followup.send("呢場已結束，或者你冇修改權限（需為在場成員、Admin 或 Helper）。", ephemeral=True)
                return
            session.update(game=str(self.game.value).strip(), mode=str(self.mode.value).strip(),
                           missing=int(value) if value else None)
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.followup.send("已更新組隊狀態。", ephemeral=True)


class RecruitmentChoices(discord.ui.View):
    def __init__(self, cog, key, session):
        super().__init__(timeout=180)
        self.cog, self.key, self.session = cog, key, session
        profile = game_profile(cog.bot.get_channel(int(key)), session)
        self.add_item(GamePicker(cog, key, session, profile))
        self.add_item(ModePicker(cog, key, session, profile))
        for count in (1, 2, 3, None):
            button = discord.ui.Button(
                label=f"缺 {count} 人" if count else "不限人數",
                style=discord.ButtonStyle.primary, row=2)
            async def choose(interaction, value=count):
                await self.set_count(interaction, value)
            button.callback = choose
            self.add_item(button)
        button = discord.ui.Button(label="其他數量／自訂", style=discord.ButtonStyle.secondary, row=2)
        button.callback = self.details
        self.add_item(button)

    async def set_count(self, interaction, value):
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock:
            session = self.cog.state["sessions"].get(self.key)
            channel = self.cog.bot.get_channel(int(self.key))
            if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
                await interaction.followup.send("呢場已結束，或者你冇修改權限。", ephemeral=True)
                return
            session["missing"] = value
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.followup.send(
            f"已更新：缺 {value} 人。" if value else "已更新：不限人數，歡迎加入！",
            ephemeral=True)

    async def details(self, interaction):
        session = self.cog.state["sessions"].get(self.key)
        channel = self.cog.bot.get_channel(int(self.key))
        if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
            await interaction.response.send_message("呢場已結束，或者你冇修改權限。", ephemeral=True)
            return
        await interaction.response.send_modal(Details(self.cog, self.key, session))


class CardView(discord.ui.View):
    def __init__(self, cog, key, session):
        super().__init__(timeout=None)
        self.cog, self.key, self.session = cog, key, session
        self.add_item(discord.ui.Button(
            label="🎮 即刻入隊",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{config.GUILD_ID}/{key}"))
        button = discord.ui.Button(label="⚙️ 招募設定", style=discord.ButtonStyle.secondary,
                                   custom_id=f"squad:{session['id']}")
        button.callback = self.edit
        self.add_item(button)

    async def edit(self, interaction):
        session = self.cog.state["sessions"].get(self.key)
        channel = self.cog.bot.get_channel(int(self.key))
        if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
            await interaction.response.send_message("只限呢個 call 嘅在場成員、Admin 或 Helper 修改。", ephemeral=True)
            return
        await interaction.response.send_message(
            "揀遊戲模式或快捷人數；全部選填，唔填都歡迎加入。",
            view=RecruitmentChoices(self.cog, self.key, session), ephemeral=True)


class SquadCards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = os.getenv("SQUAD_CARDS_PATH", str(DATA_DIR / "squad_cards.json"))
        self.state = load_json_object(self.path, lambda: {"settings": {}, "sessions": {}})
        self.lock = asyncio.Lock()
        self.arrivals = {}
        self.last_error = None
        for key, session in self.state["sessions"].items():
            if session.get("message"):
                bot.add_view(CardView(self, key, session), message_id=session["message"])
        self.tick.start()

    def save(self):
        atomic_write_json(self.path, self.state)

    def cog_unload(self):
        self.tick.cancel()

    async def render(self, channel, session, ended=False):
        destination = self.bot.get_channel(session["destination"])
        if not destination:
            raise RuntimeError("Squad card destination unavailable")
        members = humans(channel) if channel else []
        names = session["participants"] if ended else {str(m.id): m.display_name for m in members}
        roster = "、".join(discord.utils.escape_markdown(n) for n in names.values()) or "—"
        profile = game_profile(channel, session)
        game = discord.utils.escape_markdown(session.get("game") or GAME_LABELS.get(profile, ""))
        mode = discord.utils.escape_markdown(session.get("mode", ""))
        missing = session.get("missing")
        if ended:
            title, description, colour = "🏁 今晚收工，下次再戰！", "👣 今次留個足跡，下次預埋你。", 0x808080
        elif missing is not None and missing > 0:
            title, description, colour = f"🙌 缺 {missing} 人，一齊玩！", "想加入？撳下面按鈕開啟語音頻道。", 0x57F287
        else:
            title, description, colour = "🟢 開緊團 · 歡迎加入", "有位，一齊玩！", 0x57F287
        embed = discord.Embed(title=title, description=description, colour=colour)
        if game:
            embed.add_field(name="🎮 玩緊", value=game, inline=False)
        if mode:
            embed.add_field(name="🏟️ 模式", value=mode, inline=False)
        embed.add_field(name="一齊玩過" if ended else f"👥 而家有 {len(members)} 人",
                        value=roster[:1024], inline=False)
        if ended:
            minutes = max(0, int((session["ended"] - session["started"]) // 60))
            hours, remaining = divmod(minutes, 60)
            duration = f"{hours} 小時 {remaining} 分鐘" if hours else f"{remaining} 分鐘"
            embed.add_field(name=f"⏱️ 開團時長 · {duration}",
                            value=f"<t:{int(session['started'])}:t> – <t:{int(session['ended'])}:t>")
        else:
            embed.add_field(name="📍 入呢個 call", value=f"<#{channel.id}>", inline=False)
        view = None if ended else CardView(self, str(channel.id), session)
        kwargs = dict(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        if session.get("message"):
            try:
                message = await destination.fetch_message(session["message"])
                await message.edit(content=None if ended else message.content, **kwargs)
                return
            except discord.NotFound:
                if ended:
                    return  # Do not repost a deliberately deleted card as a footprint.
        # Notify only on the original card, never on edits or replacement cards.
        first_id = session.get("first_member")
        if not ended and not session.get("message") and first_id in {m.id for m in members}:
            kwargs["content"] = f"<@{first_id}> 你係第一個到步嘅玩家，請問需要更多玩家嗎？可撳「招募設定」，遊戲同缺幾人都可以留空。"
            kwargs["allowed_mentions"] = discord.AllowedMentions(
                users=[discord.Object(id=first_id)], roles=False, everyone=False, replied_user=False)
        message = await destination.send(**kwargs)
        session["message"] = message.id
        self.save()

    async def reconcile(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        settings = self.state["settings"]
        if not guild or not settings:
            return
        routes = settings.get("routes", {})
        if "category" in settings:
            routes = {str(settings["category"]): settings["destination"], **routes}
        now = time.time()
        channels = {str(c.id): c for c in guild.voice_channels
                    if str(c.category_id) in routes and c != guild.afk_channel}
        for key in list(set(channels) | set(self.state["sessions"])):
            channel = channels.get(key)
            members = humans(channel) if channel else []
            session = self.state["sessions"].get(key)
            if not members:
                if session:
                    session.setdefault("ended", now)
                    if session.get("message"):
                        await self.render(channel, session, ended=True)
                    del self.state["sessions"][key]
                    self.save()
                continue
            if not session:
                if len(members) < 1:
                    continue
                session = dict(id=uuid.uuid4().hex, started=now, qualified=now,
                               participants={}, destination=routes[str(channel.category_id)],
                               first_member=min(members, key=lambda m: getattr(self, "arrivals", {}).get(
                                   (channel.id, m.id), now)).id)
                self.state["sessions"][key] = session
            before = dict(session["participants"])
            session["participants"].update({str(m.id): m.display_name for m in members})
            roster = sorted(m.id for m in members)
            changed = roster != session.get("roster")
            session["roster"] = roster
            if not session.get("message"):
                if len(members) < 1:
                    session["qualified"] = None
                elif session.get("qualified") is None:
                    session["qualified"] = now
                elif now - session["qualified"] >= 60:
                    await self.render(channel, session)
            elif changed:
                await self.render(channel, session)
            if changed or before != session["participants"]:
                self.save()

    @tasks.loop(seconds=15)
    async def tick(self):
        try:
            async with self.lock:
                await self.reconcile()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("Failed to reconcile squad cards; retrying next tick")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        # Unpublished timers restart: offline time cannot establish continuous presence.
        for session in self.state["sessions"].values():
            if not session.get("message"):
                session["qualified"] = None
            else:
                session.pop("roster", None)  # Refresh existing cards after a deployment.
        self.save()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id != config.GUILD_ID or before.channel == after.channel:
            return
        try:
            async with self.lock:
                if before.channel:
                    self.arrivals.pop((before.channel.id, member.id), None)
                if after.channel and not member.bot:
                    self.arrivals[(after.channel.id, member.id)] = time.time()
                await self.reconcile()
        except Exception:
            log.exception("Failed to update squad card after voice change")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if str(channel.id) in self.state["sessions"]:
            async with self.lock:
                await self.reconcile()

    @app_commands.command(name="squad_setup", description="設定自動組隊卡：一人留滿1分鐘後詢問隊友")
    @app_commands.guild_only()
    @app_commands.check(lambda i: is_admin_or_helper(i.user))
    async def squad_setup(self, interaction: discord.Interaction,
                          category: discord.CategoryChannel, destination: discord.TextChannel):
        permissions = destination.permissions_for(interaction.guild.me)
        if not all((permissions.view_channel, permissions.send_messages,
                    permissions.embed_links, permissions.read_message_history)):
            await interaction.response.send_message("Bot 喺狀態卡頻道需要查看、發訊息、嵌入連結及讀取歷史權限。", ephemeral=True)
            return
        async with self.lock:
            settings = self.state["settings"]
            routes = dict(settings.get("routes", {}))
            if "category" in settings:
                routes.setdefault(str(settings["category"]), settings["destination"])
            routes[str(category.id)] = destination.id
            self.state["settings"] = {"routes": routes}
            self.save()
        task = self.tick.get_task()
        loop_status = "running" if self.tick.is_running() else "stopped"
        if task and task.done() and not task.cancelled() and task.exception():
            self.last_error = str(task.exception())
        channels = [c for c in interaction.guild.voice_channels if c.category_id == category.id]
        diagnostics = [f"{c.name}: humans={len(humans(c))}, session={self.state['sessions'].get(str(c.id), {}).get('qualified')}, card={self.state['sessions'].get(str(c.id), {}).get('message')}" for c in channels]
        diagnostic_text = "\n".join(diagnostics)[:1000]
        await interaction.response.send_message(
            f"loop={loop_status}; error={self.last_error}\n{diagnostic_text}\n"
            f"已設定：監察 {category.name}；組隊卡發到 {destination.mention}。一人以上連續1分鐘先問；散 band 轉足跡。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SquadCards(bot), guild=TARGET)
