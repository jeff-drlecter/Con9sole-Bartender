"""Voice recruitment cards. Configure with /squad_setup; first-arrival user ping only."""
from __future__ import annotations
from features.wording import text as wording_text, view_copy as wording_view, modal_copy as wording_modal

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
from core.permissions import is_admin_or_helper, is_server_admin
from core.action_guard import shared_async_lock
from core.storage_paths import DATA_DIR
from core.ui import SafeView
from features import squad_interest, squad_participants
from features.menu_stats import run_stats

log = logging.getLogger(__name__)
TARGET = discord.Object(id=config.GUILD_ID)


def humans(channel):
    return [m for m in channel.members if not m.bot]


def sync_mode_name(cog, channel, session):
    tempvc = cog.bot.get_cog("TempVC")
    if tempvc is not None:
        tempvc.queue_mode_name(channel, session.get("mode", ""))


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
                await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "呢場已結束，或者你冇修改權限。"), ephemeral=True)
                return
            value = self.values[0]
            if value == "__custom__":
                await interaction.response.send_modal(wording_modal(interaction.user, Details(self.cog, self.key, session)))
                return
            if self.profile != game_profile(channel, session):
                await interaction.response.send_message("遊戲設定已改，請重新開啟招募設定。", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            session["mode"] = "" if value == "__none__" else value
            sync_mode_name(self.cog, channel, session)
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
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), "呢場已結束，或者你冇修改權限。"), ephemeral=True)
                return
            profile = self.values[0]
            if profile == "other":
                session["profile"] = "other"
                session["mode"] = ""
                session["game"] = ""
            else:
                session.update(profile=profile, game=GAME_LABELS[profile], mode="")
            sync_mode_name(self.cog, channel, session)
            session["dirty"] = True
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.edit_original_response(
            content=wording_text(getattr(interaction, "user", None), "遊戲已更新，模式同人數都可以唔填。"),
            view=wording_view(interaction.user, RecruitmentChoices(self.cog, self.key, session)))


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
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), "呢場已結束，或者你冇修改權限（需為在場成員、Admin 或 Helper）。"), ephemeral=True)
                return
            session.update(game=str(self.game.value).strip(), mode=str(self.mode.value).strip(),
                           missing=int(value) if value else None)
            sync_mode_name(self.cog, channel, session)
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
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), "呢場已結束，或者你冇修改權限。"), ephemeral=True)
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
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "呢場已結束，或者你冇修改權限。"), ephemeral=True)
            return
        await interaction.response.send_modal(wording_modal(interaction.user, Details(self.cog, self.key, session)))




def interest_topic(channel, session):
    # Legacy footprints may carry a mode-scoped topic; storage aliases retain
    # their old button IDs while new sessions always use game-only topics.
    if session.get("interest_topic"):
        return session["interest_topic"]
    if channel is None and session.get('last_interest_topic'):
        return session['last_interest_topic']
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
    suffix = f"\n另有 {len(roster) - len(lines)} 人，按「下次通知名單」。" if len(lines) < len(roster) else ""
    return "、".join(lines) + suffix


class InterestRosterPages(SafeView):
    """Private, requester-only pages; public card stays compact."""
    def __init__(self, user_id, roster, label, *, source_view=None, source_message=None):
        super().__init__(timeout=180)
        self.user_id, self.roster, self.label, self.page = user_id, roster, label, 0
        self.source_view, self.source_message = source_view, source_message
        if source_view is not None:
            for kind, label in (("once", "🙋 下次通知我"), ("always", "🔔 每次通知我")):
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
        embed = discord.Embed(title="🔔 下次通知名單", description="\n".join(lines) or "暫時未有人登記。", colour=0x5865F2)
        embed.set_footer(text=f"{self.label} · {len(self.roster)} 人 · 第 {self.page + 1}/{max(1, (len(self.roster) + 19) // 20)} 頁")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "請由足跡卡開啟自己嘅名單。"), ephemeral=True)
            return False
        return True

    async def move(self, interaction, delta):
        self.page = max(0, min((max(1, len(self.roster)) - 1) // 20, self.page + delta))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = (self.page + 1) * 20 >= len(self.roster)
        await interaction.response.edit_message(embed=self.embed(), view=wording_view(interaction.user, self),
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


class ParticipantPages(SafeView):
    """Read-only attendance, limited to its requester and original channel."""
    def __init__(self, interaction, snapshot):
        super().__init__(timeout=180)
        self.owner, self.guild_id, self.channel_id = interaction.user.id, interaction.guild_id, interaction.channel_id
        self.page = 0
        lines = []
        for uid in snapshot['names']:
            member = interaction.guild.get_member(int(uid))
            if member and not member.bot and interaction.channel.permissions_for(member).view_channel:
                name = discord.utils.escape_mentions(discord.utils.escape_markdown(member.display_name))
                lines.append(f'<@{uid}> · {name}')
        # Legacy cards recorded names only; do not infer identities or tag them.
        for raw in snapshot['legacy']:
            lines.append(discord.utils.escape_mentions(discord.utils.escape_markdown(raw)))
        self.pages = ['']
        for line in lines:
            for start in range(0, len(line), 2800):
                part = line[start:start + 2800]
                if len(self.pages[-1]) + len(part) + 1 > 3000:
                    self.pages.append('')
                self.pages[-1] += ('\n' if self.pages[-1] else '') + part
        self.previous.disabled = True
        self.next_page.disabled = len(self.pages) == 1

    def embed(self):
        embed = discord.Embed(title='👥 本局參與者', description=self.pages[self.page] or '沒有可顯示的參與紀錄。')
        embed.set_footer(text=f'只顯示給你 · 第 {self.page + 1}/{len(self.pages)} 頁')
        return embed

    async def interaction_check(self, interaction):
        if (interaction.guild_id == self.guild_id and interaction.channel_id == self.channel_id
                and interaction.user.id == self.owner and not interaction.user.bot
                and interaction.channel.permissions_for(interaction.user).view_channel):
            return True
        await interaction.response.send_message('請在原本頻道重新開啟名單。', ephemeral=True)
        return False

    async def move(self, interaction, delta):
        if not await self.interaction_check(interaction):
            return
        self.page = max(0, min(len(self.pages) - 1, self.page + delta))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page == len(self.pages) - 1
        await interaction.response.edit_message(embed=self.embed(), view=self, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label='上一頁')
    async def previous(self, interaction, button):
        await self.move(interaction, -1)

    @discord.ui.button(label='下一頁')
    async def next_page(self, interaction, button):
        await self.move(interaction, 1)


class FootprintView(SafeView):
    def __init__(self, cog, value, *, include_plan=True):
        super().__init__(timeout=None)
        self.cog, self.topic = cog, dict(value, label=value['label'].split(' · ', 1)[0])
        self.lock = cog.lock if cog is not None else asyncio.Lock()
        for kind, label, prefix in (("once", "🙋 下次通知我", "squad-interest"),
                                     ("always", "🔔 每次通知我", "squad-interest-always")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                       custom_id=f"{prefix}:{value['id']}", row=0)
            async def choose(interaction, choice=kind):
                await self.toggle(interaction, choice)
            button.callback = choose
            self.add_item(button)
        button = discord.ui.Button(label='👥 本局參與者', custom_id=f"squad-participants:{value['id']}", row=1)
        button.callback = self.show_participants
        self.add_item(button)
        button = discord.ui.Button(label="🔔 下次通知名單", style=discord.ButtonStyle.secondary,
                                   custom_id=f"squad-interest-roster:{value['id']}", row=1)
        button.callback = self.show_roster
        self.add_item(button)
        if include_plan:
            button = discord.ui.Button(label='📅 發起下次', style=discord.ButtonStyle.secondary,
                                       custom_id=f"squad-next-plan:{value['id']}", row=1)
            button.callback = self.create_next
            self.add_item(button)

    async def show_participants(self, interaction):
        if not await self.permitted(interaction):
            return
        if interaction.message.author.id != interaction.client.user.id:
            await interaction.response.send_message('請由原本的組隊卡開啟。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            snapshot = await run_stats(squad_participants.get, interaction.message.id, interaction.guild_id, interaction.channel_id)
            if snapshot is None:
                # Persist legacy names before removing them from an old public card.
                embed = interaction.message.embeds[0].copy() if interaction.message.embeds else None
                legacy = squad_participants.compact_legacy(embed) if embed else []
                if legacy:
                    await run_stats(squad_participants.preserve_legacy, interaction.message.id, interaction.guild_id, interaction.channel_id, legacy)
                    snapshot = dict(names={}, legacy=legacy)
            if snapshot is None:
                await interaction.followup.send('這張舊卡未保留本局參與紀錄；下次通知名單是另一份名單。', ephemeral=True)
                return
            pages = ParticipantPages(interaction, snapshot)
        await interaction.followup.send(embed=pages.embed(), view=pages, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def create_next(self, interaction):
        if not await self.permitted(interaction):
            return
        plans = interaction.client.get_cog('SquadPlans')
        if plans is None:
            await interaction.response.send_message('預約功能暫時未能使用，請稍後再試。', ephemeral=True)
            return
        from cogs.squad_plans import allowed, squad_channel, PlanForm
        if not squad_channel(interaction.channel) or not allowed(interaction):
            await plans.menu_entry(interaction)
            return
        form = PlanForm(plans, interaction.channel)
        form.game.default = self.topic['label']
        # The card carries this session's mode; subscriptions remain game-scoped.
        for embed in getattr(interaction.message, 'embeds', []):
            first_line = (embed.description or '').split('\n', 1)[0]
            prefix = '🎮 ' + discord.utils.escape_markdown(self.topic['label']) + ' · '
            if first_line.startswith(prefix):
                form.mode.default = first_line[len(prefix):][:80]
                break
        await interaction.response.send_modal(wording_modal(interaction.user, form))

    async def permitted(self, interaction):
        if interaction.guild_id != self.topic["guild_id"] or interaction.user.bot:
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "請喺原本伺服器使用。"), ephemeral=True)
            return False
        if not interaction.permissions.view_channel:
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "你未有查看呢個頻道嘅權限。"), ephemeral=True)
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
            legacy = squad_participants.compact_legacy(embed)
            if legacy:
                await run_stats(squad_participants.preserve_legacy, message.id, self.topic['guild_id'], interaction.channel_id, legacy)
            add_interest_fields(embed, roster, preferences)
            await message.edit(embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none())
        return [(uid, f"{name}（{'下次通知' if preferences[uid] == 'once' else '每次通知'}）")
                for uid, name in roster]

    async def show_roster(self, interaction):
        if not await self.permitted(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Public subscription lists are hidden, so a read must not edit every
        # historical card or wait behind voice/notification reconciliation.
        preferences = await run_stats(squad_interest.preferences, self.topic['id'])
        roster = [(uid, f"{name}（{'下次通知' if preferences[uid] == 'once' else '每次通知'}）")
                  for uid, name in interest_roster(interaction.guild, interaction.channel, preferences)]
        pages = InterestRosterPages(interaction.user.id, roster, self.topic['label'],
                                    source_view=self, source_message=interaction.message)
        await interaction.followup.send(embed=pages.embed(), view=wording_view(interaction.user, pages), ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    async def toggle(self, interaction, kind='once', *, source_message=None, roster_pages=None):
        if not await self.permitted(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=roster_pages is None)
        source_message = source_message if source_message is not None else interaction.message
        async with self.lock:
            consent_scope=await run_stats(squad_interest.canonical_scope,self.topic['id'])
            async with shared_async_lock('subscription-consent',interaction.guild_id,consent_scope):
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
            text = '{0}{1}{2}'.format(wording_text(getattr(interaction, 'user', None), '🙋 記低咗，下次 **'), label, wording_text(getattr(interaction, 'user', None), '** 開局叫埋你！只通知下一局；再撳就取消。'))
        else:
            text = '{0}{1}{2}'.format(wording_text(getattr(interaction, 'user', None), '🔔 記低咗，以後每次 **'), label, wording_text(getattr(interaction, 'user', None), '** 開局都叫你！再撳就取消。'))
        if not refreshed:
            text += '\n登記已儲存；卡片暫時未更新，可按「下次通知名單」重試。'
        if roster_pages is not None:
            if refreshed:
                roster_pages.roster = roster
            roster_pages.page = min(roster_pages.page, max(0, (len(roster_pages.roster) - 1) // 20))
            roster_pages.previous.disabled = roster_pages.page == 0
            roster_pages.next_page.disabled = (roster_pages.page + 1) * 20 >= len(roster_pages.roster)
            await interaction.edit_original_response(content=text, embed=roster_pages.embed(),
                view=wording_view(interaction.user, roster_pages), allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class CardView(FootprintView):
    def __init__(self, cog, key, session):
        value = interest_topic(cog.bot.get_channel(int(key)), session)
        # A room category normally supplies the game; unknown games still get
        # join/settings controls without creating a notification subscription.
        if value:
            super().__init__(cog, value, include_plan=False)
        else:
            SafeView.__init__(self, timeout=None)
        self.cog, self.key, self.session = cog, key, session
        interests = list(self.children)
        self.clear_items()
        self.add_item(discord.ui.Button(label="🎮 加入語音", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{config.GUILD_ID}/{key}", row=0))
        for item in interests:
            item.row = 0 if item.custom_id.startswith('squad-participants:') else 1
            self.add_item(item)
        button = discord.ui.Button(label="⚙️ 招募設定", style=discord.ButtonStyle.secondary,
                                   custom_id=f"squad:{session['id']}", row=0)
        button.callback = self.edit
        self.add_item(button)

    async def edit(self, interaction):
        session = self.cog.state["sessions"].get(self.key)
        channel = self.cog.bot.get_channel(int(self.key))
        if session is not self.session or not channel or (not is_admin_or_helper(interaction.user) and interaction.user not in humans(channel)):
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "只限呢個 call 嘅在場成員、Admin 或 Helper 修改。"), ephemeral=True)
            return
        await interaction.response.send_message(
            wording_text(getattr(interaction, "user", None), "揀遊戲模式或快捷人數；全部選填，唔填都歡迎加入。"),
            view=wording_view(interaction.user, RecruitmentChoices(self.cog, self.key, session)), ephemeral=True)


class SessionNoticeView(FootprintView):
    def __init__(self, cog, value, voice_id):
        super().__init__(cog, value, include_plan=False)
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
        if session.get('id'):
            latest = await run_stats(squad_interest.latest_card_post,session['id'])
            if latest and latest['state']=='sent' and latest['message_id'] and session.get('message')!=latest['message_id']:
                session['message']=latest['message_id']
                self.save()
        destination = self.bot.get_channel(session["destination"])
        if not destination:
            raise RuntimeError("Squad card destination unavailable")
        members = humans(channel) if channel else []
        names = session["participants"] if ended else {str(m.id): m.display_name for m in members}
        profile = game_profile(channel, session)
        game_label=session.get("game") or GAME_LABELS.get(profile, "") or (session.get('last_game_label','') if channel is None else '')
        if channel is not None:session['last_game_label']=game_label
        game = discord.utils.escape_markdown(game_label)
        mode = discord.utils.escape_markdown(session.get("mode", ""))
        missing = session.get("missing")
        if ended:
            title, colour = "🏁 本局已結束，下次再戰！", 0x808080
        elif missing is not None and missing > 0:
            title, colour = f"🙌 缺 {missing} 人，歡迎加入！", 0x57F287
        else:
            title, colour = "🟢 組隊中 · 歡迎加入", 0x57F287
        lines = []
        game_mode = " · ".join(part for part in (game, mode) if part)
        if game_mode:
            lines.append(f"🎮 {game_mode}")
        lines.append(f"👥 {'參與 ' if ended else ''}{len(names)} 人")
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
            session['last_interest_topic']=value
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
                if ended and session.get('id'):
                    await self.finish_footprint(destination, message, session, embed, view, value)
                    return
                await run_stats(squad_participants.save, message.id, config.GUILD_ID, destination.id, names)
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
            kwargs["content"] = f"<@{first_id}> 想找隊友？按「招募設定」選擇模式及人數；全部選填。"
            kwargs["allowed_mentions"] = discord.AllowedMentions(
                users=[discord.Object(id=first_id)], roles=False, everyone=False, replied_user=False)
        ready=getattr(self.bot,'is_ready',None)
        if callable(ready) and not ready():return
        attempt = await run_stats(squad_interest.begin_card_post,session['id'],destination.id,channel.id) if session.get('id') else None
        if callable(ready) and not ready():
            if attempt:await run_stats(squad_interest.finish_card_post,attempt,rejected=True)
            return
        try:
            message = await destination.send(**kwargs)
        except discord.HTTPException as exc:
            if attempt and 400<=exc.status<500 and exc.status!=408:
                await run_stats(squad_interest.finish_card_post,attempt,rejected=True)
            raise
        session["message"] = message.id
        if attempt:
            await run_stats(squad_interest.finish_card_post,attempt,message_id=message.id)
        await run_stats(squad_participants.save, message.id, config.GUILD_ID, destination.id, names)
        session["dirty"] = False
        self.save()
        if value:
            await run_stats(squad_interest.track_card, value['id'], destination.id,
                            message.id, '' if ended else session['id'])
        if not ended:
            await self.notify_interested(channel, session)

    async def finish_footprint(self, destination, original, session, embed, view, value):
        """Journal the separate closing post before sending; never replay uncertainty."""
        async with shared_async_lock('squad-footprint', config.GUILD_ID, session['id']):
            await original.edit(content='本局已結束 · 正在整理足跡', embed=None,
                                view=None, allowed_mentions=discord.AllowedMentions.none())
            # A brief solo visit is not a completed group session.
            qualified = len(session['participants']) >= 2 and session['ended'] - session['started'] >= 60
            if not qualified:
                await original.edit(content='本局已結束', embed=None, view=None,
                                    allowed_mentions=discord.AllowedMentions.none())
                await run_stats(squad_interest.forget_card, original.id)
                session['dirty'] = False
                return
            journal_id = session['id'] + ':footprint'
            latest = await run_stats(squad_interest.latest_card_post, journal_id)
            footprint_id = latest['message_id'] if latest and latest['state'] == 'sent' else None
            if not footprint_id:
                if not self.bot.is_ready():
                    raise RuntimeError('Disconnected before footprint send')
                attempt = await run_stats(squad_interest.begin_card_post, journal_id, destination.id, 0)
                try:
                    footprint = await destination.send(embed=embed, view=view,
                        allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException as exc:
                    if 400 <= exc.status < 500 and exc.status != 408:
                        await run_stats(squad_interest.finish_card_post, attempt, rejected=True)
                    raise
                footprint_id = footprint.id
                await run_stats(squad_interest.finish_card_post, attempt, message_id=footprint_id)
            session['footprint'] = footprint_id
            await run_stats(squad_participants.save, footprint_id, config.GUILD_ID, destination.id, session['participants'])
            self.save()
            url = f'https://discord.com/channels/{config.GUILD_ID}/{destination.id}/{footprint_id}'
            await original.edit(content=f'本局已結束 · [查看足跡]({url})', embed=None,
                                view=None, allowed_mentions=discord.AllowedMentions.none())
            await run_stats(squad_interest.forget_card, original.id)
            if value:
                await run_stats(squad_interest.track_card, value['id'], destination.id, footprint_id, '')
                self.bot.add_view(FootprintView(self, value))
            await run_stats(squad_interest.link_footprint, session['id'], footprint_id)
            session['dirty'] = False

    async def menu_entry(self, interaction, *, page=0, replace=False):
        if interaction.guild_id!=config.GUILD_ID or interaction.user.bot:
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), '請喺原本伺服器使用。'),ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True,thinking=True)
        from features.squad_subscription_views import SubscriptionView
        rows=await run_stats(squad_interest.own_preferences,interaction.guild_id,interaction.user.id)
        view=SubscriptionView(self,interaction.guild_id,interaction.user.id,rows,page,member=interaction.user)
        kwargs = dict(embed=view.embed(), view=wording_view(interaction.user, view), allowed_mentions=discord.AllowedMentions.none())
        if replace:
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.followup.send(**kwargs, ephemeral=True)

    async def close_finished_notices(self):
        ready=getattr(self.bot,'is_ready',None)
        if callable(ready) and not ready():return
        for row in await run_stats(squad_interest.closing_notices):
            context=row['context']
            if row['guild_id']!=config.GUILD_ID or context.get('guild')!=config.GUILD_ID:
                continue
            channel=self.bot.get_channel(context.get('channel'))
            if channel is None:
                await run_stats(squad_interest.notice_close_failed,row)
                continue
            try:
                message=await channel.fetch_message(row['message_id'])
                url=f"https://discord.com/channels/{context['guild']}/{context['channel']}/{context['card']}"
                original_url=f"https://discord.com/channels/{context['guild']}/{context['channel']}/{context.get('original_card',context['card'])}"
                if message.author.id!=self.bot.user.id or not any(link in message.content for link in (url, original_url)):
                    log.warning('Refused to close mismatched squad notice: message=%s',row['message_id'])
                    await run_stats(squad_interest.notice_close_failed,row)
                    continue
                if callable(ready) and not ready():return
                await message.edit(content=f'本局已結束 · [查看足跡]({url})',
                    view=None,allowed_mentions=discord.AllowedMentions.none())
                await run_stats(squad_interest.forget_card,message.id)
                await run_stats(squad_interest.notice_closed,row)
            except discord.NotFound:
                await run_stats(squad_interest.forget_card,row['message_id'])
                await run_stats(squad_interest.notice_closed,row)
            except discord.HTTPException:
                log.exception('Could not close ended squad notice: message=%s',row['message_id'])
                await run_stats(squad_interest.notice_close_failed,row)

    @commands.Cog.listener()
    async def on_disconnect(self):
        async with self.lock:
            for session in self.state['sessions'].values():
                session.pop('empty_since', None)
                if not session.get('message'):
                    session['qualified']=None
            self.save()

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
                legacy = squad_participants.compact_legacy(embed)
                if legacy:
                    await run_stats(squad_participants.preserve_legacy, message.id, value['guild_id'], destination.id, legacy)
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
                async with shared_async_lock('subscription-consent',guild.id,value['id']):
                    revision=await run_stats(squad_interest.claim_delivery,session['id'],value['id'],batch_id)
                    if not revision:
                        continue
                    batch=await run_stats(squad_interest.delivery_users,session['id'],value['id'],batch_id,revision)
                    present={m.id for m in humans(channel)}
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
                    ready=getattr(self.bot,'is_ready',None)
                    if callable(ready) and not ready():
                        await run_stats(squad_interest.finish_delivery,session['id'],value['id'],batch_id,retry=True,expected_revision=revision)
                        return
                    try:
                        message=await destination.send(
                            f"{mentions}｜🎮 **{label}** 開局了！[查看召人卡]({url})",
                            suppress_embeds=True,
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
        ready = getattr(self.bot,'is_ready',None)
        if callable(ready) and not ready():
            return
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
                if session and session.get('id'):
                    latest=await run_stats(squad_interest.latest_card_post,session['id'])
                    if latest and latest['state']=='sent' and latest['message_id']:
                        session['message']=latest['message_id']
                if not members or (session and session.get('ended') is not None):
                    if session:
                        if channel is not None and session.get('message') and session.get('ended') is None:
                            session.setdefault('empty_since', now)
                            self.save()
                            if now - session['empty_since'] < 30:
                                continue
                        session.setdefault("ended", now)
                        self.save()  # Persist terminal state before any awaited finalization.
                        await run_stats(squad_interest.end_session,session['id'])
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
                session.pop('empty_since', None)
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
                await self.close_finished_notices()
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
            session.pop('empty_since', None)
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

    async def test_entry(self, interaction: discord.Interaction):
        destination = interaction.channel
        category = getattr(destination, 'category', None)
        if (interaction.guild_id != config.GUILD_ID or not is_server_admin(interaction.user)
                or not isinstance(destination, discord.TextChannel) or category is None
                or '測試' not in category.name):
            await interaction.response.send_message('請在功能測試區的文字頻道使用。', ephemeral=True)
            return
        voice = next((c for c in category.voice_channels if not humans(c)), None)
        if voice is None:
            await interaction.response.send_message('測試區需要一個沒有成員的語音頻道。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = time.time()
        session = dict(id='test-' + uuid.uuid4().hex, started=now-90, destination=destination.id,
                       participants={'test-a': '測試玩家 A', 'test-b': '測試玩家 B'},
                       game='測試遊戲', mode='卡片流程測試', profile='other')
        self.interest_baseline.add(session['id'])  # Never notify real subscribers.
        async with self.lock:
            try:
                await self.render(voice, session)
                original = await destination.fetch_message(session['message'])
                original_url = original.jump_url
                notice = await destination.send(f'【測試】開局提醒 · [查看召人卡]({original_url})',
                    suppress_embeds=True, allowed_mentions=discord.AllowedMentions.none())
                await destination.send('【測試】這則訊息模擬中途聊天，足跡卡應出現在它之後。',
                    allowed_mentions=discord.AllowedMentions.none())
                session['ended'] = now
                await self.render(voice, session, ended=True)
                footprint_id = session['footprint']
                # Retry the production finalizer; the journal must reuse the same post.
                await self.render(voice, session, ended=True)
                assert session['footprint'] == footprint_id
                footprint = await destination.fetch_message(footprint_id)
                await notice.edit(content=f'【測試】本局已結束 · [查看足跡]({footprint.jump_url})',
                    view=None, allowed_mentions=discord.AllowedMentions.none())
                original = await destination.fetch_message(original.id)
                assert not original.embeds and not original.components
                assert footprint.jump_url in original.content
                assert footprint.embeds and len([c for row in footprint.components for c in row.children]) == 5
                assert footprint.id > notice.id
                assert not notice.components and not original.mentions and not footprint.mentions
                await interaction.followup.send(
                    f'測試通過：[查看足跡]({footprint.jump_url})\n舊卡已收起操作；新卡位於聊天之後；重試沒有重發。\n使用模擬參與資料，未測真人進出語音。',
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                log.exception('Squad test incomplete: session=%s', session['id'])
                await interaction.followup.send('測試未完成，請保留現有卡片供核對。', ephemeral=True)
            finally:
                self.interest_baseline.discard(session['id'])

    @app_commands.command(name='squad_recover', description='核對並連結發送結果不明嘅現有召人卡')
    @app_commands.guild_only()
    @app_commands.check(lambda i: is_server_admin(i.user))
    async def squad_recover(self, interaction: discord.Interaction, channel: discord.VoiceChannel, message_id: str):
        if interaction.guild_id!=config.GUILD_ID or not is_server_admin(interaction.user) or not message_id.isdigit():
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), '請喺本伺服器提供現有訊息 ID。'),ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True,thinking=True)
        async with self.lock:
            session=self.state['sessions'].get(str(channel.id))
            post=await run_stats(squad_interest.uncertain_card,session['id']) if session else None
            if not post or not humans(channel):
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), '未有可核對嘅進行中發卡紀錄。'),ephemeral=True);return
            destination=self.bot.get_channel(post['destination'])
            try:
                message=await destination.fetch_message(int(message_id))
            except (discord.HTTPException,AttributeError):
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), '讀取唔到指定訊息，紀錄保持待查。'),ephemeral=True);return
            join_url=f'https://discord.com/channels/{config.GUILD_ID}/{channel.id}'
            components=[c for row in message.components for c in row.children]
            links=[getattr(c,'url',None) for c in components]
            controls=[getattr(c,'custom_id',None) for c in components]
            if not message.embeds or f"squad:{session['id']}" not in controls or message.author.id!=self.bot.user.id or join_url not in links or message.created_at.timestamp()<post['stamp']-5:
                await interaction.followup.send(wording_text(getattr(interaction, "user", None), '訊息作者、語音連結或時間唔吻合，紀錄保持待查。'),ephemeral=True);return
            await run_stats(squad_interest.finish_card_post,post['attempt'],message_id=message.id)
            session['message']=message.id
            self.interest_baseline.add(session['id'])
            self.save()
            await self.render(channel,session)
        await interaction.followup.send('已連結現有召人卡；沒有重發卡片或補 tag。',ephemeral=True)

    @app_commands.command(name="squad_setup", description="設定自動組隊卡：一人留滿30秒後發召人卡")
    @app_commands.guild_only()
    @app_commands.check(lambda i: is_server_admin(i.user))
    async def squad_setup(self, interaction: discord.Interaction,
                          category: discord.CategoryChannel, destination: discord.TextChannel):
        permissions = destination.permissions_for(interaction.guild.me)
        if not all((permissions.view_channel, permissions.send_messages,
                    permissions.embed_links, permissions.read_message_history)):
            await interaction.response.send_message(wording_text(getattr(interaction, "user", None), "Bot 喺狀態卡頻道需要查看、發訊息、嵌入連結及讀取歷史權限。"), ephemeral=True)
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
            'loop={0}; error={1}\n{2}\n已設定：監察 {3}；組隊卡發到 {4}{5}'.format(loop_status, self.last_error, diagnostic_text, category.name, destination.mention, wording_text(getattr(interaction, 'user', None), '。一人以上連續30秒出卡；散 band 轉足跡。')), ephemeral=True)


async def setup(bot):
    await bot.add_cog(SquadCards(bot), guild=TARGET)
