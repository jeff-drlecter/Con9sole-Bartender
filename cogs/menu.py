from __future__ import annotations

import inspect
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import config

MENU_COLOR = 0x2B2D31
COOLDOWN_SECONDS = 3.0

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BARTENDER_IMAGE = ASSETS_DIR / "bartender.png"
BARTENDER_ATTACHMENT_NAME = "bartender.png"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATS_DB = DATA_DIR / "community_stats.sqlite3"
HK_TZ = timezone(timedelta(hours=8))

COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")
INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://threads.net/con9sole")

INVITE_CHANNEL_ID = getattr(config, "INVITE_CHANNEL_ID", None)
INVITE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
INVITE_MAX_USES = 10
INVITE_COOLDOWN_SECONDS = 10 * 60

RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = set(getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper", "helpers"]))

USER_MENU_COOLDOWNS: dict[int, float] = {}
USER_INVITE_COOLDOWNS: dict[int, float] = {}

FEATURE_LABELS: dict[str, str] = {
    "menu": "Menu",
    "home_menu": "Bartender Home",
    "team": "組隊",
    "tempvc": "小隊 call",
    "cheers": "打氣",
    "drink": "調酒",
    "ig": "IG Page",
    "threads": "Threads Page",
    "invite": "生成邀請碼",
    "help": "幫助",
    "admin_tool": "Admin Tool",
    "admin_stats": "Admin Stats",
    "admin_reload": "Reload",
    "admin_role": "Role Tools",
    "admin_ping": "Ping",
    "admin_vc_teardown": "VC Teardown",
    "mention_menu": "Mention Menu",
}

FEATURE_EMOJIS: dict[str, str] = {
    "menu": "⬅️",
    "home_menu": "🍸",
    "team": "👥",
    "tempvc": "🎧",
    "cheers": "🎉",
    "drink": "🍹",
    "ig": "📸",
    "threads": "🧵",
    "invite": "🔗",
    "help": "ℹ️",
    "admin_tool": "🛠️",
    "admin_stats": "📊",
    "admin_reload": "🔄",
    "admin_role": "🎭",
    "admin_ping": "🏓",
    "admin_vc_teardown": "🧹",
    "mention_menu": "💬",
}


def init_stats_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS command_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature TEXT NOT NULL,
                user_id INTEGER,
                guild_id INTEGER,
                used_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_command_usage_feature_used_at
            ON command_usage(feature, used_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_command_usage_guild_used_at
            ON command_usage(guild_id, used_at)
            """
        )


def record_usage_sync(feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
    try:
        init_stats_db()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(STATS_DB) as conn:
            conn.execute(
                """
                INSERT INTO command_usage (feature, user_id, guild_id, used_at)
                VALUES (?, ?, ?, ?)
                """,
                (feature.lower().strip(), user_id, guild_id, now),
            )
    except Exception:
        pass


def get_stats(guild_id: int | None, days: int | None = None) -> list[tuple[str, int]]:
    init_stats_db()
    params: list[object] = []
    where: list[str] = []

    if guild_id is not None:
        where.append("guild_id = ?")
        params.append(guild_id)

    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where.append("used_at >= ?")
        params.append(since.isoformat())

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    with sqlite3.connect(STATS_DB) as conn:
        rows = conn.execute(
            f"""
            SELECT feature, COUNT(*) AS total
            FROM command_usage
            {where_sql}
            GROUP BY feature
            ORDER BY total DESC
            """,
            params,
        ).fetchall()

    return [(str(row[0]), int(row[1])) for row in rows]


def get_total_usage(guild_id: int | None, days: int | None = None) -> int:
    init_stats_db()
    params: list[object] = []
    where: list[str] = []

    if guild_id is not None:
        where.append("guild_id = ?")
        params.append(guild_id)

    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where.append("used_at >= ?")
        params.append(since.isoformat())

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    with sqlite3.connect(STATS_DB) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM command_usage {where_sql}",
            params,
        ).fetchone()

    return int(row[0]) if row else 0


def format_stats_block(stats: list[tuple[str, int]]) -> str:
    if not stats:
        return "暫時未有紀錄。"

    lines: list[str] = []
    for feature, total in stats:
        emoji = FEATURE_EMOJIS.get(feature, "🔹")
        label = FEATURE_LABELS.get(feature, feature)
        lines.append(f"{emoji} **{label}**：`{total}` 次")
    return "\n".join(lines)


def can_use_admin(member: discord.Member | discord.User) -> bool:
    if not isinstance(member, discord.Member):
        return False

    if member.guild_permissions.manage_guild:
        return True

    for role in member.roles:
        if role.id in HELPER_ROLE_IDS:
            return True
        if role.name in HELPER_ROLE_NAMES:
            return True

    return False


can_use_admin_stats = can_use_admin


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


def _apply_bartender_thumbnail(embed: discord.Embed) -> None:
    if BARTENDER_IMAGE.exists():
        embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")


def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "👥 **組隊**｜召集隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎉 **打氣**｜為大家補充能量\n"
            "🍹 **調酒**｜酒保特選\n\n"
            "⬅️ **Menu**｜進入吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text=f"Con9sole Bartender｜{user.display_name}，今晚由我為你服務。")
    return embed


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_home_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Bartender Home",
        description=(
            f"**{COMMUNITY_NAME} 吧枱主頁**\n\n"
            "👥 **組隊** — 召集隊友\n"
            "🎧 **小隊 call** — 建立臨時語音房\n"
            "🎉 **打氣** — 為大家補充能量\n"
            "🍹 **調酒** — 酒保特選\n"
            "📸 **IG Page** — 官方 Instagram\n"
            "🧵 **Threads Page** — 官方 Threads\n"
            "🔗 **生成邀請碼** — 7 日 / 10 次公開邀請連結\n"
            "ℹ️ **幫助** — 使用說明\n"
            "🛠️ **Admin Tool** — 管理工具"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜選好服務後，直接撳下面按鈕。")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description=(
            "**Bartender 使用說明**\n\n"
            "👥 **組隊**｜發起組隊 / 招募隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🍹 **調酒**｜抽一杯酒保特選飲品\n"
            "📸 **IG Page / Threads Page**｜查看官方社交平台\n"
            "🔗 **生成邀請碼**｜7 日有效、最多 10 次使用，每人 10 分鐘一次\n"
            "🛠️ **Admin Tool**｜Admin / helpers 專用管理工具"
        ),
        color=MENU_COLOR,
    )
    _apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Admin Tool",
        description=(
            "**管理工具**\n\n"
            "📊 **Stats** — Community Bot 使用數據\n"
            "🔄 **Reload** — 直接重載所有 cogs\n"
            "🎭 **Role Tools** — 角色管理指令入口\n"
            "🏓 **Ping** — Bot latency\n"
            "🧹 **VC Teardown** — 指令入口 `/vc_teardown`\n\n"
            "⬅️ **Menu** — 返回吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Admin 工具只限授權成員使用。")
    return embed


def build_role_tools_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🎭 Role Tools",
        description=(
            "**目前可用角色管理指令**\n\n"
            "`/role_grant` — 加上某個角色\n"
            "`/role_revoke` — 移除某個角色\n"
            "`/role_list` — 查看成員角色\n"
            "`/role_channel_new` — Clone versioned channel 並建立新版本 role"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def _safe_message_kwargs(
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    file: discord.File | None = None,
    ephemeral: bool | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file
    if ephemeral is not None:
        kwargs["ephemeral"] = ephemeral
    return kwargs


async def send_or_followup(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
    file: discord.File | None = None,
) -> None:
    kwargs = _safe_message_kwargs(
        content=content,
        embed=embed,
        embeds=embeds,
        view=view,
        ephemeral=ephemeral,
        file=file,
    )

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


def get_retry_after(user_id: int) -> float:
    last_used = USER_MENU_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cooldown(user_id: int) -> None:
    USER_MENU_COOLDOWNS[user_id] = time.time()


def get_invite_retry_after(user_id: int) -> float:
    last_used = USER_INVITE_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = INVITE_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_invite_cooldown(user_id: int) -> None:
    USER_INVITE_COOLDOWNS[user_id] = time.time()


def format_retry_seconds(seconds: float) -> str:
    seconds_int = max(0, int(seconds + 0.999))
    minutes, sec = divmod(seconds_int, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再撳。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def _record(self, interaction: discord.Interaction, feature: str) -> None:
        record_usage_sync(feature, interaction.user.id, interaction.guild_id)

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        await send_or_followup(
            interaction,
            content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以使用 Admin Tool。",
            ephemeral=True,
        )
        return False

    async def _call_cog_method(
        self,
        interaction: discord.Interaction,
        *,
        feature: str,
        cog_name: str,
        method_names: list[str],
        missing_message: str,
    ) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, feature)

        target_cog = interaction.client.get_cog(cog_name)
        if not target_cog:
            await send_or_followup(interaction, content=missing_message, ephemeral=True)
            return

        method: Callable[..., Awaitable[None]] | None = None
        for method_name in method_names:
            candidate = getattr(target_cog, method_name, None)
            if candidate and inspect.iscoroutinefunction(candidate):
                method = candidate
                break

        if method is None:
            await send_or_followup(interaction, content=missing_message, ephemeral=True)
            return

        try:
            await method(interaction)
        except TypeError:
            try:
                await method(interaction, None)
            except TypeError:
                await method(interaction, to=None)
        except discord.InteractionResponded:
            pass
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 執行功能時出錯：{type(exc).__name__}",
                ephemeral=True,
            )

    async def _send_home_menu(self, interaction: discord.Interaction) -> None:
        await self._record(interaction, "home_menu")
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def _send_quick_bar(self, interaction: discord.Interaction) -> None:
        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def _create_invite_link(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not can_use_admin(interaction.user):
            retry_after = get_invite_retry_after(interaction.user.id)
            if retry_after > 0:
                await send_or_followup(
                    interaction,
                    content=f"⏳ 你啱啱已經產生過邀請碼，請等 {format_retry_seconds(retry_after)} 後再試。",
                    ephemeral=True,
                )
                return

        await self._record(interaction, "invite")

        if INVITE_CHANNEL_ID is None:
            await send_or_followup(
                interaction,
                content=(
                    "⚠️ 未設定邀請入口頻道。\n"
                    "請先喺 `config.py` 加：\n"
                    "`INVITE_CHANNEL_ID: int = 你的channel_id`"
                ),
                ephemeral=True,
            )
            return

        channel = interaction.client.get_channel(int(INVITE_CHANNEL_ID))
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(int(INVITE_CHANNEL_ID))
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            await send_or_followup(
                interaction,
                content="⚠️ 搵唔到指定邀請入口頻道，請檢查 `INVITE_CHANNEL_ID`。",
                ephemeral=True,
            )
            return

        try:
            invite = await channel.create_invite(
                max_age=INVITE_MAX_AGE_SECONDS,
                max_uses=INVITE_MAX_USES,
                unique=True,
                temporary=False,
                reason=f"Invite generated by {interaction.user} ({interaction.user.id}) via Bartender menu",
            )
        except discord.Forbidden:
            await send_or_followup(
                interaction,
                content=f"❌ Bartender 無權喺 {channel.mention} 建立 invite，請開啟 `Create Instant Invite` 權限。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 建立邀請碼失敗：{type(exc).__name__}",
                ephemeral=True,
            )
            return

        if not can_use_admin(interaction.user):
            touch_invite_cooldown(interaction.user.id)

        public_message = (
            "🔗 **邀請碼已生成：**\n"
            f"{invite.url}\n\n"
            "有效期：`7 日`\n"
            "使用次數：`最多 10 次`\n"
            "成員類型：`非 temporary member`\n\n"
            "大家可以 copy 呢條 link share 畀朋友加入社群。"
        )

        try:
            if interaction.channel is None:
                raise RuntimeError("No interaction channel")
            await interaction.channel.send(public_message)
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 邀請碼已建立，但公開發送失敗：{type(exc).__name__}\n{invite.url}",
                ephemeral=True,
            )
            return

        await send_or_followup(
            interaction,
            content="✅ 邀請碼已公開發送到此頻道。",
            ephemeral=True,
        )


class QuickBarView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:quick:home", row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)

    @discord.ui.button(label="組隊", emoji="👥", style=discord.ButtonStyle.primary, custom_id="bartender:quick:team", row=0)
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="team",
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(label="小隊 call", emoji="🎧", style=discord.ButtonStyle.primary, custom_id="bartender:quick:tempvc", row=0)
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="tempvc",
            cog_name="TempVC",
            method_names=["create_temp_vc_from_menu", "send_control_panel", "tempvc_panel", "tempvc", "panel"],
            missing_message="❌ 搵唔到小隊房控制面板入口。",
        )

    @discord.ui.button(label="", emoji="🎉", style=discord.ButtonStyle.success, custom_id="bartender:quick:cheers", row=0)
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣功能未載入。",
        )

    @discord.ui.button(label="", emoji="🍹", style=discord.ButtonStyle.success, custom_id="bartender:quick:drink", row=0)
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="drink",
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )


class HomeMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

        self.add_item(discord.ui.Button(label="IG Page", emoji="📸", style=discord.ButtonStyle.link, url=INSTAGRAM_URL, row=2))
        self.add_item(discord.ui.Button(label="Threads Page", emoji="🧵", style=discord.ButtonStyle.link, url=THREADS_URL, row=2))

        if RULES_URL:
            self.add_item(discord.ui.Button(label="Rules", emoji="🛡️", style=discord.ButtonStyle.link, url=RULES_URL, row=4))

        if HELP_URL:
            self.add_item(discord.ui.Button(label="Help Channel", emoji="❓", style=discord.ButtonStyle.link, url=HELP_URL, row=4))

    @discord.ui.button(label="組隊", emoji="👥", style=discord.ButtonStyle.primary, custom_id="bartender:home:team", row=0)
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="team",
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(label="小隊 call", emoji="🎧", style=discord.ButtonStyle.primary, custom_id="bartender:home:tempvc", row=0)
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="tempvc",
            cog_name="TempVC",
            method_names=["create_temp_vc_from_menu", "send_control_panel", "tempvc_panel", "tempvc", "panel"],
            missing_message="❌ 搵唔到小隊房控制面板入口。",
        )

    @discord.ui.button(label="打氣", emoji="🎉", style=discord.ButtonStyle.success, custom_id="bartender:home:cheers", row=1)
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣功能未載入。",
        )

    @discord.ui.button(label="調酒", emoji="🍹", style=discord.ButtonStyle.success, custom_id="bartender:home:drink", row=1)
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="drink",
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )

    @discord.ui.button(label="生成邀請碼", emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="bartender:home:invite", row=3)
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._create_invite_link(interaction)

    @discord.ui.button(label="幫助", emoji="ℹ️", style=discord.ButtonStyle.secondary, custom_id="bartender:home:help", row=3)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "help")
        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(label="Admin Tool", emoji="🛠️", style=discord.ButtonStyle.danger, custom_id="bartender:home:admin_tool", row=3)
    async def admin_tool_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "admin_tool")

        if not await self._require_admin(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self.cog),
            ephemeral=True,
        )


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:help:home", row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)


class RoleToolsView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(label="Admin Tool", emoji="🛠️", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:admin", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:home", row=0)
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)


class AdminToolView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.primary, custom_id="bartender:admin:stats", row=0)
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_stats")
        stats = get_stats(interaction.guild_id, days=7)
        total = get_total_usage(interaction.guild_id, days=7)

        top_feature = "暫時未有"
        if stats:
            top_key = stats[0][0]
            top_feature = f"{FEATURE_EMOJIS.get(top_key, '🔹')} {FEATURE_LABELS.get(top_key, top_key)}"

        now_hk = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")
        embed = discord.Embed(
            title="📊 Community Bot Insights｜本週",
            description=(
                f"**總使用次數：** `{total}`\n"
                f"**最活躍功能：** {top_feature}\n"
                f"**更新時間：** `{now_hk}`"
            ),
            color=MENU_COLOR,
        )
        embed.add_field(name="功能使用分佈", value=format_stats_block(stats), inline=False)
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")

        await send_or_followup(interaction, embed=embed, view=AdminToolView(self.cog), ephemeral=True)

    @discord.ui.button(label="Reload", emoji="🔄", style=discord.ButtonStyle.primary, custom_id="bartender:admin:reload", row=0)
    async def reload_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_reload")

        reload_cog = interaction.client.get_cog("Reload")
        if reload_cog is None or not hasattr(reload_cog, "_reload_one"):
            await send_or_followup(
                interaction,
                content="❌ Reload cog 未載入，請先用 `/reload reload` 或重啟 Bot。",
                ephemeral=True,
            )
            return

        try:
            from cogs.reload import _list_cogs_package  # type: ignore

            ok_list: list[str] = []
            fail_list: list[str] = []

            for name in _list_cogs_package():
                ext = f"cogs.{name}"
                try:
                    result = reload_cog._reload_one(ext)  # type: ignore[attr-defined]
                    if inspect.isawaitable(result):
                        ok, fail = await result
                    else:
                        ok, fail = result
                except Exception as exc:
                    ok = False
                    fail = f"`{type(exc).__name__}`: {exc}"

                if ok:
                    ok_list.append(name)
                else:
                    fail_list.append(f"{name} -> {fail}")

            msg: list[str] = []
            if ok_list:
                msg.append("✅ 已重載： " + ", ".join(ok_list))
            if fail_list:
                msg.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

            await send_or_followup(
                interaction,
                content="\n".join(msg) if msg else "⚠️ 無可重載的 cogs。",
                ephemeral=True,
            )

        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ Reload button 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )

    @discord.ui.button(label="Role Tools", emoji="🎭", style=discord.ButtonStyle.secondary, custom_id="bartender:admin:role_tools", row=1)
    async def role_tools_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_role")
        await send_or_followup(
            interaction,
            embed=build_role_tools_embed(interaction.user),
            view=RoleToolsView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Ping", emoji="🏓", style=discord.ButtonStyle.secondary, custom_id="bartender:admin:ping", row=1)
    async def ping_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_ping")
        latency_ms = round(interaction.client.latency * 1000)
        await send_or_followup(interaction, content=f"🏓 Pong! `{latency_ms} ms`", ephemeral=True)

    @discord.ui.button(label="VC Teardown", emoji="🧹", style=discord.ButtonStyle.danger, custom_id="bartender:admin:vc_teardown", row=1)
    async def vc_teardown_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_vc_teardown")

        tempvc_cog = interaction.client.get_cog("TempVC")
        if tempvc_cog and hasattr(tempvc_cog, "teardown_temp_vc_from_menu"):
            try:
                result = tempvc_cog.teardown_temp_vc_from_menu(interaction)  # type: ignore[attr-defined]
                if inspect.isawaitable(result):
                    await result
                return
            except Exception as exc:
                await send_or_followup(
                    interaction,
                    content=f"❌ VC Teardown 執行失敗：`{type(exc).__name__}`：{exc}",
                    ephemeral=True,
                )
                return

        await send_or_followup(
            interaction,
            content="🧹 **VC Teardown 指令入口**\n\n請使用 slash command：`/vc_teardown`。",
            ephemeral=True,
        )

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:admin:home", row=2)
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)


MainMenuView = QuickBarView
CommunityHubView = HomeMenuView
MenuEntryView = QuickBarView


def build_menu_entry_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)


def build_full_menu_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)


class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False
        init_stats_db()

    async def _enforce_command_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再用 /menu。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def record_usage(self, feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
        record_usage_sync(feature, user_id, guild_id)

    async def open_main_menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def send_mention_menu(self, message: discord.Message) -> None:
        if not can_use_admin(message.author):
            retry_after = get_retry_after(message.author.id)
            if retry_after > 0:
                return
            touch_cooldown(message.author.id)

        record_usage_sync("mention_menu", message.author.id, message.guild.id if message.guild else None)

        try:
            kwargs = _safe_message_kwargs(
                embed=build_quick_bar_embed(message.author),
                view=QuickBarView(self),
                file=build_menu_file(),
            )
            kwargs["mention_author"] = False
            await message.reply(**kwargs)
        except discord.HTTPException:
            pass

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(QuickBarView(self))
        self.bot.add_view(HomeMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self.bot.add_view(AdminToolView(self))
        self.bot.add_view(RoleToolsView(self))
        self._views_registered = True

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 快捷吧枱")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=False,
            file=build_menu_file(),
        )

    @app_commands.command(name="community_hub", description="顯示 Con9sole Bartender 主頁")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    @app_commands.command(name="admin_stats", description="查看 Community Bot 使用數據")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(scope="查看範圍：today / week / all")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="今日", value="today"),
            app_commands.Choice(name="本週", value="week"),
            app_commands.Choice(name="全部", value="all"),
        ]
    )
    async def admin_stats(self, interaction: discord.Interaction, scope: app_commands.Choice[str]) -> None:
        if not can_use_admin(interaction.user):
            await send_or_followup(
                interaction,
                content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
                ephemeral=True,
            )
            return

        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)

        if scope.value == "today":
            days: int | None = 1
            title_scope = "今日"
        elif scope.value == "week":
            days = 7
            title_scope = "本週"
        else:
            days = None
            title_scope = "全部"

        stats = get_stats(interaction.guild_id, days)
        total = get_total_usage(interaction.guild_id, days)

        top_feature = "暫時未有"
        if stats:
            top_key = stats[0][0]
            top_feature = f"{FEATURE_EMOJIS.get(top_key, '🔹')} {FEATURE_LABELS.get(top_key, top_key)}"

        now_hk = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")
        embed = discord.Embed(
            title=f"📊 Community Bot Insights｜{title_scope}",
            description=(
                f"**總使用次數：** `{total}`\n"
                f"**最活躍功能：** {top_feature}\n"
                f"**更新時間：** `{now_hk}`"
            ),
            color=MENU_COLOR,
        )
        embed.add_field(name="功能使用分佈", value=format_stats_block(stats), inline=False)
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")

        await send_or_followup(interaction, embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
