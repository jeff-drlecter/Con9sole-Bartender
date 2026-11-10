from __future__ import annotations

import discord


def safe_message_kwargs(
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
    file: discord.File | None = None,
    ephemeral: bool = False,
) -> None:
    kwargs = safe_message_kwargs(
        content=content,
        embed=embed,
        embeds=embeds,
        view=view,
        file=file,
        ephemeral=ephemeral,
    )

    if ephemeral:
        from features.language_preferences import language, menu_text, localize_menu
        if content is not None:
            kwargs["content"] = menu_text(content, language(interaction.user))
        if embed is not None or view is not None:
            localized_embed, localized_view = localize_menu(interaction.user, embed, view)
            if embed is not None:
                kwargs["embed"] = localized_embed
            if view is not None:
                kwargs["view"] = localized_view
        if embeds is not None:
            kwargs["embeds"] = [localize_menu(interaction.user, item)[0] for item in embeds]

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)
