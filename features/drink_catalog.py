from __future__ import annotations

import random
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

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


def current_seasonal_pool() -> list[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return list(pool)
    return []


def pick_rarity() -> str:
    labels = list(RARITY_STYLE.keys())
    weights = [RARITY_STYLE[label]["weight"] for label in labels]
    return random.choices(labels, weights=weights, k=1)[0]


def build_pool_for_rarity(rarity: str) -> list[DrinkEntry]:
    pool = [drink for drink in ALL_DRINKS if drink.rarity == rarity]
    seasonal = [drink for drink in current_seasonal_pool() if drink.rarity == rarity]
    return pool + seasonal


def pick_weighted_drink(*, rarity: str, recent_drink_names: set[str]) -> DrinkEntry:
    pool = build_pool_for_rarity(rarity)
    if not pool:
        pool = ALL_DRINKS + current_seasonal_pool()

    weights = [1 if drink.eng in recent_drink_names else 4 for drink in pool]
    return random.choices(pool, weights=weights, k=1)[0]


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
