"""Frozen v1 collections. All writes share the drink ownership transaction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from features.collection_milestones import guild_key

STYLE_LABELS = {
    "short": "調酒系",
    "tropical": "熱帶系",
    "sparkling": "氣泡系",
    "beer": "薑味／騾子系",
    "whisky": "醇厚系",
}


@dataclass(frozen=True)
class ThemeDrink:
    eng: str
    zh: str
    typ: str
    rarity: str
    classic: bool


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    emoji: str
    targets: tuple[int, ...]
    title: str
    drinks: tuple[ThemeDrink, ...]
    by_style: bool = False

    @property
    def unit(self) -> str:
        return "類" if self.by_style else "款"

    def owned(self, names: set[str]) -> list[ThemeDrink]:
        return [d for d in self.drinks if d.eng in names]

    def count(self, names: set[str]) -> int:
        owned = self.owned(names)
        return len({d.typ for d in owned}) if self.by_style else len(owned)

    def award_id(self, target: int) -> str:
        return f"theme:v1:{self.key}:{target}"


@lru_cache(maxsize=1)
def themes() -> tuple[Theme, ...]:
    path = Path(__file__).resolve().parents[1] / "assets/theme_collections_v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["version"] != 1:
        raise ValueError("Unsupported theme manifest version")
    drinks = tuple(ThemeDrink(*row) for row in data["drinks"])
    if len({d.eng for d in drinks}) != len(drinks):
        raise ValueError("Duplicate theme drink identity")
    return (
        Theme(
            "starter",
            "吧枱初體驗",
            "🍸",
            (3, 5),
            "吧枱探索家",
            tuple(d for d in drinks if d.typ in STYLE_LABELS),
            True,
        ),
        Theme(
            "tropical",
            "熱帶假期",
            "🌴",
            (3, 10, 25),
            "熱帶漫遊者",
            tuple(d for d in drinks if d.typ == "tropical"),
        ),
        Theme(
            "classics",
            "經典巡禮",
            "🥃",
            (1, 3, 10),
            "經典收藏家",
            tuple(d for d in drinks if d.classic),
        ),
    )


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_theme_awards (
        guild_key TEXT NOT NULL, user_id INTEGER NOT NULL, award_id TEXT NOT NULL,
        theme_key TEXT NOT NULL, target INTEGER NOT NULL, label TEXT NOT NULL,
        unlocked_at TEXT NOT NULL, backfilled INTEGER NOT NULL,
        pending INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(guild_key, user_id, award_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drink_theme_preferences (
        guild_key TEXT NOT NULL, user_id INTEGER NOT NULL, theme_key TEXT NOT NULL,
        PRIMARY KEY(guild_key, user_id))""")


def reconcile(
    conn: sqlite3.Connection,
    guild_id: int | None,
    user_id: int,
    *,
    backfill: bool = True,
) -> list[dict]:
    key = guild_key(guild_id)
    names = {
        r[0]
        for r in conn.execute(
            "SELECT drink_eng FROM drink_collection WHERE guild_key=? AND user_id=?",
            (key, user_id),
        )
    }
    now = datetime.now(UTC).isoformat()
    added = []
    for theme in themes():
        count = theme.count(names)
        for target in theme.targets:
            if count < target:
                continue
            stage = (
                "精通"
                if target == theme.targets[-1]
                else "入門完成"
                if target == theme.targets[0]
                else "進階"
            )
            label = f"{theme.label} · {stage}"
            award_id = theme.award_id(target)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO drink_theme_awards VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (key, user_id, award_id, theme.key, target, label, now, int(backfill)),
            )
            if cursor.rowcount:
                added.append({"award_id": award_id, "label": label})
    return added


def title_awards(
    conn: sqlite3.Connection, guild_id: int | None, user_id: int
) -> list[dict]:
    """Adapt mastered themes to the shared selector without polluting legacy awards.

    Older releases can safely read their milestone table on rollback. A selected
    theme title is retained in the selection table but hidden by an older release.
    """
    mastered = {t.award_id(t.targets[-1]): t for t in themes()}
    result = []
    for award_id, unlocked_at in conn.execute(
        "SELECT award_id, unlocked_at FROM drink_theme_awards WHERE guild_key=? AND user_id=?",
        (guild_key(guild_id), user_id),
    ):
        theme = mastered.get(award_id)
        if theme:
            result.append(
                {
                    "milestone_id": award_id,
                    "label": theme.title,
                    "target": theme.targets[-1],
                    "catalog_total": None,
                    "unlocked_at": unlocked_at,
                }
            )
    return result


def snapshot(guild_id: int | None, user_id: int) -> dict:
    from features import drink_storage as storage

    storage.init_drink_events_db()
    with storage.connect_sqlite(storage.STATS_DB) as conn:
        conn.execute("BEGIN IMMEDIATE")
        reconcile(conn, guild_id, user_id)
        key = guild_key(guild_id)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT drink_eng FROM drink_collection WHERE guild_key=? AND user_id=?",
                (key, user_id),
            )
        }
        conn.row_factory = sqlite3.Row
        awards = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM drink_theme_awards WHERE guild_key=? AND user_id=? ORDER BY unlocked_at, theme_key, target",
                (key, user_id),
            )
        ]
        row = conn.execute(
            "SELECT theme_key FROM drink_theme_preferences WHERE guild_key=? AND user_id=?",
            (key, user_id),
        ).fetchone()
    return {
        "names": names,
        "awards": awards,
        "tracked": row[0] if row else None,
        "pending": [a for a in awards if a["pending"]],
    }


def acknowledge(guild_id: int | None, user_id: int, award_ids: list[str]) -> None:
    """Only acknowledge the exact notices successfully delivered, never newer ones."""
    from features import drink_storage as storage

    with storage.connect_sqlite(storage.STATS_DB) as conn:
        conn.executemany(
            "UPDATE drink_theme_awards SET pending=0 WHERE guild_key=? AND user_id=? AND award_id=?",
            [(guild_key(guild_id), user_id, a) for a in award_ids],
        )


def track(guild_id: int | None, user_id: int, theme_key: str | None) -> bool:
    from features import drink_storage as storage

    if theme_key is not None and theme_key not in {t.key for t in themes()}:
        return False
    storage.init_drink_events_db()
    with storage.connect_sqlite(storage.STATS_DB) as conn:
        if theme_key is None:
            conn.execute(
                "DELETE FROM drink_theme_preferences WHERE guild_key=? AND user_id=?",
                (guild_key(guild_id), user_id),
            )
        else:
            conn.execute(
                """INSERT INTO drink_theme_preferences VALUES (?, ?, ?)
                ON CONFLICT(guild_key,user_id) DO UPDATE SET theme_key=excluded.theme_key""",
                (guild_key(guild_id), user_id, theme_key),
            )
    return True


def next_target(theme: Theme, state: dict) -> int | None:
    owned = {a["award_id"] for a in state["awards"]}
    return next((n for n in theme.targets if theme.award_id(n) not in owned), None)


def recommended(state: dict) -> Theme:
    tracked = next((t for t in themes() if t.key == state["tracked"]), None)
    if tracked:
        return tracked
    # Finish one approachable entry tier before suggesting a long-term collection.
    ids = {a["award_id"] for a in state["awards"]}
    return next(
        (t for t in themes() if t.award_id(t.targets[0]) not in ids),
        next((t for t in themes() if next_target(t, state) is not None), themes()[0]),
    )


def notice_text(awards: list[dict]) -> str:
    if not awards:
        return ""
    old = [a for a in awards if a.get("backfilled")]
    new = [a for a in awards if not a.get("backfilled")]
    lines = []
    if old:
        lines.append(f"舊收藏已補計 **{len(old)} 個階段**，唔使重新儲。")
    if new:
        lines.append("🎉 主題達標：" + "、".join(a["label"] for a in new))
    lines.append("精通稱號可到「里程碑」選用；目前稱號會保留。")
    return "\n".join(lines)
