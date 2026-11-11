"""Durable, opt-in RSS delivery queue. No network or Discord calls here."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from urllib.parse import urlsplit

from core.rss_trial import SOURCES, decision

SOURCE_IDS = frozenset(source for source, _, _ in SOURCES)
DAILY_CAP = 50
MAX_ATTEMPTS = 5


def enabled_sources(raw: str) -> frozenset[str]:
    selected = frozenset(x.strip() for x in raw.split(",") if x.strip())
    if selected - SOURCE_IDS:
        raise ValueError("RSS_DELIVERY_SOURCES contains unknown sources")
    return selected


def safe_link(link: str) -> bool:
    try:
        u = urlsplit(link)
        return u.scheme == "https" and bool(u.hostname) and not u.username and not u.password
    except ValueError:
        return False


class DeliveryStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS baseline (source TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS articles (
                    source TEXT, key TEXT, title TEXT, summary TEXT, link TEXT,
                    published REAL, state TEXT, attempts INTEGER DEFAULT 0,
                    next_attempt REAL DEFAULT 0, detail TEXT DEFAULT '',
                    PRIMARY KEY (source,key));
                CREATE TABLE IF NOT EXISTS attempts (source TEXT, at REAL);
                CREATE INDEX IF NOT EXISTS attempts_time ON attempts(source,at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, source, articles, now):
        if source not in SOURCE_IDS:
            raise ValueError("unknown source")
        added = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            baseline = db.execute("SELECT 1 FROM baseline WHERE source=?", (source,)).fetchone() is None
            for a in articles:
                state = "baseline" if baseline else decision(source, a, now)
                if not safe_link(a["link"]):
                    state = "invalid_link"
                if state == "would_deliver":
                    state = "pending"
                cur = db.execute("INSERT OR IGNORE INTO articles (source,key,title,summary,link,published,state) VALUES (?,?,?,?,?,?,?)",
                                 (source,a["key"],a["title"],a["summary"],a["link"],a["published"],state))
                added += cur.rowcount if state == "pending" else 0
            db.execute("INSERT OR IGNORE INTO baseline VALUES (?)", (source,))
        return added

    def claim(self, source, now):
        """Reserve before sending. A crash leaves 'sending'; never auto-resend it."""
        if source not in SOURCE_IDS:
            raise ValueError("unknown source")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE at<=?", (now-86400,))
            db.execute("UPDATE articles SET state='expired' WHERE state IN ('pending','retry') AND published<?", (now-86400,))
            count = db.execute("SELECT count(*) FROM attempts WHERE source=?", (source,)).fetchone()[0]
            if count >= DAILY_CAP:
                return None
            row = db.execute("SELECT * FROM articles WHERE source=? AND state IN ('pending','retry') AND next_attempt<=? ORDER BY published,key LIMIT 1", (source,now)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE articles SET state='sending',attempts=attempts+1 WHERE source=? AND key=?", (source,row['key']))
            db.execute("INSERT INTO attempts VALUES (?,?)", (source,now))
            return dict(row)

    def finish(self, source, key, outcome, now, detail="", retry_after=60):
        if outcome not in {"sent","retry","failed","uncertain"}:
            raise ValueError("invalid outcome")
        with self.connect() as db:
            row = db.execute("SELECT attempts,state FROM articles WHERE source=? AND key=?", (source,key)).fetchone()
            if row is None or row['state'] != 'sending':
                raise ValueError("article was not claimed")
            if outcome == "retry" and row['attempts'] >= MAX_ATTEMPTS:
                outcome = "failed"
            delay = max(60, min(3600, retry_after), min(1800, 60 * 2 ** (row['attempts']-1)))
            db.execute("UPDATE articles SET state=?,next_attempt=?,detail=? WHERE source=? AND key=?",
                       (outcome,now+delay,detail[:240],source,key))

    def report(self):
        with self.connect() as db:
            return [tuple(row) for row in db.execute("SELECT source,state,count(*) FROM articles GROUP BY source,state")]
