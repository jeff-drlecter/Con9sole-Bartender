"""Bounded, read-only RSS shadow trial. No Discord delivery or translation code."""
from __future__ import annotations

import hashlib
import html
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

TRIAL_SECONDS = 3 * 86400
MAX_BYTES = 2 * 1024 * 1024
SOURCES = (
    ("4gamers", "https://www.4gamers.com.tw/rss/news/c/2", 1364210080043630612),
    ("xbox", "https://news.xbox.com/en-us/feed/", 1379699174668505098),
    ("ps", "https://blog.zh-hant.playstation.com/feed/", 1364201334798290994),
)
# Steam intentionally excluded: manually disabled in the audited configuration.
TITLE_PATTERN = r"steam|限免|免費|免費週末|限免|免費|限時免費|玩家"
SUMMARY_PATTERN = r"遊戲|steam|玩家|PC|epic|RPG|手遊|Game"


def parse_date(value: str) -> float | None:
    try:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(body: bytes) -> list[dict]:
    if len(body) > MAX_BYTES or b'\x00' in body or re.search(br"<!\s*(DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("oversize feed or prohibited XML declaration")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("invalid XML") from exc
    # Reject HTML/error pages instead of silently treating them as empty feeds.
    local = lambda tag: tag.rsplit("}", 1)[-1]
    if local(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("response is not RSS/Atom")
    result = []
    for item in root.iter():
        if local(item.tag) not in {"item", "entry"}:
            continue
        values = {}
        for child in item:
            key = local(child.tag)
            value = "".join(child.itertext()).strip()
            if key == "link" and child.attrib.get("rel", "alternate") == "alternate":
                value = child.attrib.get("href", value)
            values.setdefault(key, value)
        title = values.get("title", "")[:1000]
        summary = html.unescape(re.sub(r"<[^>]*>", "", values.get("description", values.get("summary", ""))))[:8000]
        link = values.get("link", "")[:2000]
        identity = values.get("guid") or values.get("id") or link
        if not identity:
            raise ValueError("article has no stable identity")
        result.append({"key": hashlib.sha256(identity.encode()).hexdigest(),
                       "title": title, "summary": summary, "link": link,
                       "published": parse_date(values.get("pubDate", values.get("published", values.get("updated", ""))))})
        if len(result) > 500:
            raise ValueError("too many articles in one response")
    return result


def decision(source: str, article: dict, now: float) -> str:
    published = article["published"]
    if published is None:
        return "missing_date"
    if published < now - 86400:
        return "older_than_1_day"
    if published > now + 300:
        return "future_date"
    if source == "4gamers" and not (
        re.search(TITLE_PATTERN, article["title"]) or re.search(SUMMARY_PATTERN, article["summary"])
    ):
        return "filtered"
    return "would_deliver"


class TrialStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS articles (
                    source TEXT, key TEXT, title TEXT, link TEXT, decision TEXT,
                    seen REAL, PRIMARY KEY (source,key));
                CREATE TABLE IF NOT EXISTS polls (
                    at REAL, source TEXT, status TEXT, bytes INTEGER, seconds REAL,
                    rss_bytes INTEGER, peak_bytes INTEGER, new_count INTEGER,
                    resolved_url TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO meta VALUES ('start', ?)", (time.time(),))

    def connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def active(self, now=None):
        with self.connect() as db:
            start = db.execute("SELECT value FROM meta WHERE key='start'").fetchone()[0]
        return (time.time() if now is None else now) < start + TRIAL_SECONDS

    def record(self, source, articles, *, status="ok", size=0, seconds=0,
               rss_bytes=0, peak_bytes=0, resolved_url="", now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            baseline = db.execute("SELECT value FROM meta WHERE key=?", ("baseline:" + source,)).fetchone() is None
            count = 0
            for a in articles:
                verdict = "baseline" if baseline else decision(source, a, now)
                cursor = db.execute("INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?)",
                                    (source, a["key"], a["title"], a["link"], verdict, now))
                count += cursor.rowcount
            if status == "ok":
                db.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", ("baseline:" + source, now))
            db.execute("INSERT INTO polls VALUES (?,?,?,?,?,?,?,?,?)",
                       (now, source, status[:240], size, seconds, rss_bytes, peak_bytes, count, resolved_url[:2000]))
        return count

    def report(self):
        with self.connect() as db:
            return {
                "start": db.execute("SELECT value FROM meta WHERE key='start'").fetchone()[0],
                "decisions": db.execute("SELECT source,decision,count(*) FROM articles GROUP BY source,decision").fetchall(),
                "polls": db.execute("SELECT source,count(*),sum(bytes),max(rss_bytes),max(peak_bytes),sum(status NOT IN ('ok','not_modified')) FROM polls GROUP BY source").fetchall(),
                "recent": db.execute("SELECT source,title,decision FROM articles ORDER BY seen DESC LIMIT 5").fetchall(),
            }
