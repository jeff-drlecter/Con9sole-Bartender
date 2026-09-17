from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.permissions import is_admin_or_helper
from features.update_publisher import record_created_game
from utils import copy_forum_tags, make_private_overwrites

log = logging.getLogger("con9sole-bartender.duplicate")


def user_can_manage_games(interaction: discord.Interaction) -> bool:
    return is_admin_or_helper(interaction.user)


def _safe_get(obj: object, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _admin_roles(guild: discord.Guild) -> list[discord.Role]:
    return [role for role_id in config.ADMIN_ROLE_IDS if (role := guild.get_role(role_id))]


def _record_game_announcement(
    guild: discord.Guild,
    *,
    name: str,
    detail: str,
) -> None:
    """Keep a manual-announcement prompt separate from game creation."""
    try:
        record_created_game(guild_id=guild.id, name=name, detail=detail)
    except Exception:
        log.exception("Failed to record created game for later announcement: game=%s", name)


async def _get_template_category(
    client: discord.Client,
    guild: discord.Guild,
) -> discord.CategoryChannel:
    category = guild.get_channel(config.TEMPLATE_CATEGORY_ID)
    if isinstance(category, discord.CategoryChannel):
        return category

    fetched = await client.fetch_channel(config.TEMPLATE_CATEGORY_ID)
    if not isinstance(fetched, discord.CategoryChannel):
        raise RuntimeError(
            f"TEMPLATE_CATEGORY_ID 並不是 Category（而是 {type(fetched).__name__}）。"
        )
    return fetched


def _build_text_kwargs(source: discord.TextChannel) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for source_attr, target_key in (
        ("topic", "topic"),
        ("nsfw", "nsfw"),
        ("rate_limit_per_user", "rate_limit_per_user"),
        ("default_auto_archive_duration", "default_auto_archive_duration"),
    ):
        value = _safe_get(source, source_attr)
        if value is not None:
            kwargs[target_key] = value
    return kwargs


def _build_voice_kwargs(source: discord.VoiceChannel) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for source_attr, target_key in (
        ("bitrate", "bitrate"),
        ("user_limit", "user_limit"),
        ("rtc_region", "rtc_region"),
        ("video_quality_mode", "video_quality_mode"),
    ):
        value = _safe_get(source, source_attr)
        if value is not None:
            kwargs[target_key] = value
    return kwargs


def _build_stage_kwargs(source: discord.StageChannel) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for source_attr, target_key in (("rtc_region", "rtc_region"), ("topic", "topic")):
        value = _safe_get(source, source_attr)
        if value is not None:
            kwargs[target_key] = value
    return kwargs


def _build_forum_kwargs(source: discord.ForumChannel) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for source_attr, target_key in (
        ("topic", "topic"),
        ("nsfw", "nsfw"),
        ("rate_limit_per_user", "rate_limit_per_user"),
        ("default_sort_order", "default_sort_order"),
        ("default_layout", "default_layout"),
        ("default_reaction_emoji", "default_reaction_emoji"),
        ("default_thread_rate_limit_per_user", "default_thread_rate_limit_per_user"),
        ("default_auto_archive_duration", "default_auto_archive_duration"),
    ):
        value = _safe_get(source, source_attr)
        if value is not None:
            kwargs[target_key] = value
    return kwargs


def _normalise_version_base(value: str) -> str:
    base = value.strip()
    if not base:
        raise RuntimeError("新遊戲版本名稱唔可以留空。")

    if base.casefold().endswith(" player"):
        base = base[:-7].rstrip()
    if base.endswith("-專區"):
        base = base[:-3].rstrip("- ")

    if not base:
        raise RuntimeError("新遊戲版本名稱唔可以留空。")
    return base


def _compact_alphanumeric(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _apply_source_casing(value: str, source: str) -> str:
    source_letters = "".join(character for character in source if character.isalpha())
    if source_letters.isupper():
        return value.upper()
    if source_letters.islower():
        return value.lower()
    return value


def _format_replacement_like_source(value: str, source: str) -> str:
    """Retain source separators such as the space in ``NBA 2K25`` when possible."""
    target_characters = [character for character in value if character.isalnum()]
    source_characters = [character for character in source if character.isalnum()]
    if len(target_characters) != len(source_characters):
        return _apply_source_casing(value, source)

    target_index = 0
    formatted: list[str] = []
    for character in source:
        if not character.isalnum():
            formatted.append(character)
            continue

        replacement = target_characters[target_index]
        target_index += 1
        if character.isupper():
            replacement = replacement.upper()
        elif character.islower():
            replacement = replacement.lower()
        formatted.append(replacement)
    return "".join(formatted)


def _derive_version_role_name(
    source_role: discord.Role,
    source_forum: discord.ForumChannel,
    new_game: str,
) -> str:
    """Preserve the source role's naming convention when its game name is identifiable."""
    source_game = _normalise_version_base(source_forum.name)
    source_key = _compact_alphanumeric(source_game)
    role_characters = [
        (index, character.casefold())
        for index, character in enumerate(source_role.name)
        if character.isalnum()
    ]
    role_key = "".join(character for _, character in role_characters)
    match_start = role_key.find(source_key)

    if match_start < 0:
        return f"{new_game} Player"

    match_end = match_start + len(source_key) - 1
    source_start = role_characters[match_start][0]
    source_end = role_characters[match_end][0] + 1
    source_segment = source_role.name[source_start:source_end]
    replacement = _format_replacement_like_source(new_game, source_segment)
    return f"{source_role.name[:source_start]}{replacement}{source_role.name[source_end:]}"


def _clone_forum_overwrites(
    source_forum: discord.ForumChannel,
    *,
    source_role: discord.Role,
    new_role: discord.Role,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        target: overwrite
        for target, overwrite in source_forum.overwrites.items()
        if not (isinstance(target, discord.Role) and target.id == source_role.id)
    }

    source_role_overwrite = source_forum.overwrites_for(source_role)
    if source_role_overwrite.is_empty():
        raise RuntimeError(
            f"來源角色 `{source_role.name}` 喺來源 Forum 冇獨立權限設定，無法安全映射到新角色。"
        )

    overwrites[new_role] = source_role_overwrite
    return overwrites


async def add_game_version(
    guild: discord.Guild,
    *,
    source_forum: discord.ForumChannel,
    source_role: discord.Role,
    new_game: str,
) -> str:
    if source_forum.guild.id != guild.id or source_role.guild.id != guild.id:
        raise RuntimeError("來源 Forum 或角色唔屬於目前伺服器。")
    if source_forum.category is None:
        raise RuntimeError("來源 Forum 冇所屬 Category。")

    base_name = _normalise_version_base(new_game)
    forum_name = f"{base_name}-專區"
    role_name = _derive_version_role_name(source_role, source_forum, base_name)

    if discord.utils.get(guild.forums, name=forum_name) is not None:
        raise RuntimeError(f"已經有一個 Forum 叫 `{forum_name}`。")

    new_role = discord.utils.get(guild.roles, name=role_name)
    if new_role is None:
        new_role = await guild.create_role(
            name=role_name,
            colour=source_role.colour,
            hoist=source_role.hoist,
            mentionable=source_role.mentionable,
            reason=f"Create role for new game version from {source_forum.name}",
        )
        try:
            new_role = await new_role.edit(position=source_role.position)
        except Exception:
            log.exception(
                "Failed to position new game role above source role: role=%s source_role=%s",
                new_role.id,
                source_role.id,
            )

    overwrites = _clone_forum_overwrites(
        source_forum,
        source_role=source_role,
        new_role=new_role,
    )

    new_forum = await guild.create_forum(
        forum_name,
        category=source_forum.category,
        overwrites=overwrites,
        reason=f"Create new game version from {source_forum.name}",
        **_build_forum_kwargs(source_forum),
    )

    try:
        await new_forum.edit(position=source_forum.position)
    except Exception:
        log.exception("Failed to position cloned forum: forum=%s", new_forum.id)

    try:
        await copy_forum_tags(source_forum, new_forum)
    except Exception:
        log.exception("Failed to copy tags to cloned forum: forum=%s", new_forum.id)

    _record_game_announcement(
        guild,
        name=base_name,
        detail=f"已新增 {new_forum.mention}，可選擇 {new_role.mention} 身份。",
    )

    return (
        f"已喺 `#{source_forum.category.name}` 建立 `#{new_forum.name}`；"
        f"新角色：`{new_role.name}`；權限由 `#{source_forum.name}` 複製，"
        f"並將 `{source_role.name}` 映射成 `{new_role.name}`。\n"
        "📝 已記錄到 Update Publisher；如要公告，請喺 Admin Tool 建立草稿（唔會自動發佈）。"
    )


async def add_new_game(
    client: discord.Client,
    guild: discord.Guild,
    game_name: str,
) -> str:
    template_category = await _get_template_category(client, guild)
    all_channels = await guild.fetch_channels()
    template_children = sorted(
        (
            channel
            for channel in all_channels
            if getattr(channel, "category_id", None) == template_category.id
            and isinstance(
                channel,
                (
                    discord.TextChannel,
                    discord.VoiceChannel,
                    discord.StageChannel,
                    discord.ForumChannel,
                ),
            )
        ),
        key=lambda channel: getattr(channel, "position", 0),
    )

    role_name = config.ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if new_role is None:
        new_role = await guild.create_role(
            name=role_name,
            hoist=False,
            mentionable=True,
            reason="Create game role",
        )

    category_name = config.CATEGORY_NAME_PATTERN.format(game=game_name)
    new_category = await guild.create_category(
        name=category_name,
        reason="Create new game section",
    )

    private_overwrites = make_private_overwrites(guild, [new_role], _admin_roles(guild))
    await new_category.edit(overwrites=private_overwrites)

    created_forum: discord.ForumChannel | None = None
    first_source_forum: discord.ForumChannel | None = None

    for source in template_children:
        if isinstance(source, discord.TextChannel):
            created = await guild.create_text_channel(
                source.name,
                category=new_category,
                overwrites=private_overwrites,
                **_build_text_kwargs(source),
            )
        elif isinstance(source, discord.VoiceChannel):
            created = await guild.create_voice_channel(
                source.name,
                category=new_category,
                overwrites=private_overwrites,
                **_build_voice_kwargs(source),
            )
        elif isinstance(source, discord.StageChannel):
            created = await guild.create_stage_channel(
                source.name,
                category=new_category,
                overwrites=private_overwrites,
                **_build_stage_kwargs(source),
            )
        else:
            if first_source_forum is None:
                first_source_forum = source
            created_forum = await guild.create_forum(
                source.name,
                category=new_category,
                overwrites=private_overwrites,
                **_build_forum_kwargs(source),
            )
            created = created_forum

        try:
            await created.edit(position=source.position)
        except Exception:
            log.exception("Failed to position duplicated channel: channel=%s", created.id)

    if first_source_forum is not None and created_forum is not None:
        try:
            await copy_forum_tags(first_source_forum, created_forum)
        except Exception:
            log.exception("Failed to copy tags to duplicated forum: forum=%s", created_forum.id)

    fallback = getattr(config, "FALLBACK_CHANNELS", {}) or {}
    if fallback:
        current_names = {
            channel.name
            for channel in await guild.fetch_channels()
            if getattr(channel, "category_id", None) == new_category.id
        }
        for name in fallback.get("text", []) or []:
            if name not in current_names:
                await guild.create_text_channel(
                    name,
                    category=new_category,
                    overwrites=private_overwrites,
                )
        for name in fallback.get("voice", []) or []:
            if name not in current_names:
                await guild.create_voice_channel(
                    name,
                    category=new_category,
                    overwrites=private_overwrites,
                )
        if created_forum is None and fallback.get("forum"):
            created_forum = await guild.create_forum(
                fallback["forum"],
                category=new_category,
                overwrites=private_overwrites,
            )

    destination = created_forum.mention if created_forum is not None else new_category.mention
    _record_game_announcement(
        guild,
        name=game_name,
        detail=f"已建立 {destination}，可選擇 {new_role.mention} 身份。",
    )

    return (
        f"新分區：#{new_category.name}；新角色：{new_role.name}\n"
        "📝 已記錄到 Update Publisher；如要公告，請喺 Admin Tool 建立草稿（唔會自動發佈）。"
    )


class Duplicate(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="add_new_game",
        description="建立全新遊戲 Category、角色及模板頻道",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.check(lambda interaction: user_can_manage_games(interaction))
    @app_commands.describe(gamename="新遊戲名稱，例如 delta-force")
    async def add_new_game_cmd(
        self,
        interaction: discord.Interaction,
        gamename: str,
    ) -> None:
        if interaction.guild_id != config.GUILD_ID:
            await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
            return
        if not user_can_manage_games(interaction):
            await interaction.response.send_message("需要 Administrator、Manage Server 或 Helper 權限。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            message = await add_new_game(
                interaction.client,
                interaction.guild,  # type: ignore[arg-type]
                gamename,
            )
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ 出錯：{exc}", ephemeral=True)

    @app_commands.command(
        name="add_game_version",
        description="喺現有遊戲系列 Category 內新增另一個版本 Forum 及角色",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.check(lambda interaction: user_can_manage_games(interaction))
    @app_commands.describe(
        source_forum="來源版本 Forum，例如 gta-v-專區",
        source_role="來源版本角色，例如 GTA-V Player",
        new_game="新版本名稱；例如填 GTA-VI，會建立 GTA-VI-專區及 GTA-VI Player",
    )
    async def add_game_version_cmd(
        self,
        interaction: discord.Interaction,
        source_forum: discord.ForumChannel,
        source_role: discord.Role,
        new_game: str,
    ) -> None:
        if interaction.guild_id != config.GUILD_ID:
            await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
            return
        if not user_can_manage_games(interaction):
            await interaction.response.send_message("需要 Administrator、Manage Server 或 Helper 權限。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            message = await add_game_version(
                interaction.guild,  # type: ignore[arg-type]
                source_forum=source_forum,
                source_role=source_role,
                new_game=new_game,
            )
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ 出錯：{exc}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Duplicate(bot))
