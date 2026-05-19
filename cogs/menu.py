from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper
from core.safe_send import safe_message_kwargs, send_or_followup
from data.menu_registry import MenuItem, get_menu_items
from features.admin_actions import (
    admin_ping_from_button as run_admin_ping_from_button,
    admin_reload_from_button as run_admin_reload_from_button,
    admin_vc_teardown_from_button as run_admin_vc_teardown_from_button,
)
from features.invite_tools import create_invite_link_from_button as run_create_invite_link_from_button
from features.menu_stats import (
    FEATURE_EMOJIS,
    FEATURE_LABELS,
    build_admin_stats_embed,
    init_stats_db,
    record_usage_sync,
)
from features.role_tools import (
    RoleActionState,
    RoleToolsView,
    build_role_tools_embed,
    get_member_from_state,
    get_role_from_state,
)

MENU_COLOR = 0x2B2D31
COOLDOWN_SECONDS = 3.0
MENTION_DEDUPE_TTL_SECONDS = 300.0
ROLE_TOOLS_TIMEOUT_SECONDS = 300
ROLE_BATCH_PAUSE_EVERY = 10
ROLE_BATCH_PAUSE_SECONDS = 0.8

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BARTENDER_IMAGE = ASSETS_DIR / "bartender.png"
BARTENDER_ATTACHMENT_NAME = "bartender.png"
COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")
INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://threads.net/con9sole")
RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

USER_MENU_COOLDOWNS: dict[int, float] = {}
MENTION_MESSAGE_DEDUPE: dict[int, float] = {}

STYLE_MAP: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "link": discord.ButtonStyle.link,
}

COG_METHOD_FALLBACKS: dict[str, list[str]] = {
    "team": ["menu_entry"],
    "tempvc": ["menu_entry"],
    "tempvc_control": ["open_control_panel_from_menu"],
    "cheers": ["menu_entry"],
    "cheers_target": ["cheer_for_member_entry"],
    "drink": ["menu_entry"],
    "drink_gift": ["gift_drink_entry"],
    "drink_stats": ["stats_entry"],
    "drink_collection": ["collection_entry"],
    "confession": ["menu_entry"],
}




# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------

def can_use_admin(member: discord.Member | discord.User) -> bool:
    """Backward-compatible admin/helper checker."""
    return is_admin_or_helper(member)


can_use_admin_stats = can_use_admin


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


def _apply_bartender_thumbnail(embed: discord.Embed) -> None:
    if BARTENDER_IMAGE.exists():
        embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")


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


def _cleanup_mention_dedupe(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    expired_ids = [
        message_id
        for message_id, seen_at in MENTION_MESSAGE_DEDUPE.items()
        if now - seen_at >= MENTION_DEDUPE_TTL_SECONDS
    ]
    for message_id in expired_ids:
        MENTION_MESSAGE_DEDUPE.pop(message_id, None)

    if len(MENTION_MESSAGE_DEDUPE) > 1000:
        newest = sorted(MENTION_MESSAGE_DEDUPE.items(), key=lambda item: item[1], reverse=True)[:300]
        MENTION_MESSAGE_DEDUPE.clear()
        MENTION_MESSAGE_DEDUPE.update(dict(newest))


def claim_mention_message(message_id: int) -> bool:
    now = time.time()
    _cleanup_mention_dedupe(now)
    if message_id in MENTION_MESSAGE_DEDUPE:
        return False
    MENTION_MESSAGE_DEDUPE[message_id] = now
    return True


# -----------------------------------------------------------------------------
# Main menu embeds
# -----------------------------------------------------------------------------

def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "👥 **組隊**｜召集隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **控制**｜管理目前小隊 call\n\n"
            "🎉 **打氣**｜為大家補充能量\n"
            "🙌 **幫人打氣**｜送一句打氣給其他成員\n"
            "🍹 **調酒**｜酒保特選\n"
            "🥂 **賜酒**｜賜一杯酒給其他成員\n\n"
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
            "🎛️ **小隊 call 控制** — 管理目前身處的小隊 call\n\n"
            "🎉 **打氣** — 為大家補充能量\n"
            "🙌 **幫人打氣** — 送一句打氣給其他成員\n"
            "🕯️ **無名告白** — 匿名投稿\n\n"
            "🍹 **調酒** — 酒保特選\n"
            "🥂 **賜酒** — 賜一杯酒給其他成員\n"
            "📊 **酒保紀錄** — 查看自己的酒保互動\n"
            "🍾 **酒單收藏** — 查看酒款收藏進度\n\n"
            "🔗 **生成邀請碼** — 7 日 / 10 次公開邀請連結\n"
            "📸 **IG Page** — 官方 Instagram\n"
            "🧵 **Threads Page** — 官方 Threads\n\n"
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
            "🎛️ **小隊 call 控制**｜改人數上限 / 刪除自己的小隊 call\n\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🙌 **幫人打氣**｜tag 一位成員，送一句打氣給對方\n\n"
            "🍹 **調酒**｜抽一杯酒保特選飲品\n"
            "🥂 **賜酒**｜tag 一位成員，賜一杯酒給對方\n"
            "📊 **酒保紀錄**｜查看自己叫酒 / 賜酒 / 收到賜酒紀錄\n"
            "🍾 **酒單收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n\n"
            "🕯️ **無名告白**｜匿名投稿\n"
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
            "🎭 **Role Tools** — Select Menu 角色管理工具\n"
            "🏓 **Ping** — Bot latency\n"
            "🧹 **VC Teardown** — 列出並刪除 Bot Temp VC\n\n"
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
            "**Select Menu 角色管理工具**\n\n"
            "➕ **加角色** — 用選單選成員 / 角色，再確認執行\n"
            "➖ **移除角色** — 用選單選成員 / 角色，再確認執行\n"
            "📋 **查看角色** — 用 User Select 或 User ID 查看角色\n"
            "🧬 **新版本頻道** — 先保留為 slash 指令提示，不直接 button 執行\n\n"
            "✅ 平時用選單，搜尋不到成員時用 User ID fallback。\n"
            "⚠️ 批量處理前會顯示預計影響人數。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def build_role_channel_new_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🧬 新版本頻道",
        description=(
            "呢個功能涉及 clone channel、建立新版本 role 同權限設定，暫時保留用 slash command 執行。\n\n"
            "請使用：\n"
            "`/role_channel_new`\n\n"
            "建議只喺需要建立新版 channel / role 時使用。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜此功能暫不直接由 button 執行。")
    return embed


# -----------------------------------------------------------------------------
# Registry router
# -----------------------------------------------------------------------------

def _get_method(target: object, item: MenuItem) -> Callable[..., Awaitable[None]] | None:
    names = [item.method]
    names.extend(name for name in COG_METHOD_FALLBACKS.get(item.id, []) if name not in names)

    for name in names:
        candidate = getattr(target, name, None)
        if candidate and inspect.iscoroutinefunction(candidate):
            return candidate
    return None


async def _call_method_safely(method: Callable[..., Awaitable[None]], interaction: discord.Interaction) -> None:
    try:
        await method(interaction)
    except TypeError:
        try:
            await method(interaction, None)
        except TypeError:
            await method(interaction, to=None)


class RegistryButton(discord.ui.Button):
    def __init__(self, item: MenuItem):
        style = STYLE_MAP.get(item.style, discord.ButtonStyle.secondary)
        kwargs: dict[str, object] = {
            "label": item.label,
            "emoji": item.emoji,
            "style": style,
            "row": item.row,
        }
        if item.url:
            kwargs["url"] = item.url
        else:
            kwargs["custom_id"] = f"bartender:{item.layer}:{item.id}"

        super().__init__(**kwargs)
        self.item = item

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RegistryMenuView):
            await send_or_followup(interaction, content="❌ Menu view 狀態異常，請重新輸入 `/menu`。", ephemeral=True)
            return
        await self.view.handle_item(interaction, self.item)


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: "Menu", *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
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



class RegistryMenuView(BaseMenuView):
    def __init__(self, cog: "Menu", layer: str) -> None:
        super().__init__(cog, timeout=None)
        self.layer = layer
        for item in get_menu_items(layer):
            self.add_item(RegistryButton(item))

    async def handle_item(self, interaction: discord.Interaction, item: MenuItem) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        if item.admin_only and not await self._require_admin(interaction):
            return

        if item.cog is None:
            await send_or_followup(interaction, content="❌ 呢個功能未設定 cog。", ephemeral=True)
            return

        target = self.cog if item.cog == "Menu" else interaction.client.get_cog(item.cog)
        if target is None:
            await send_or_followup(
                interaction,
                content=f"❌ `{item.cog}` 功能未載入。",
                ephemeral=True,
            )
            return

        method = _get_method(target, item)
        if method is None:
            await send_or_followup(
                interaction,
                content=f"❌ `{item.cog}` 未提供 `{item.method}` 入口。",
                ephemeral=True,
            )
            return

        try:
            await _call_method_safely(method, interaction)
        except discord.InteractionResponded:
            pass
        except Exception as exc:
            # 如果目標功能已經回覆過 user，就唔再補第二個錯誤訊息。
            # 例如 tempvc_control 已經提示「你而家未身處任何語音房」，
            # 就避免再出「AttributeError」造成重覆錯誤。
            if interaction.response.is_done():
                print(f"[Menu router suppressed] {item.id}: {type(exc).__name__}: {exc}")
                return

            await send_or_followup(
                interaction,
                content=f"❌ 執行 `{item.id}` 時出錯：`{type(exc).__name__}`。",
                ephemeral=True,
            )


class QuickBarView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "quick")


class HomeMenuView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "home")
        self.add_item(discord.ui.Button(label="IG Page", emoji="📸", style=discord.ButtonStyle.link, url=INSTAGRAM_URL, row=3))
        self.add_item(discord.ui.Button(label="Threads Page", emoji="🧵", style=discord.ButtonStyle.link, url=THREADS_URL, row=3))
        if RULES_URL:
            self.add_item(discord.ui.Button(label="Rules", emoji="🛡️", style=discord.ButtonStyle.link, url=RULES_URL, row=4))
        if HELP_URL:
            self.add_item(discord.ui.Button(label="Help Channel", emoji="❓", style=discord.ButtonStyle.link, url=HELP_URL, row=4))


class AdminToolView(RegistryMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, "admin")


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog, timeout=None)

    @discord.ui.button(label="Menu", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:help:home", row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self.cog.open_home_menu_from_button(interaction)



# Backward-compatible aliases used by other cogs.
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


# -----------------------------------------------------------------------------
# Cog
# -----------------------------------------------------------------------------

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

    async def enforce_menu_button_cooldown(self, interaction: discord.Interaction) -> bool:
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

    async def record_usage(self, feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
        record_usage_sync(feature, user_id, guild_id)

    async def execute_role_change_from_select(self, interaction: discord.Interaction, *, state: RoleActionState) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            return

        role_cog = interaction.client.get_cog("RoleManager")
        if role_cog is None or not hasattr(role_cog, "_apply_role_change"):
            await interaction.response.edit_message(content="❌ RoleManager cog 未載入，請先 `/reload role`。", embed=None, view=None)
            return

        apply_role = get_role_from_state(interaction.guild, state.apply_role_id)
        if apply_role is None:
            await interaction.response.edit_message(content="❌ 要處理嘅角色已不存在。", embed=None, view=None)
            return

        target_member: discord.Member | None = None
        target_role: discord.Role | None = None

        if state.target_kind == "member":
            target_member = get_member_from_state(interaction.guild, state.target_member_id)
            if target_member is None and state.target_member_id is not None:
                try:
                    target_member = await interaction.guild.fetch_member(state.target_member_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    target_member = None
            if target_member is None:
                await interaction.response.edit_message(content="❌ 目標成員已不存在，或 Bot 無法讀取該成員。", embed=None, view=None)
                return
        else:
            target_role = get_role_from_state(interaction.guild, state.target_role_id)
            if target_role is None:
                await interaction.response.edit_message(content="❌ 目標角色群組已不存在。", embed=None, view=None)
                return

        feature = "admin_role_grant" if state.mode == "add" else "admin_role_revoke"
        record_usage_sync(feature, interaction.user.id, interaction.guild_id)

        try:
            await role_cog._apply_role_change(  # type: ignore[attr-defined]
                interaction,
                role_id=str(apply_role.id),
                target_member=target_member,
                target_role=target_role,
                include_bots=state.include_bots,
                mode=state.mode,
            )
        except discord.InteractionResponded:
            return
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"⚠️ Role Tools 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )

    async def execute_role_list_for_member(
        self,
        interaction: discord.Interaction,
        *,
        member: discord.Member,
        edit_existing: bool = True,
    ) -> None:
        if not interaction.guild:
            if edit_existing:
                await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            else:
                await interaction.response.send_message("⚠️ 呢個工具只可以喺伺服器內使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            if edit_existing:
                await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            else:
                await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        roles = [role for role in member.roles if not role.is_default()]
        roles.sort(key=lambda role: role.position, reverse=True)
        record_usage_sync("admin_role_list", interaction.user.id, interaction.guild_id)

        if not roles:
            content = f"ℹ️ {member.mention} 沒有任何自訂角色。"
            if edit_existing:
                await interaction.response.edit_message(content=content, embed=None, view=None)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        lines = [f"{role.mention} (ID: `{role.id}`)" for role in roles]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current_len + len(line) + 1 > 3800:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))

        embed = discord.Embed(
            title=f"📋 {member.display_name} 的角色（高→低）",
            description=chunks[0],
            color=MENU_COLOR,
        )
        embed.set_footer(text=f"共有 {len(roles)} 個角色")

        if edit_existing:
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

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

    async def open_home_menu_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_help_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("help", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_admin_tool_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_tool", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self),
            ephemeral=True,
        )

    async def create_invite_link_from_button(self, interaction: discord.Interaction) -> None:
        await run_create_invite_link_from_button(interaction, can_use_admin_func=can_use_admin)

    async def admin_stats_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)
        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)
        embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=7, title_scope="本週")
        await send_or_followup(interaction, embed=embed, view=AdminToolView(self), ephemeral=True)

    async def admin_reload_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_reload_from_button(interaction)

    async def admin_role_tools_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_role", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_role_tools_embed(interaction.user),
            view=RoleToolsView(self),
            ephemeral=True,
        )

    async def admin_ping_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_ping_from_button(interaction)

    async def admin_vc_teardown_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_vc_teardown_from_button(interaction)

    async def send_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not claim_mention_message(message.id):
            return

        if not can_use_admin(message.author):
            retry_after = get_retry_after(message.author.id)
            if retry_after > 0:
                return
            touch_cooldown(message.author.id)

        record_usage_sync("mention_menu", message.author.id, message.guild.id if message.guild else None)

        try:
            kwargs = safe_message_kwargs(
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

    @commands.Cog.listener("on_message")
    async def on_message_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return
        if self.bot.user is None:
            return

        direct_mention = f"<@{self.bot.user.id}>" in message.content or f"<@!{self.bot.user.id}>" in message.content
        if not direct_mention:
            return

        cleaned = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        if cleaned:
            return

        await self.send_mention_menu(message)

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

        embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=days, title_scope=title_scope)
        await send_or_followup(interaction, embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
