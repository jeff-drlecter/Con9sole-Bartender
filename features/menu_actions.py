from __future__ import annotations

import discord

from core.safe_send import safe_message_kwargs, send_or_followup
from features.invite_tools import create_invite_link_from_button as run_create_invite_link_from_button
from features.menu_embeds import (
    build_admin_tool_embed,
    build_help_embed,
    build_home_menu_embed,
    build_quick_bar_embed,
)
from features.menu_helpers import build_menu_file, can_use_admin, get_retry_after, touch_cooldown
from features.menu_stats import record_usage_sync
from features.menu_views import AdminToolView, HelpMenuView, HomeMenuView, QuickBarView


def _log_http_exception(context: str, exc: discord.HTTPException) -> None:
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    text = getattr(exc, "text", None)
    print(f"[{context}] HTTPException status={status} code={code} text={text!r}")


async def open_quick_bar_menu(
    cog: object,
    interaction: discord.Interaction,
    *,
    ephemeral: bool,
) -> None:
    record_usage_sync("menu", interaction.user.id, interaction.guild_id)
    await send_or_followup(
        interaction,
        embed=build_quick_bar_embed(interaction.user),
        view=QuickBarView(cog),
        ephemeral=ephemeral,
        file=build_menu_file(),
    )


async def open_home_menu(cog: object, interaction: discord.Interaction) -> None:
    record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
    try:
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(cog),
            ephemeral=True,
            file=build_menu_file(),
        )
        return
    except discord.HTTPException as exc:
        _log_http_exception("slash home_menu full view", exc)

    await send_or_followup(
        interaction,
        embed=build_home_menu_embed(interaction.user, include_thumbnail=False),
        view=HomeMenuView(cog, include_social=False, include_external_links=False),
        ephemeral=True,
    )


async def open_help_menu(cog: object, interaction: discord.Interaction) -> None:
    record_usage_sync("help", interaction.user.id, interaction.guild_id)
    await send_or_followup(
        interaction,
        embed=build_help_embed(interaction.user),
        view=HelpMenuView(cog),
        ephemeral=True,
        file=build_menu_file(),
    )


async def open_admin_tool_menu(cog: object, interaction: discord.Interaction) -> None:
    record_usage_sync("admin_tool", interaction.user.id, interaction.guild_id)
    await send_or_followup(
        interaction,
        embed=build_admin_tool_embed(interaction.user),
        view=AdminToolView(cog),
        ephemeral=True,
    )


async def open_invite_menu(interaction: discord.Interaction) -> None:
    await run_create_invite_link_from_button(interaction, can_use_admin_func=can_use_admin)


async def send_mention_quick_bar(cog: object, message: discord.Message) -> None:
    if message.author.bot:
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
            view=QuickBarView(cog),
            file=build_menu_file(),
        )
        kwargs["mention_author"] = False
        await message.reply(**kwargs)
    except discord.HTTPException:
        pass
