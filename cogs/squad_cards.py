"""Voice recruitment cards. Configure with /squad_setup; no automatic role pings."""
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

log = logging.getLogger(__name__)
TARGET = discord.Object(id=config.GUILD_ID)


def humans(channel):
    return [m for m in channel.members if not m.bot]


class Details(discord.ui.Modal, title="組隊狀態"):
    game = discord.ui.TextInput(label="玩緊乜？", max_length=100)
    missing = discord.ui.TextInput(label="仲缺幾人？（0 = 齊人）", max_length=2)

    def __init__(self, cog, key, session):
        super().__init__()
        self.cog, self.key, self.session = cog, key, session
        self.game.default = session.get("game", "")
        self.missing.default = str(session.get("missing", 1))

    async def on_submit(self, interaction):
        value = str(self.missing.value).strip()
        if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 99:
            await interaction.response.send_message("請填 0–99；0 代表齊人。", ephemeral=True)
            return
        if not str(self.game.value).strip():
            await interaction.response.send_message("請填遊戲名稱。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock:
            session = self.cog.state["sessions"].get(self.key)
            channel = self.cog.bot.get_channel(int(self.key))
            if session is not self.session or not channel or interaction.user not in humans(channel):
                await interaction.followup.send("呢場已結束，或者你已離開個 call。", ephemeral=True)
                return
            session.update(game=str(self.game.value).strip(), missing=int(value))
            self.cog.save()
            await self.cog.render(channel, session)
        await interaction.followup.send("已更新組隊狀態。", ephemeral=True)


class CardView(discord.ui.View):
    def __init__(self, cog, key, session):
        super().__init__(timeout=None)
        self.cog, self.key, self.session = cog, key, session
        button = discord.ui.Button(label="填寫／更新招募", style=discord.ButtonStyle.primary,
                                   custom_id=f"squad:{session['id']}")
        button.callback = self.edit
        self.add_item(button)

    async def edit(self, interaction):
        session = self.cog.state["sessions"].get(self.key)
        channel = self.cog.bot.get_channel(int(self.key))
        if session is not self.session or not channel or interaction.user not in humans(channel):
            await interaction.response.send_message("只限呢個 call 嘅在場成員修改。", ephemeral=True)
            return
        await interaction.response.send_modal(Details(self.cog, self.key, session))


class SquadCards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = os.getenv("SQUAD_CARDS_PATH", "/data/squad_cards.json")
        self.state = load_json_object(self.path, lambda: {"settings": {}, "sessions": {}})
        self.lock = asyncio.Lock()
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
        game = discord.utils.escape_markdown(session.get("game", "未填寫"))
        title = "👣 開團足跡" if ended else ("🎮 在 call 玩緊" if "game" in session else "👋 仲缺幾人？")
        embed = discord.Embed(title=title, colour=0x808080 if ended else 0x57F287)
        embed.add_field(name="玩緊", value=game, inline=False)
        embed.add_field(name="一齊玩過" if ended else f"在 call · {len(members)} 人", value=roster[:1024], inline=False)
        if ended:
            embed.add_field(name="時間", value=f"<t:{int(session['started'])}:t> – <t:{int(session['ended'])}:t>")
        else:
            missing = session.get("missing")
            embed.add_field(name="招募", value="等在場成員填寫" if missing is None else (f"缺 {missing} 人" if missing else "齊人啦"))
            embed.add_field(name="語音頻道", value=f"<#{channel.id}>")
        view = None if ended else CardView(self, str(channel.id), session)
        kwargs = dict(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        if session.get("message"):
            try:
                message = await destination.fetch_message(session["message"])
                await message.edit(**kwargs)
                return
            except discord.NotFound:
                if ended:
                    return  # Do not repost a deliberately deleted card as a footprint.
        message = await destination.send(**kwargs)
        session["message"] = message.id
        self.save()

    async def reconcile(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        settings = self.state["settings"]
        if not guild or not settings:
            return
        now = time.time()
        channels = {str(c.id): c for c in guild.voice_channels
                    if c.category_id == settings["category"] and c.id != guild.afk_channel_id}
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
                if len(members) < 2:
                    continue
                session = dict(id=uuid.uuid4().hex, started=now, qualified=now,
                               participants={}, destination=settings["destination"])
                self.state["sessions"][key] = session
            before = dict(session["participants"])
            session["participants"].update({str(m.id): m.display_name for m in members})
            roster = sorted(m.id for m in members)
            changed = roster != session.get("roster")
            session["roster"] = roster
            if not session.get("message"):
                if len(members) < 2:
                    session["qualified"] = None
                elif session.get("qualified") is None:
                    session["qualified"] = now
                elif now - session["qualified"] >= 600:
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
        except Exception:
            log.exception("Failed to reconcile squad cards; retrying next tick")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        # Unpublished timers restart: offline time cannot establish continuous presence.
        for session in self.state["sessions"].values():
            if not session.get("message"):
                session["qualified"] = None
        self.save()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id != config.GUILD_ID or before.channel == after.channel:
            return
        try:
            async with self.lock:
                await self.reconcile()
        except Exception:
            log.exception("Failed to update squad card after voice change")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if str(channel.id) in self.state["sessions"]:
            async with self.lock:
                await self.reconcile()

    @app_commands.command(name="squad_setup", description="設定自動組隊卡：兩人同場10分鐘後詢問招募")
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
            self.state["settings"] = dict(category=category.id, destination=destination.id)
            self.save()
        await interaction.response.send_message(
            f"已設定：監察 {category.name}；組隊卡發到 {destination.mention}。兩人以上連續10分鐘先問；散 band 轉足跡。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SquadCards(bot), guild=TARGET)
