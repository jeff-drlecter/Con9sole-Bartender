from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

import sqlite3

from data.drink_data import (
    ALL_DRINKS,
    RARITY_STYLE,
    SEASONAL_DRINKS,
    TASTING_LINES,
    DrinkEntry,
)


def drink_catalog() -> dict[str, DrinkEntry]:
    """Return every known drink keyed by English name.

    Seasonal drinks are included, but existing base-catalog names win if duplicated.
    """
    catalog: dict[str, DrinkEntry] = {}
    for drink in ALL_DRINKS:
        catalog.setdefault(drink.eng, drink)

    for pool in SEASONAL_DRINKS.values():
        for drink in pool:
            catalog.setdefault(drink.eng, drink)

    return catalog


def catalog_by_rarity() -> dict[str, list[DrinkEntry]]:
    """Group all catalog drinks by rarity and sort each group consistently."""
    grouped: dict[str, list[DrinkEntry]] = {rarity: [] for rarity in RARITY_STYLE.keys()}
    for drink in drink_catalog().values():
        grouped.setdefault(drink.rarity, []).append(drink)

    for drinks in grouped.values():
        drinks.sort(key=lambda item: (item.eng.casefold(), item.zh.casefold()))
    return grouped


def progress_bar(current: int, total: int, *, size: int = 10) -> str:
    if total <= 0:
        return "░" * size
    filled = max(0, min(size, round((current / total) * size)))
    return "█" * filled + "░" * (size - filled)


def rarity_label(rarity: str) -> str:
    meta = RARITY_STYLE.get(rarity, {})
    emoji = str(meta.get("emoji", "🍸"))
    label = str(meta.get("label", rarity))
    return f"{emoji} {label}"


def rarity_color(rarity: str) -> int:
    meta = RARITY_STYLE.get(rarity, {})
    try:
        return int(meta.get("color", 0x2B2D31))
    except Exception:
        return 0x2B2D31


def format_collection_row(row: sqlite3.Row | Mapping[str, Any]) -> str:
    flags: list[str] = []
    if int(row["self_count"] or 0) > 0:
        flags.append("🍹")
    if int(row["received_count"] or 0) > 0:
        flags.append("🍷")
    if int(row["given_count"] or 0) > 0:
        flags.append("🥂")

    flag_text = "".join(flags) or "✅"
    return f"{flag_text} **{row['drink_eng']}（{row['drink_zh']}）**"


def build_tasting_note(drink: DrinkEntry) -> str:
    base = drink.desc.rstrip("。")
    return f"{base}。{random.choice(TASTING_LINES)}"
