"""Offline intake of reviewed FC 27 metadata. No HTTP, scheduler or Discord sender."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote

from core.gta_translation import FC_CHANNEL_ID, LEASE_SECONDS, TranslationQueue, reserve_translation
from core.rss_trial import MAX_BYTES
from core.sqlite_storage import connect_sqlite

NEWS = "https://www.ea.com/games/ea-sports-fc/fc-27/news/"
HUB = "https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/"
NEWS_URL = re.compile(re.escape(NEWS) + r"[a-z0-9]+(?:-[a-z0-9]+)*")
HUB_URL = re.compile(re.escape(HUB) + r"(?:[a-z0-9-]|%E2%84%A2)+/[1-9][0-9]*")


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    brief: str
    author: str
    rank: str = ""
    canonical: str = ""
    demo_text: str = ""

    def identity(self, source: str) -> str:
        # Adapters must supply original-article bylines and evidence for canonical
        # equivalence. The fixture is reviewed by hand. Related links aren't aliases.
        if source == "news":
            trusted = NEWS_URL.fullmatch(self.url) and self.author == "EA SPORTS"
        elif source == "hub":
            trusted = (HUB_URL.fullmatch(self.url) and self.author == "EA_Vendcera"
                       and self.rank == "Community Manager")
        else:
            raise ValueError("Unknown FC 27 source")
        if not trusted:
            raise ValueError("Unverified FC 27 article location or publisher")
        if self.canonical and (source != "hub" or not NEWS_URL.fullmatch(self.canonical)):
            raise ValueError("Invalid official canonical article")
        for text, limit in ((self.title, 160), (self.brief, 360), (self.demo_text, 100)):
            if len(text) > limit or any(c in text for c in "\r\n@<>[]") or "://" in text:
                raise ValueError("Expected short plain metadata")
        if not self.title.strip() or not self.brief.strip():
            raise ValueError("Missing FC 27 article metadata")
        release = re.fullmatch(r"EA SPORTS FC™? 27 \| Title Update v(\d+\.\d+(?:\.\d+)?)( Pitch Notes)?",
                               self.title, re.I)
        if release:
            version = release[1] if release[1].count(".") == 2 else release[1] + ".0"
            kind = "pitch" if release[2] else "patch"
            return f"fc27/{kind}/{version}"
        # Unclassified forum stories need reviewed cross-publication evidence.
        # A matching version, thumbnail, related link or similar title is insufficient.
        if source == "hub" and not self.canonical:
            raise ValueError("Forum article needs a verified canonical identity")
        return self.canonical or self.url


class PreviewLedger:
    """Single shared DB for direct receipts and the existing nine-channel budget."""

    def __init__(self, path: Path):
        self.path = path
        TranslationQueue(path)  # initialize/migrate the existing shared usage ledger
        with connect_sqlite(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fc27_preview (
                identity TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, brief TEXT NOT NULL,
                demo_text TEXT NOT NULL, state TEXT NOT NULL, claimed REAL, summary TEXT
            )""")

            db.execute("CREATE TABLE IF NOT EXISTS fc27_poll (slot INTEGER PRIMARY KEY, next_poll REAL NOT NULL)")

    def reserve_poll(self, now: float) -> bool:
        with connect_sqlite(self.path) as db:
            return bool(db.execute(
                "INSERT INTO fc27_poll VALUES (1,?) ON CONFLICT(slot) DO UPDATE SET next_poll=excluded.next_poll "
                "WHERE fc27_poll.next_poll<=?", (now + 3600, now),
            ).rowcount)

    def ingest(self, news: list[Article], hub: list[Article]) -> int:
        # No state changes if one index is missing, empty, oversized or untrusted.
        # Source adapters have to validate completeness before calling this method.
        items = []
        for source, records in (("news", news), ("hub", hub)):
            if not 1 <= len(records) <= 100:
                raise ValueError(f"Invalid {source} index snapshot")
            for article in records:
                items.append((article.identity(source), article, source))
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            baseline = db.execute("SELECT 1 FROM fc27_preview LIMIT 1").fetchone() is None
            added = 0
            for identity, article, source in items:
                url = article.canonical or article.url
                added += db.execute(
                    "INSERT OR IGNORE INTO fc27_preview(identity,url,title,brief,demo_text,state) VALUES (?,?,?,?,?,?)",
                    (identity, url, article.title, article.brief, article.demo_text, "baseline" if baseline else "pending"),
                ).rowcount
                if source == "news":
                    # A later website mirror improves the stored source without
                    # resetting its receipt or changing the translated brief.
                    db.execute("UPDATE fc27_preview SET url=?,demo_text=? WHERE url=? OR (identity=? AND url LIKE ?)",
                               (url, article.demo_text, url, identity, HUB + "%"))
            return 0 if baseline else added

    def claim(self, now: float) -> tuple[str, str] | None:
        """One translation attempt per canonical article, even after a crash."""
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE fc27_preview SET state='ready' WHERE state='translating' AND claimed<=?",
                       (now - LEASE_SECONDS,))
            pending = db.execute("SELECT identity,brief FROM fc27_preview WHERE state='pending' ORDER BY identity")
            for identity, brief in pending.fetchall():
                if reserve_translation(db, now, brief, FC_CHANNEL_ID):
                    db.execute("UPDATE fc27_preview SET state='translating',claimed=? WHERE identity=?", (now, identity))
                    return identity, brief
                db.execute("UPDATE fc27_preview SET state='ready' WHERE identity=?", (identity,))
            return None

    def finish(self, identity: str, summary: str | None) -> None:
        if summary and (len(summary) > 500 or any(c in summary for c in "@<>[]\r\n") or "://" in summary):
            summary = None
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE fc27_preview SET state='ready',summary=? WHERE identity=? AND state='translating'",
                       (summary, identity))

    def cards(self) -> list[str]:
        with connect_sqlite(self.path) as db:
            rows = db.execute("SELECT url,title,demo_text,summary FROM fc27_preview WHERE state='ready' ORDER BY url")
            cards = []
            for url, title, demo_text, summary in rows:
                lines = [title, summary or "繁中摘要暫未提供，可先查看英文官方原文。", f"[英文官方原文]({url})"]
                if demo_text:
                    lines.append(f"[查看原文中的示範]({url}#:~:text={quote(demo_text, safe='')})")
                cards.append("\n".join(lines))
            return cards


async def poll_indexes(ledger, now, open_stream, parse_index, *, sleep=asyncio.sleep):
    """Poll an injected transport. No live transport is configured in this version."""
    if not ledger.reserve_poll(now):
        return None
    snapshots = {}
    for source in ("news", "hub"):
        for attempt in range(3):
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    async with open_stream(source) as chunks:
                        async for chunk in chunks:
                            if len(body) + len(chunk) > MAX_BYTES:
                                raise ValueError(f"{source} index exceeds byte limit")
                            body.extend(chunk)
                break
            except (TimeoutError, ConnectionError):
                if attempt == 2:
                    raise
                await sleep(2 ** attempt)
        # Non-transient errors abort the whole snapshot, preserving the baseline.
        snapshots[source] = parse_index(source, body)
    return ledger.ingest(snapshots["news"], snapshots["hub"])
