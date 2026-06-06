from __future__ import annotations

import discord

from features.menu_helpers import build_menu_file
from features.menu_views import build_full_menu_view


def build_bartender_result_payload(
    interaction: discord.Interaction,
    result_embed: discord.Embed,
    *,
    attachment_name: str,
) -> dict[str, object]:
    """Build a standard bartender result payload.

    This keeps feature cogs from importing cogs.menu just to attach the Quick Bar
    and bartender image.
    """
    payload: dict[str, object] = {"embed": result_embed}

    menu_view = build_full_menu_view(interaction)
    if menu_view is not None:
        payload["view"] = menu_view

    menu_file = build_menu_file()
    if menu_file is not None:
        result_embed.set_thumbnail(url=f"attachment://{attachment_name}")
        payload["file"] = menu_file

    return payload
