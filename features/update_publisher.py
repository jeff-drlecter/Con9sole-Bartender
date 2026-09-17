from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import discord

from core.json_storage import atomic_write_json, load_json_object
from core.storage_paths import GAME_ANNOUNCEMENTS_PATH


UPDATE_PUBLISHER_COLOR = 0x5865F2
MAX_PENDING_GAMES = 30
AnnouncementKind = Literal["feature", "game"]


@dataclass(frozen=True)
class PendingGame:
    id: str
    guild_id: int
    name: str
    detail: str
    created_at: str
    source_key: str | None = None
    role_id: int | None = None


@dataclass(frozen=True)
class AnnouncementDraft:
    kind: AnnouncementKind
    title: str
    body: str
    game_ids: tuple[str, ...] = ()
    version: str = ""
    announcement_date: str = ""


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "games": []}


def _load_state(path: Path = GAME_ANNOUNCEMENTS_PATH) -> dict[str, Any]:
    state = load_json_object(path, _empty_state)
    if not isinstance(state.get("games"), list):
        return _empty_state()
    return state


def _as_pending_game(value: object, *, guild_id: int) -> PendingGame | None:
    if not isinstance(value, dict):
        return None

    try:
        record_guild_id = value["guild_id"]
        name = value["name"]
        detail = value["detail"]
        record_id = value["id"]
        created_at = value["created_at"]
    except KeyError:
        return None

    if (
        not isinstance(record_guild_id, int)
        or record_guild_id != guild_id
        or not all(isinstance(item, str) and item.strip() for item in (name, detail, record_id, created_at))
        or value.get("published_at") is not None
    ):
        return None

    return PendingGame(
        id=record_id,
        guild_id=record_guild_id,
        name=name,
        detail=detail,
        created_at=created_at,
        source_key=value.get("source_key") if isinstance(value.get("source_key"), str) else None,
        role_id=value.get("role_id") if isinstance(value.get("role_id"), int) else None,
    )


def record_created_game(
    *,
    guild_id: int,
    name: str,
    detail: str,
    source_key: str | None = None,
    role_id: int | None = None,
    path: Path = GAME_ANNOUNCEMENTS_PATH,
) -> PendingGame:
    """Record a game for a later manual announcement; this never publishes anything."""
    clean_name = name.strip()
    clean_detail = detail.strip()
    if not clean_name or not clean_detail:
        raise ValueError("Game announcement record requires a name and detail.")

    state = _load_state(path)
    games = state["games"]
    clean_source_key = source_key.strip() if isinstance(source_key, str) and source_key.strip() else None
    if clean_source_key is not None:
        for item in games:
            if (
                isinstance(item, dict)
                and item.get("guild_id") == guild_id
                and item.get("source_key") == clean_source_key
                and item.get("published_at") is None
            ):
                existing = _as_pending_game(item, guild_id=guild_id)
                if existing is not None:
                    item["name"] = clean_name
                    item["detail"] = clean_detail
                    item["role_id"] = role_id
                    atomic_write_json(path, state)
                    refreshed = _as_pending_game(item, guild_id=guild_id)
                    if refreshed is not None:
                        return refreshed

    record = {
        "id": uuid4().hex,
        "guild_id": guild_id,
        "name": clean_name,
        "detail": clean_detail,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_key": clean_source_key,
        "role_id": role_id,
    }
    games.append(record)

    pending_indexes = [
        index
        for index, item in enumerate(games)
        if isinstance(item, dict) and item.get("guild_id") == guild_id and item.get("published_at") is None
    ]
    for index in pending_indexes[:-MAX_PENDING_GAMES]:
        games[index]["published_at"] = "discarded"

    atomic_write_json(path, state)
    return PendingGame(**record)


def game_name_from_forum(name: str) -> str:
    clean_name = name.strip()
    if clean_name.endswith("-專區"):
        clean_name = clean_name[:-3].rstrip("- ")
    return clean_name or name.strip()


def _version_label(value: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        return ""
    return clean_value if clean_value.casefold().startswith("v") else f"v{clean_value}"


def _bullet_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("•", "-", "*")):
            line = line[1:].strip()
        lines.append(f"• {line}")
    return lines


def build_announcement_text(
    draft: AnnouncementDraft,
    *,
    games: list[PendingGame] | None = None,
) -> str:
    title = "📣 **Con9sole 更新公告"
    version = _version_label(draft.version)
    if version:
        title += f" — {version}"
    title += "**"

    sections = [title]
    if draft.announcement_date.strip():
        sections.append(f"📅 **{draft.announcement_date.strip()}**")

    feature_lines = _bullet_lines(draft.body)
    if draft.kind == "game":
        selected_ids = set(draft.game_ids)
        selected_games = [game for game in games or [] if game.id in selected_ids]
        feature_lines.extend(f"• **{game.name}**｜{game.detail}" for game in selected_games)
    if feature_lines:
        sections.append("🆕 **新功能**\n" + "\n".join(feature_lines))

    return "\n\n".join(sections)


def get_pending_games(
    guild_id: int,
    *,
    path: Path = GAME_ANNOUNCEMENTS_PATH,
) -> list[PendingGame]:
    state = _load_state(path)
    records = [
        pending
        for item in state["games"]
        if (pending := _as_pending_game(item, guild_id=guild_id)) is not None
    ]
    return records[-MAX_PENDING_GAMES:]


def mark_games_published(
    guild_id: int,
    game_ids: tuple[str, ...],
    *,
    message_id: int,
    path: Path = GAME_ANNOUNCEMENTS_PATH,
) -> None:
    if not game_ids:
        return

    selected_ids = set(game_ids)
    state = _load_state(path)
    published_at = datetime.now(timezone.utc).isoformat()
    changed = False
    for item in state["games"]:
        if (
            isinstance(item, dict)
            and item.get("guild_id") == guild_id
            and item.get("id") in selected_ids
            and item.get("published_at") is None
        ):
            item["published_at"] = published_at
            item["published_message_id"] = message_id
            changed = True
    if changed:
        atomic_write_json(path, state)


def game_draft_from_pending(games: list[PendingGame], *, intro: str = "") -> AnnouncementDraft:
    if not games:
        raise ValueError("暫時冇待公告的新遊戲。")

    clean_intro = intro.strip() or "以下遊戲專區已準備好，歡迎入嚟一齊玩。"
    return AnnouncementDraft(
        kind="game",
        title="🎮 遊戲專區更新",
        body=clean_intro,
        game_ids=tuple(game.id for game in games),
    )


def build_announcement_embed(
    draft: AnnouncementDraft,
    *,
    games: list[PendingGame] | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=draft.title.strip(), description=draft.body.strip(), color=UPDATE_PUBLISHER_COLOR)
    if draft.kind == "game":
        selected_ids = set(draft.game_ids)
        selected_games = [game for game in games or [] if game.id in selected_ids]
        if selected_games:
            lines = [f"• **{game.name}**｜{game.detail}" for game in selected_games]
            chunks: list[str] = []
            current_lines: list[str] = []
            current_length = 0
            for line in lines:
                safe_line = line[:1024]
                additional_length = len(safe_line) + (1 if current_lines else 0)
                if current_lines and current_length + additional_length > 1024:
                    chunks.append("\n".join(current_lines))
                    current_lines = []
                    current_length = 0
                current_lines.append(safe_line)
                current_length += len(safe_line) + (1 if len(current_lines) > 1 else 0)
            if current_lines:
                chunks.append("\n".join(current_lines))

            for index, chunk in enumerate(chunks):
                field_name = "新增項目" if index == 0 else "新增項目（續）"
                embed.add_field(name=field_name, value=chunk, inline=False)
        embed.set_footer(text="Con9sole｜遊戲專區更新")
    else:
        embed.set_footer(text="Con9sole｜功能更新")
    return embed
