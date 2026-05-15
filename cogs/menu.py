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
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://www.threads.net/@con9sole")

# 可選：如果你有 rules/help channel link，可以喺 config.py 加：
# RULES_URL = "https://discord.com/channels/.../..."
# HELP_URL = "https://discord.com/channels/.../..."
RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

# /admin_stats 權限：Manage Server 或 Helper role 都可以使用
# 可選 config.py：
# HELPER_ROLE_IDS = [123456789012345678]
# HELPER_ROLE_NAMES = ["Helper", "helper", "社群助手"]
HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = set(getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper"]))

# 全局 user cooldown：同一個 user 撳任何 menu / submenu 按鈕都會共用 CD
USER_MENU_COOLDOWNS: dict[int, float] = {}

FEATURE_LABELS: dict[str, str] = {
    "menu": "Menu",
    "team": "組隊",
    "tempvc": "建立小隊 call",
    "cheers": "打氣時間",
    "drink": "調酒",
    "social": "Social Link",
    "help": "Help",
    "close": "Close",
    "community_hub": "Community Hub",
    "admin_stats": "Admin Stats",
    "mention_menu": "Mention Menu",
}

FEATURE_EMOJIS: dict[str, str] = {
    "menu": "📋",
    "team": "👥",
    "tempvc": "🎧",
    "cheers": "🎉",
    "drink": "🍹",
    "social": "📱",
    "help": "ℹ️",
    "close": "🗑️",
    "community_hub": "🧭",
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


def can_use_admin_stats(member: discord.Member | discord.User) -> bool:
    """Manage Server 或 Helper role 都可以使用 /admin_stats。"""
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


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "🎮 **組隊**｜召集隊友\n"
            "🎙️ **建立小隊 call**｜開臨時語音房\n"
            "🎉 **打氣時間**｜來一點鼓勵\n"
            "🍹 **調酒**｜來一杯\n"
            "📱 **Social Link**｜IG / Threads"
        ),
        color=MENU_COLOR,
    )
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，今晚由我為你服務。")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 使用說明",
        description="酒保已經準備好，以下是你可以使用的服務。",
        color=MENU_COLOR,
    )
    embed.add_field(name="👥 組隊", value="發起組隊 / 招募隊友", inline=False)
    embed.add_field(name="🎧 建立小隊 call", value="建立臨時語音房", inline=False)
    embed.add_field(name="🎉 打氣時間", value="送出隨機打氣內容", inline=False)
    embed.add_field(name="🍹 調酒", value="抽一杯隨機飲品", inline=False)
    embed.add_field(name="📱 Social Link", value="查看 Con9sole IG / Threads", inline=False)
    embed.add_field(name="🧭 Community Hub", value="公開社群入口，適合放喺新人頻道", inline=False)
    embed.add_field(name="📊 Admin Stats", value="Admin / Helper 查看功能使用數據", inline=False)
    embed.add_field(name="🗑️ Close", value="關閉目前面板", inline=False)
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，慢慢揀，我喺度等你。")
    return embed


def build_socials_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📱 Con9sole Social Link",
        description="想追蹤最新動態？酒保幫你準備好官方連結。",
        color=MENU_COLOR,
    )
    embed.add_field(name="📸 Instagram", value="官方 IG", inline=False)
    embed.add_field(name="🧵 Threads", value="官方 Threads", inline=False)
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，有空都可以去逛逛。")
    return embed


def build_community_hub_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🧭 Community Hub",
        description=(
            f"歡迎嚟到 **{COMMUNITY_NAME}**。\n\n"
            "你可以喺呢度快速開始：\n"
            "🎮 **組隊** — 搵隊友一齊玩\n"
            "🎙️ **建立小隊 call** — 開臨時語音房\n"
            "🎉 **打氣時間** — 為大家補充能量\n"
            "🍹 **調酒** — 來一杯今日心情\n"
            "📱 **Social Link** — 追蹤 Con9sole 最新動態\n\n"
            "按下面按鈕開始。"
        ),
        color=MENU_COLOR,
    )
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text="Community Hub · Public Entry")
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


class SocialsMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

        self.add_item(
            discord.ui.Button(
                label="Instagram",
                emoji="📸",
                style=discord.ButtonStyle.link,
                url=INSTAGRAM_URL,
                row=0,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Threads",
                emoji="🧵",
                style=discord.ButtonStyle.link,
                url=THREADS_URL,
                row=0,
            )
        )

    @discord.ui.button(
        label="返回主選單",
        emoji="🔙",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:socials:back",
        row=1,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="返回主選單",
        emoji="🔙",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:help:back",
        row=0,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


class MenuEntryView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="主選單",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:entry:menu",
        row=0,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


def build_menu_entry_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return MenuEntryView(menu_cog)


def build_full_menu_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return MainMenuView(menu_cog)


class MainMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

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

    @discord.ui.button(
        label="Menu",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:menu",
        row=0,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:main:team",
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
        label="建立小隊 call",
        emoji="🎧",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:main:tempvc",
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
        label="打氣時間",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="bartender:main:cheers",
        row=1,
    )
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣時間功能未載入。",
        )

    @discord.ui.button(
        label="調酒",
        emoji="🍹",
        style=discord.ButtonStyle.success,
        custom_id="bartender:main:drink",
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
        label="Social Link",
        emoji="📱",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:socials",
        row=1,
    )
    async def socials_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "social")
        await send_or_followup(
            interaction,
            embed=build_socials_embed(interaction.user),
            view=SocialsMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="Community Hub",
        emoji="🧭",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:community_hub",
        row=2,
    )
    async def community_hub_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "community_hub")
        await send_or_followup(
            interaction,
            embed=build_community_hub_embed(interaction.user),
            view=CommunityHubView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="Help",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:help",
        row=2,
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
        label="Close",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="bartender:main:close",
        row=2,
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "close")

        if not interaction.response.is_done():
            await interaction.response.defer()

        try:
            await interaction.message.delete()
        except discord.HTTPException:
            await interaction.followup.send("❌ 呢個面板刪除失敗。", ephemeral=True)


class CommunityHubView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

        self.add_item(
            discord.ui.Button(
                label="Instagram",
                emoji="📸",
                style=discord.ButtonStyle.link,
                url=INSTAGRAM_URL,
                row=3,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Threads",
                emoji="🧵",
                style=discord.ButtonStyle.link,
                url=THREADS_URL,
                row=3,
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

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:hub:team",
        row=0,
    )
    async def hub_team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="team",
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(
        label="建立小隊 call",
        emoji="🎧",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:hub:tempvc",
        row=0,
    )
    async def hub_tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
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
        label="打氣時間",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="bartender:hub:cheers",
        row=1,
    )
    async def hub_cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="cheers",
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣時間功能未載入。",
        )

    @discord.ui.button(
        label="調酒",
        emoji="🍹",
        style=discord.ButtonStyle.success,
        custom_id="bartender:hub:drink",
        row=1,
    )
    async def hub_drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            feature="drink",
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )

    @discord.ui.button(
        label="Menu",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:hub:menu",
        row=2,
    )
    async def hub_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await self._record(interaction, "menu")
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


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
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def send_mention_menu(self, message: discord.Message) -> None:
        """畀 bot.py 全局 on_message fallback 呼叫：純 tag bot 時出公開 Menu。"""
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
                embed=build_main_menu_embed(message.author),
                view=MainMenuView(self),
                file=build_menu_file(),
                mention_author=False,
            )
        except discord.HTTPException:
            pass

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(MainMenuView(self))
        self.bot.add_view(MenuEntryView(self))
        self.bot.add_view(SocialsMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self.bot.add_view(CommunityHubView(self))
        self._views_registered = True

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 面板")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self),
            ephemeral=False,
            file=build_menu_file(),
        )

    @app_commands.command(name="community_hub", description="發出公開 Community Hub 入口")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        record_usage_sync("community_hub", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
            embed=build_community_hub_embed(interaction.user),
            view=CommunityHubView(self),
            ephemeral=False,
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
        if not can_use_admin_stats(interaction.user):
            await interaction.response.send_message(
                "❌ 你需要 `Manage Server` 權限或 Helper role 先可以查看統計。",
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

        # 按你之前要求：Admin/Helper 操作公開，方便其他管理人員一齊睇。
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
