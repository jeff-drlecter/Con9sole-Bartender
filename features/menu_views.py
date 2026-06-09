from __future__ import annotations

import inspect
from typing import Awaitable, Callable

import discord

import config
from core.safe_send import send_or_followup
from data.menu_registry import MenuItem, get_menu_items
from features.menu_embeds import build_home_menu_embed
from features.menu_helpers import can_use_admin

RULES_URL = getattr(config, "RULES_URL", None)
HELP_URL = getattr(config, "HELP_URL", None)

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
    "drink_leaderboard": ["leaderboard_entry"],
    "daily_bar": ["menu_entry"],
    "confession": ["menu_entry"],
}

TARGET_MANAGED_COOLDOWN_ITEM_IDS = {
    "cheers",
    "cheers_target",
    "drink",
    "drink_gift",
}

NO_COOLDOWN_ITEM_IDS = {
    "home_menu",
    "help",
    "admin_tool",
    "invite",
    "instagram",
    "threads",
    "drink_stats",
    "drink_collection",
    "drink_leaderboard",
    "daily_bar",
}

LABEL_OVERRIDES: dict[str, str] = {
    "invite": "邀請",
}


def _get_method(target: object, item: MenuItem) -> Callable[..., Awaitable[None]] | None:
    names = [item.method]
    names.extend(name for name in COG_METHOD_FALLBACKS.get(item.id, []) if name not in names)

    for name in names:
        candidate = getattr(target, name, None)
        if candidate and inspect.iscoroutinefunction(candidate):
            return candidate

    return None


async def _call_method_safely(method: Callable[..., Awaitable[None]], interaction: discord.Interaction) -> None:
    await method(interaction)


def _log_http_exception(context: str, exc: discord.HTTPException) -> None:
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    text = getattr(exc, "text", None)
    print(f"[{context}] HTTPException status={status} code={code} text={text!r}")


class RegistryButton(discord.ui.Button):
    def __init__(self, item: MenuItem):
        style = STYLE_MAP.get(item.style, discord.ButtonStyle.secondary)

        kwargs: dict[str, object] = {
            "label": LABEL_OVERRIDES.get(item.id, item.label),
            "style": style,
            "row": item.row,
        }

        if item.emoji:
            kwargs["emoji"] = item.emoji

        if item.url:
            kwargs["url"] = item.url
        else:
            kwargs["custom_id"] = f"bartender:{item.layer}:{item.id}"

        super().__init__(**kwargs)
        self.item = item

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RegistryMenuView):
            await send_or_followup(
                interaction,
                content="❌ Menu view 狀態異常，請重新輸入 `/menu`。",
                ephemeral=True,
            )
            return

        await self.view.handle_item(interaction, self.item)


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: object, *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
        enforce = getattr(self.cog, "enforce_menu_button_cooldown", None)
        if enforce is None:
            enforce = getattr(self.cog, "_enforce_command_cooldown", None)
        if enforce is None:
            return True

        return await enforce(interaction)

    async def _record(self, interaction: discord.Interaction, feature: str) -> None:
        record = getattr(self.cog, "record_usage", None)
        if record is not None:
            await record(feature, interaction.user.id, interaction.guild_id)

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
    def __init__(self, cog: object, layer: str) -> None:
        super().__init__(cog, timeout=None)
        self.layer = layer

        for item in get_menu_items(layer):
            self.add_item(RegistryButton(item))

    async def _send_home_menu_direct(self, interaction: discord.Interaction) -> None:
        await self._record(interaction, "home_menu")
        embed = build_home_menu_embed(interaction.user, include_thumbnail=False)

        try:
            await send_or_followup(
                interaction,
                embed=embed,
                view=HomeMenuView(self.cog),
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            _log_http_exception("home_menu full view", exc)

        await send_or_followup(
            interaction,
            embed=embed,
            view=HomeMenuView(self.cog, include_external_links=False),
            ephemeral=True,
        )

    async def handle_item(self, interaction: discord.Interaction, item: MenuItem) -> None:
        if item.id == "home_menu":
            try:
                await self._send_home_menu_direct(interaction)
            except discord.InteractionResponded:
                pass
            except Exception as exc:
                if interaction.response.is_done():
                    print(f"[Menu router suppressed] {item.id}: {type(exc).__name__}: {exc}")
                    return
                await send_or_followup(
                    interaction,
                    content=f"❌ 執行 `{item.id}` 時出錯：`{type(exc).__name__}`。",
                    ephemeral=True,
                )
            return

        if item.id not in TARGET_MANAGED_COOLDOWN_ITEM_IDS and item.id not in NO_COOLDOWN_ITEM_IDS:
            if not await self._enforce_cooldown(interaction):
                return

        if item.admin_only and not await self._require_admin(interaction):
            return

        if item.cog is None:
            await send_or_followup(
                interaction,
                content="❌ 呢個功能未設定 cog。",
                ephemeral=True,
            )
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
            if interaction.response.is_done():
                print(f"[Menu router suppressed] {item.id}: {type(exc).__name__}: {exc}")
                return

            await send_or_followup(
                interaction,
                content=f"❌ 執行 `{item.id}` 時出錯：`{type(exc).__name__}`。",
                ephemeral=True,
            )


class QuickBarView(RegistryMenuView):
    def __init__(self, cog: object) -> None:
        super().__init__(cog, "quick")


class HomeMenuView(RegistryMenuView):
    def __init__(
        self,
        cog: object,
        *,
        include_external_links: bool = True,
    ) -> None:
        super().__init__(cog, "home")

        if include_external_links and RULES_URL:
            self.add_item(
                discord.ui.Button(
                    label="Rules",
                    emoji="📜",
                    style=discord.ButtonStyle.link,
                    url=RULES_URL,
                    row=4,
                )
            )

        if include_external_links and HELP_URL:
            self.add_item(
                discord.ui.Button(
                    label="Help Channel",
                    emoji="❓",
                    style=discord.ButtonStyle.link,
                    url=HELP_URL,
                    row=4,
                )
            )


class AdminToolView(RegistryMenuView):
    def __init__(self, cog: object) -> None:
        super().__init__(cog, "admin")


class HelpMenuView(QuickBarView):
    """Backwards-compatible help view: show the normal Quick Bar under Help."""

    pass


class MainMenuView(HomeMenuView):
    """Backwards-compatible alias for older cogs / fallback code."""

    pass


def build_full_menu_view(interaction: discord.Interaction) -> QuickBarView | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return QuickBarView(menu_cog)
