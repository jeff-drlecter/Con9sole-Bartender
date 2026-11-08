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
from core.action_guard import shared_async_lock
from core.storage_paths import DATA_DIR
from core.ui import SafeView
from features import squad_interest
from features.menu_stats import run_stats

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
            session["dirty"] = True
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
            session["dirty"] = True
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
            session["dirty"] = True
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
            session["dirty"] = True
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




def interest_topic(channel, session):
    # Legacy footprints may carry a mode-scoped topic; storage aliases retain
    # their old button IDs while new sessions always use game-only topics.
    if session.get("interest_topic"):
        return session["interest_topic"]
    profile = game_profile(channel, session)
    game = session.get("game") or GAME_LABELS.get(profile, "")
    if not game:
        category = getattr(channel, "category", None)
        game = getattr(category, "name", "")
    return squad_interest.topic(config.GUILD_ID, game)


INTEREST_FIELD = "🙋 下次叫埋"
RECURRING_FIELD = "🔔 每次都叫"


def interest_roster(guild, destination, ids):
    """Only expose current members who can see this card; mentions never ping."""
    result = []
    if guild is None or destination is None:
        return result
    for uid in ids:
        member = guild.get_member(uid)
        if member and not member.bot and destination.permissions_for(member).view_channel:
            result.append((uid, discord.utils.escape_mentions(
                discord.utils.escape_markdown(member.display_name))))
    return result


def interest_summary(roster):
    lines = []
    for uid, name in roster:
        line = f"<@{uid}>"
        if len("、".join(lines + [line])) > 900:
            break
        lines.append(line)
    if not lines:
        return "未有人登記。"
    suffix = f"\n另有 {len(roster) - len(lines)} 人，撳「查看／更新名單」。" if len(lines) < len(roster) else ""
    return "、".join(lines) + suffix


class InterestRosterPages(SafeView):
    """Private, requester-only pages; public card stays compact."""
    def __init__(self, user_id, roster, label, *, source_view=None, source_message=None):
        super().__init__(timeout=180)
        self.user_id, self.roster, self.label, self.page = user_id, roster, label, 0
        self.source_view, self.source_message = source_view, source_message
        if source_view is not None:
            for kind, label in (("once", "🙋 下次叫我"), ("always", "🔔 每次都叫我")):
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=1)
                async def choose(interaction, choice=kind):
                    await self.source_view.toggle(interaction, choice,
                        source_message=self.source_message, roster_pages=self)
                button.callback = choose
                self.add_item(button)
        self.previous.disabled = True
        self.next_page.disabled = len(roster) <= 20

    def embed(self):
        start = self.page * 20
        lines = [f"<@{uid}> · {name}" for uid, name in self.roster[start:start + 20]]
        embed = discord.Embed(title="🙋 下次想玩", description="\n".join(lines) or "暫時未有人登記。", colour=0x5865F2)
        embed.set_footer(text=f"{self.label} · {len(self.roster)} 人 · 第 {self.page + 1}/{max(1, (len(self.roster) + 19) // 20)} 頁")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("請由足跡卡開啟自己嘅名單。", ephemeral=True)
            return False
        return True

    async def move(self, interaction, delta):
        self.page = max(0, min((max(1, len(self.roster)) - 1) // 20, self.page + delta))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = (self.page + 1) * 20 >= len(self.roster)
        await interaction.response.edit_message(embed=self.embed(), view=self,
                                                allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.move(interaction, -1)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        await self.move(interaction, 1)


def add_interest_fields(embed, roster, preferences):
    """Remove legacy public subscription fields; rosters are button-only."""
    for index in reversed(range(len(embed.fields))):
        if embed.fields[index].name.startswith((INTEREST_FIELD, RECURRING_FIELD, "🙋 下次想玩")):
            embed.remove_field(index)


class FootprintView(SafeView):
    def __init__(self, cog, value):
        super().__init__(timeout=None)
        self.cog, self.topic = cog, dict(value, label=value['label'].split(' · ', 1)[0])
        self.lock = cog.lock if cog is not None else asyncio.Lock()
        for kind, label, prefix in (("once", "🙋 下次叫我", "squad-interest"),
                                     ("always", "🔔 每次都叫我", "squad-interest-always")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                       custom_id=f"{prefix}:{value['id']}")
            async def choose(interaction, choice=kind):
                await self.toggle(interaction, choice)
            button.callback = choose
            self.add_item(button)
        button = discord.ui.Button(label="👥 查看／更新名單", style=discord.ButtonStyle.secondary,
                                   custom_id=f"squad-interest-roster:{value['id']}")
        button.callback = self.show_roster
        self.add_item(button)

    async def permitted(self, interaction):
        if interaction.guild_id != self.topic["guild_id"] or interaction.user.bot:
            await interaction.response.send_message("請喺原本伺服器使用。", ephemeral=True)
            return False
        if not interaction.permissions.view_channel:
            await interaction.response.send_message("你未有查看呢個頻道嘅權限。", ephemeral=True)
            return False
        return True

    def source_session(self, message_id):
        if self.cog is not None:
            for session in self.cog.state["sessions"].values():
                if session.get("message") == message_id:
                    return session['id']
        return squad_interest.card_session(message_id)

    async def refresh(self, interaction, *, source_message=None):
        source_message = source_message if source_message is not None else interaction.message
        await run_stats(squad_interest.track_card, self.topic['id'], interaction.channel_id,
                        source_message.id, self.source_session(source_message.id))
        preferences = await run_stats(squad_interest.preferences, self.topic['id'])
        roster = interest_roster(interaction.guild, interaction.channel, preferences)
        if self.cog is not None:
            await self.cog.refresh_interest_cards(self.topic)
        else:
            message = await interaction.channel.fetch_message(source_message.id)
            if message.author.id != interaction.client.user.id or not message.embeds:
                raise ValueError("Not a bot card")
            embed = message.embeds[0].copy()
            add_interest_fields(embed, roster, preferences)
            await message.edit(embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none())
        return [(uid, f"{name}（{'下次叫我' if preferences[uid] == 'once' else '每次都叫我'}）")
                for uid, name in roster]

    async def show_roster(self, interaction):
        if not await self.permitted(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            roster = await self.refresh(interaction)
        pages = InterestRosterPages(interaction.user.id, roster, self.topic['label'],
                                    source_view=self, source_message=interaction.message)
        await interaction.followup.send(embed=pages.embed(), view=pages, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    async def toggle(self, interaction, kind='once', *, source_message=None, roster_pages=None):
        if not await self.permitted(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=roster_pages is None)
        source_message = source_message if source_message is not None else interaction.message
        async with self.lock:
            joined = await run_stats(squad_interest.toggle, self.topic['id'], interaction.guild_id,
                                     interaction.user.id, kind, self.source_session(source_message.id))
            refreshed = True
            try:
                roster = await self.refresh(interaction, source_message=source_message)
            except (discord.HTTPException, ValueError):
                refreshed = False
                log.exception("Card roster refresh failed: message=%s", interaction.message.id)
        if joined:
            interaction.client.dispatch("community_activity", interaction.user, interaction.channel,
                             f"interest:{self.topic['id']}:{interaction.user.id}:{interaction.id}")
        label = discord.utils.escape_mentions(discord.utils.escape_markdown(self.topic['label']))
        if not joined:
            text = f"已取消 **{label}** 開局通知。"
        elif kind == 'once':
            text = f"🙋 記低咗，下次 **{label}** 開局叫埋你！只通知下一局；再撳就取消。"
        else:
            text = f"🔔 記低咗，以後每次 **{label}** 開局都叫你！再撳就取消。"
        if not refreshed:
            text += "\n登記已儲存；卡片暫時未更新，可撳「查看／更新名單」重試。"
        if roster_pages is not None:
            if refreshed:
                roster_pages.roster = roster
            roster_pages.page = min(roster_pages.page, max(0, (len(roster_pages.roster) - 1) // 20))
            roster_pages.previous.disabled = roster_pages.page == 0
            roster_pages.next_page.disabled = (roster_pages.page + 1) * 20 >= len(roster_pages.roster)
            await interaction.edit_original_response(content=text, embed=roster_pages.embed(),
                view=roster_pages, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class CardView(FootprintView):
    def __init__(self, cog, key, session):
        value = interest_topic(cog.bot.get_channel(int(key)), session)
        # A room category normally supplies the game; unknown games still get
        # join/settings controls without creating a notification subscription.
        if value:
            super().__init__(cog, value)
        else:
            SafeView.__init__(self, timeout=None)
        self.cog, self.key, self.session = cog, key, session
        interests = list(self.children)
        self.clear_items()
        self.add_item(discord.ui.Button(label="🎮 加入語音", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{config.GUILD_ID}/{key}"))
        for item in interests:
            self.add_item(item)
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


class SessionNoticeView(FootprintView):
    def __init__(self, cog, value, voice_id):
        super().__init__(cog, value)
        self.add_item(discord.ui.Button(label="🎮 加入語音", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{value['guild_id']}/{voice_id}"))


class SquadCards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = os.getenv("SQUAD_CARDS_PATH", str(DATA_DIR / "squad_cards.json"))
        self.state = load_json_object(self.path, lambda: {"settings": {}, "sessions": {}})
        self.interest_baseline = {s["id"] for s in self.state["sessions"].values() if s.get("message")}
        self.lock = asyncio.Lock()
        self.arrivals = {}
        self.last_error = None
        for key, session in self.state["sessions"].items():
            if session.get("message"):
                bot.add_view(CardView(self, key, session), message_id=session["message"])
        for value in squad_interest.topics():
            bot.add_view(FootprintView(self, value))
        self.tick.start()

    def save(self):
        atomic_write_json(self.path, self.state)

    def cog_unload(self):
        self.tick.cancel()

    async def render(self, channel, session, ended=False):
        session["dirty"] = True
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
            title, colour = "🏁 今晚收工，下次再戰！", 0x808080
        elif missing is not None and missing > 0:
            title, colour = f"🙌 缺 {missing} 人，一齊玩！", 0x57F287
        else:
            title, colour = "🟢 開緊團 · 歡迎加入", 0x57F287
        lines = []
        game_mode = " · ".join(part for part in (game, mode) if part)
        if game_mode:
            lines.append(f"🎮 {game_mode}")
        lines.append(f"👥 {'一齊玩過' if ended else str(len(members)) + ' 人'} · {roster[:1024]}")
        if ended:
            minutes = max(0, int((session["ended"] - session["started"]) // 60))
            hours, remaining = divmod(minutes, 60)
            duration = f"{hours} 小時 {remaining} 分鐘" if hours else f"{remaining} 分鐘"
            lines.append(f"⏱️ <t:{int(session['started'])}:t> – <t:{int(session['ended'])}:t> · {duration}")
        else:
            lines.append(f"📍 <#{channel.id}>")
        embed = discord.Embed(title=title, description="\n".join(lines), colour=colour)
        value = interest_topic(channel, session)
        if value:
            if ended:
                session["interest_topic"] = value
            await run_stats(squad_interest.remember, value)
            preferences = await run_stats(squad_interest.preferences, value['id'])
            roster = interest_roster(self.bot.get_guild(value['guild_id']), destination, preferences)
            add_interest_fields(embed, roster, preferences)
        view = (FootprintView(self, value) if value else None) if ended else CardView(self, str(channel.id), session)
        kwargs = dict(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        if session.get("message"):
            try:
                message = await destination.fetch_message(session["message"])
                await message.edit(content=None if ended else message.content, **kwargs)
                session["dirty"] = False
                if value:
                    await run_stats(squad_interest.track_card, value['id'], destination.id,
                                    session['message'], '' if ended else session['id'])
                if ended and value:
                    self.bot.add_view(FootprintView(self, value))
                if not ended:
                    await self.notify_interested(channel, session)
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
        session["dirty"] = False
        self.save()
        if value:
            await run_stats(squad_interest.track_card, value['id'], destination.id,
                            message.id, '' if ended else session['id'])
        if not ended:
            await self.notify_interested(channel, session)

    async def refresh_interest_cards(self, value):
        preferences = await run_stats(squad_interest.preferences, value['id'])
        guild = self.bot.get_guild(value['guild_id'])
        for record in await run_stats(squad_interest.cards, value['id']):
            destination = self.bot.get_channel(record['channel_id'])
            if destination is None:
                continue
            try:
                message = await destination.fetch_message(record['message_id'])
                if message.author.id != self.bot.user.id or not message.embeds:
                    await run_stats(squad_interest.forget_card, record['message_id'])
                    continue
                embed = message.embeds[0].copy()
                roster = interest_roster(guild, destination, preferences)
                add_interest_fields(embed, roster, preferences)
                view = FootprintView(self, value)
                for key, session in self.state['sessions'].items():
                    if session.get('message') == message.id:
                        view = CardView(self, key, session)
                        break
                    if session['id'] == record['session_id']:
                        view = SessionNoticeView(self, value, key)
                        break
                await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                await run_stats(squad_interest.forget_card, record['message_id'])
            except discord.HTTPException:
                log.exception("Could not refresh interest roster: message=%s", record['message_id'])

    async def notify_interested(self, channel, session):
        try:
            async with shared_async_lock('subscription-delivery',channel.guild.id if channel else config.GUILD_ID,session['id']):
                await self._notify_interested_locked(channel,session)
        except Exception:
            log.exception('Could not start subscription delivery: session=%s',session.get('id'))

    async def _notify_interested_locked(self, channel, session, retry_batch=None):
        try:
            if session['id'] in self.interest_baseline and retry_batch is None:
                return  # Deployments never tag people for a game already in progress.
            value = interest_topic(channel, session)
            if value is None:
                return
            destination = self.bot.get_channel(session['destination'])
            guild = channel.guild
            ids = await run_stats(squad_interest.members, value['id'])
            present = {m.id for m in humans(channel)}
            eligible = []
            for uid in ids:
                member = guild.get_member(uid)
                if member is None or member.bot or uid in present:
                    continue
                voice_perms = channel.permissions_for(member)
                text_perms = destination.permissions_for(member)
                if voice_perms.view_channel and voice_perms.connect and text_perms.view_channel:
                    eligible.append(uid)
            await run_stats(squad_interest.remember, value)
            if retry_batch is None:
                await run_stats(squad_interest.reserve, session['id'], value['id'], eligible)
            await run_stats(squad_interest.delivery_context,session['id'],value['id'],
                            dict(guild=guild.id,channel=destination.id,card=session['message'],voice=channel.id))
            batches = await run_stats(squad_interest.pending_deliveries, session['id'], value['id'])
            if retry_batch is not None:batches=[b for b in batches if b[0]==retry_batch]
            if not batches:
                return
            label = discord.utils.escape_markdown(value['label'])
            url = f"https://discord.com/channels/{guild.id}/{destination.id}/{session['message']}"
            for batch_id, batch in batches:
                revision=await run_stats(squad_interest.claim_delivery,session['id'],value['id'],batch_id)
                if not revision:
                    continue
                allowed=[]
                for uid in batch:
                    member=guild.get_member(uid)
                    if member and not member.bot and uid not in present:
                        vp=channel.permissions_for(member)
                        if vp.view_channel and vp.connect and destination.permissions_for(member).view_channel:
                            allowed.append(uid)
                batch=allowed
                if not batch:
                    await run_stats(squad_interest.finish_delivery,session['id'],value['id'],batch_id,expected_revision=revision)
                    continue
                mentions = " ".join(f"<@{uid}>" for uid in batch)
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="🎮 加入語音", style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{guild.id}/{channel.id}"))
                try:
                    message=await destination.send(
                        f"{mentions}｜🎮 **{label}** 開局喇！[查看召人卡]({url})",
                        view=view, suppress_embeds=True,
                        allowed_mentions=discord.AllowedMentions(
                            users=[discord.Object(id=uid) for uid in batch], roles=False,
                            everyone=False, replied_user=False))
                except discord.HTTPException as exc:
                    if 400<=exc.status<500 and exc.status!=408:
                        await run_stats(squad_interest.finish_delivery,session['id'],value['id'],batch_id,retry=True,expected_revision=revision)
                    raise
                await run_stats(squad_interest.finish_delivery,session['id'],value['id'],batch_id,message_id=message.id,expected_revision=revision)
            await self.refresh_interest_cards(value)
        except Exception:
            log.exception("Next-session notification failed: session=%s", session.get('id'))

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
            try:
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
                display = {str(m.id): m.display_name for m in members}
                changed = roster != session.get("roster") or display != session.get("display") or session.get("dirty", False)
                if not session.get("message"):
                    if len(members) < 1:
                        session["qualified"] = None
                    elif session.get("qualified") is None:
                        session["qualified"] = now
                    elif now - session["qualified"] >= 30:
                        await self.render(channel, session)
                elif changed:
                    await self.render(channel, session)
                if session.get('message'):
                    await self.notify_interested(channel,session)
                # Commit the roster only after rendering succeeds so a failed edit
                # remains pending and is retried by the next reconciliation.
                session["roster"] = roster
                session["display"] = display
                if changed or before != session["participants"]:
                    self.save()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Squad card update failed: channel=%s; continuing other sessions", key)

    @tasks.loop(seconds=5)
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
        for value in await run_stats(squad_interest.topics):
            try:
                await self.refresh_interest_cards(value)
            except Exception:
                log.exception("Could not hide legacy subscription fields: topic=%s", value["id"])
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

    @app_commands.command(name="squad_setup", description="設定自動組隊卡：一人留滿30秒後發召人卡")
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
            f"已設定：監察 {category.name}；組隊卡發到 {destination.mention}。一人以上連續30秒出卡；散 band 轉足跡。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SquadCards(bot), guild=TARGET)
