from __future__ import annotations

import inspect
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

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
LEVEL_CHECK_CHANNEL_ID = getattr(config, "LEVEL_CHECK_CHANNEL_ID", None)

# 可選：如果你有 rules/help channel link，可以喺 config.py 加：
# RULES_URL = "https://discord.com/channels/.../..."
# HELP_URL = "https://discord.com/channels/.../..."
RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

# /admin_stats / Admin Tool 權限：Manage Server 或 Helper role 都可以使用
# 可選 config.py：
# HELPER_ROLE_IDS = [123456789012345678]
# HELPER_ROLE_NAMES = ["helpers"]
HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = set(getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper", "helpers"]))

# 全局 user cooldown：同一個 user 撳任何 menu / submenu 按鈕都會共用 CD
USER_MENU_COOLDOWNS: dict[int, float] = {}

FEATURE_LABELS: dict[str, str] = {
    "menu": "Menu",
    "home_menu": "Bartender Home",
    "team": "組隊",
    "tempvc": "小隊 call",
    "cheers": "打氣",
    "drink": "調酒",
    "ig": "IG Page",
    "threads": "Threads Page",
    "level": "Level",
    "leaderboard": "Leaderboard",
    "help": "幫助",
    "admin_tool": "Admin Tool",
    "admin_stats": "Admin Stats",
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
    "level": "🏅",
    "leaderboard": "🏆",
    "help": "ℹ️",
    "admin_tool": "🛠️",
    "admin_stats": "📊",
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
    """輕量記錄功能使用次數。SQLite 寫入量好低，對 CPU/RAM 影響極細。"""
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
        # 統計失敗唔應該影響主功能
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

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

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

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

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
    """Manage Server 或 Helper role 都可以使用 Admin Tool / Admin Stats。"""
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


# Backward-compatible alias
can_use_admin_stats = can_use_admin


def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "吧枱已經準備好。\n"
            "你可以直接召集隊友、開小隊 call、來一點打氣，或者讓酒保為你調一杯。\n\n"
            "⬅️ **Menu**｜進入吧枱主頁查看更多功能"
        ),
        color=MENU_COLOR,
    )
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，今晚由我為你服務。")
    return embed


def build_home_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Bartender Home",
        description=(
            f"**這裡是 {COMMUNITY_NAME} 的吧枱主頁。**\n\n"
            "👥 **組隊** — 召集隊友\n"
            "🎧 **小隊 call** — 建立臨時語音房\n"
            "🎉 **打氣** — 為大家補充能量\n"
            "🍹 **調酒** — 酒保特選\n"
            "📸 **IG Page** — 官方 Instagram\n"
            "🧵 **Threads Page** — 官方 Threads\n"
            "🏅 **Level** — 嘗試透過 AmariBot 查詢等級\n"
            "🏆 **Leaderboard** — 嘗試透過 AmariBot 查看排行榜\n"
            "ℹ️ **幫助** — 查看使用說明\n"
            "🛠️ **Admin Tool** — 管理工具"
        ),
        color=MENU_COLOR,
    )
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，慢慢揀，我喺度等你。")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description="酒保已經準備好，以下是你可以使用的服務。",
        color=MENU_COLOR,
    )
    embed.add_field(name="👥 組隊", value="發起組隊 / 招募隊友。", inline=False)
    embed.add_field(name="🎧 小隊 call", value="建立臨時語音房。", inline=False)
    embed.add_field(name="🎉 打氣", value="送出隨機打氣內容。", inline=False)
    embed.add_field(name="🍹 調酒", value="抽一杯酒保特選飲品。", inline=False)
    embed.add_field(name="📸 IG Page / 🧵 Threads Page", value="查看 Con9sole 官方社交平台。", inline=False)
    embed.add_field(name="🏅 Level / 🏆 Leaderboard", value="嘗試喺指定頻道發出 AmariBot 查詢指令。", inline=False)
    embed.add_field(name="🛠️ Admin Tool", value="Admin / helpers 專用管理工具。", inline=False)
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，需要咩就撳相應按鈕。")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Admin Tool",
        description=(
            "管理用工具集中於此。\n\n"
            "📊 **Stats** — 查看 Community Bot 使用數據\n"
            "⬅️ **Menu** — 返回吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，Admin 工具只限授權成員使用。")
    return embed


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


async def send_or_followup(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
    file: discord.File | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
            file=file,
        )
    else:
        await interaction.response.send_message(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
            file=file,
        )


def get_retry_after(user_id: int) -> float:
    last_used = USER_MENU_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cooldown(user_id: int) -> None:
    USER_MENU_COOLDOWNS[user_id] = time.time()


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
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

    async def _send_amari_command(self, interaction: discord.Interaction, *, command_text: str, feature: str) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, feature)

        if LEVEL_CHECK_CHANNEL_ID is None:
            await send_or_followup(
                interaction,
                content=(
                    "⚠️ 未設定等級查詢頻道。\n"
                    "請先喺 `config.py` 加：\n"
                    "`LEVEL_CHECK_CHANNEL_ID: int = 你的channel_id`"
                ),
                ephemeral=True,
            )
            return

        channel = interaction.client.get_channel(int(LEVEL_CHECK_CHANNEL_ID))
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(int(LEVEL_CHECK_CHANNEL_ID))
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, discord.TextChannel):
            await send_or_followup(
                interaction,
                content="⚠️ 搵唔到指定等級查詢文字頻道，請檢查 `LEVEL_CHECK_CHANNEL_ID`。",
                ephemeral=True,
            )
            return

        try:
            await channel.send(command_text)
        except discord.Forbidden:
            await send_or_followup(
                interaction,
                content=f"❌ Bartender 無權喺 {channel.mention} 發訊息，請檢查頻道權限。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 發送 AmariBot 指令失敗：{type(exc).__name__}",
                ephemeral=True,
            )
            return

        await send_or_followup(
            interaction,
            content=(
                f"✅ 已嘗試喺 {channel.mention} 發出查詢指令：\n"
                f"`{command_text}`\n\n"
                "如果 AmariBot 支援 bot-to-bot 指令，結果會出現在該頻道。\n"
                "如果無反應，即代表 AmariBot 忽略其他 bot 發出嘅訊息。"
            ),
            ephemeral=True,
        )


class QuickBarView(BaseMenuView):
    """Layer 1：公開 Quick Bar。"""

    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="Menu",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:quick:home",
        row=0,
    )
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:quick:team",
        row=0,
    )
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="team",
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(
        label="小隊 call",
        emoji="🎧",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:quick:tempvc",
        row=0,
    )
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="tempvc",
            cog_name="TempVC",
            method_names=[
                "create_temp_vc_from_menu",
                "send_control_panel",
                "tempvc_panel",
                "tempvc",
                "panel",
            ],
            missing_message="❌ 搵唔到小隊房控制面板入口。",
        )

    @discord.ui.button(
        label=None,
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="bartender:quick:cheers",
        row=0,
    )
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣功能未載入。",
        )

    @discord.ui.button(
        label=None,
        emoji="🍹",
        style=discord.ButtonStyle.success,
        custom_id="bartender:quick:drink",
        row=0,
    )
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="drink",
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )


class HomeMenuView(BaseMenuView):
    """Layer 2：私人完整主頁。"""

    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

        self.add_item(
            discord.ui.Button(
                label="IG Page",
                emoji="📸",
                style=discord.ButtonStyle.link,
                url=INSTAGRAM_URL,
                row=2,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Threads Page",
                emoji="🧵",
                style=discord.ButtonStyle.link,
                url=THREADS_URL,
                row=2,
            )
        )

        if RULES_URL:
            self.add_item(
                discord.ui.Button(
                    label="Rules",
                    emoji="🛡️",
                    style=discord.ButtonStyle.link,
                    url=RULES_URL,
                    row=4,
                )
            )

        if HELP_URL:
            self.add_item(
                discord.ui.Button(
                    label="Help Channel",
                    emoji="❓",
                    style=discord.ButtonStyle.link,
                    url=HELP_URL,
                    row=4,
                )
            )

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:home:team",
        row=0,
    )
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="team",
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(
        label="小隊 call",
        emoji="🎧",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:home:tempvc",
        row=0,
    )
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="tempvc",
            cog_name="TempVC",
            method_names=[
                "create_temp_vc_from_menu",
                "send_control_panel",
                "tempvc_panel",
                "tempvc",
                "panel",
            ],
            missing_message="❌ 搵唔到小隊房控制面板入口。",
        )

    @discord.ui.button(
        label="打氣",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="bartender:home:cheers",
        row=1,
    )
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣功能未載入。",
        )

    @discord.ui.button(
        label="調酒",
        emoji="🍹",
        style=discord.ButtonStyle.success,
        custom_id="bartender:home:drink",
        row=1,
    )
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="drink",
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )

    @discord.ui.button(
        label="Level",
        emoji="🏅",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:home:level",
        row=3,
    )
    async def level_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._send_amari_command(
            interaction,
            command_text=f":?rank {interaction.user.mention}",
            feature="level",
        )

    @discord.ui.button(
        label="Leaderboard",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:home:leaderboard",
        row=3,
    )
    async def leaderboard_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._send_amari_command(
            interaction,
            command_text=":?leaderboard",
            feature="leaderboard",
        )

    @discord.ui.button(
        label="幫助",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:home:help",
        row=4,
    )
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

    @discord.ui.button(
        label="Admin Tool",
        emoji="🛠️",
        style=discord.ButtonStyle.danger,
        custom_id="bartender:home:admin_tool",
        row=4,
    )
    async def admin_tool_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "admin_tool")

        if not can_use_admin(interaction.user):
            await send_or_followup(
                interaction,
                content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以使用 Admin Tool。",
                ephemeral=True,
            )
            return

        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="Menu",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:help:home",
        row=0,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)


class AdminToolView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="Stats",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:admin:stats",
        row=0,
    )
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        if not can_use_admin(interaction.user):
            await send_or_followup(
                interaction,
                content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
                ephemeral=True,
            )
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
        embed.add_field(
            name="功能使用分佈",
            value=format_stats_block(stats),
            inline=False,
        )
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")

        await send_or_followup(
            interaction,
            embed=embed,
            view=AdminToolView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Menu",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:admin:home",
        row=0,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self._send_home_menu(interaction)


# Backward-compatible aliases / helpers for other cogs
MainMenuView = QuickBarView
CommunityHubView = HomeMenuView
MenuEntryView = QuickBarView


def build_menu_entry_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)


def build_full_menu_view(interaction: discord.Interaction) -> discord.ui.View | None:
    """畀 drink.py / cheers.py 用：抽完後回到 Layer 1 Quick Bar。"""
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
        """畀其他 cogs 呼叫：await bot.get_cog("Menu").record_usage("drink", user_id, guild_id)"""
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
        """畀 bot.py 全局 on_message fallback 呼叫：純 tag bot 時出公開 Quick Bar。"""
        retry_after = get_retry_after(message.author.id)
        if retry_after > 0:
            return

        touch_cooldown(message.author.id)
        record_usage_sync(
            "mention_menu",
            message.author.id,
            message.guild.id if message.guild else None,
        )

        try:
            await message.reply(
                embed=build_quick_bar_embed(message.author),
                view=QuickBarView(self),
                file=build_menu_file(),
                mention_author=False,
            )
        except discord.HTTPException:
            pass

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(QuickBarView(self))
        self.bot.add_view(HomeMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self.bot.add_view(AdminToolView(self))
        self._views_registered = True

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 快捷吧枱")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=False,
            file=build_menu_file(),
        )

    @app_commands.command(name="community_hub", description="顯示 Con9sole Bartender 主頁")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
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
            await interaction.response.send_message(
                "❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
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
        embed.add_field(
            name="功能使用分佈",
            value=format_stats_block(stats),
            inline=False,
        )
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")

        # Slash command 保持公開，方便 Admin / helpers 一齊睇。
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
