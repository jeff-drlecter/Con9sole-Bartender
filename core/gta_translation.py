"""Durable queue and character reservations for the single GTA translation pilot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from core.sqlite_storage import connect_sqlite


GTA_CHANNEL_ID = 1460576839385743493
MONTHLY_LIMIT = 450_000
HONG_KONG = ZoneInfo("Asia/Hong_Kong")
LEASE_SECONDS = 300
MAX_ATTEMPTS = 3

# Discord uses both [label](url) and [label](<url>). Angle brackets delimit
# the exact destination even when the URL contains parentheses.
MENTION = r"<[@#][!&]?\d+>|(?<![\w@])@(?:Announcements|公告)(?![\w-])"
SOURCE_TOKEN = re.compile(
    r"\[(?P<label>[^\]\n]+)\]\((?:<(?P<masked_angle>https?://[^\s<>]+)>|"
    r"(?P<masked>https?://(?:[^\s<>()]|\([^\s<>()]*\))+))\)"
    r"|<(?P<angle>https?://[^\s<>]+)>|(?P<bare>https?://[^\s<>]+)"
    rf"|{MENTION}", re.I
)
LABEL_METADATA = re.compile(rf"{MENTION}|https?://\S+|(?:[\w-]+\.)+[a-z]{{2,}}\b(?:[/:?#]\S*)?", re.I)
LOCAL_LINK = re.compile(r"<(https?://[^\s<>]+)>", re.I)
# A music CTA is a single clickable action in the translated post.
LINK_ACTION = re.compile(r"(?P<listen>\bListen[ \t]+now[ \t]*[:：][ \t]*)?(?P<link><https?://[^\s<>]+>)", re.I)


def _local_token(match: re.Match) -> str:
    url = match["masked_angle"] or match["masked"] or match["angle"] or match["bare"]
    if not url:
        return ""
    suffix = ""
    if match["bare"]:
        # In prose the closing parenthesis and punctuation can belong to the sentence.
        while url and (url[-1] in ".,!;:，。！？；：" or
                       (url[-1] == ")" and url.count(")") > url.count("("))):
            suffix = url[-1] + suffix
            url = url[:-1]
    label = LABEL_METADATA.sub("", match["label"] or "").strip()
    # URL-shaped labels (including bare hosts) aren't prose for Google to translate.
    if label:
        return f"{label} <{url}>{suffix}"
    return f"<{url}>{suffix}"


def translation_input(text: str) -> tuple[str, dict[str, str]]:
    """Keep source URLs on the Bot; markers retain their positions during translation."""
    prefix = "GTALINK"
    while prefix.lower() in text.lower():
        prefix += "X"
    links = {}

    def mark(match: re.Match) -> str:
        marker = f"{prefix}{len(links)}Z"
        link = match["link"]
        links[marker] = f"[立即收聽]({link})" if match["listen"] else link
        return marker

    return LINK_ACTION.sub(mark, text), links


def next_month_start(local: datetime) -> float:
    return datetime(local.year + (local.month == 12), local.month % 12 + 1,
                    1, tzinfo=HONG_KONG).timestamp()


def source_text(message) -> str:
    """Only visible text on the post. Do not retrieve linked articles or media."""
    parts = [message.content]
    for embed in message.embeds:
        parts.extend((embed.title, embed.description))
        for field in embed.fields:
            parts.extend((field.name, field.value))
    distinct = {}
    for part in parts:
        if part:
            lines = SOURCE_TOKEN.sub(_local_token, part).splitlines()
            cleaned = "\n".join(line.rstrip() for line in lines).strip()
            if cleaned:
                distinct[cleaned] = None
    text = "\n\n".join(distinct)
    return text if any(ch.isalnum() for ch in LOCAL_LINK.sub("", text)) else ""


@dataclass(frozen=True)
class Job:
    message_id: int
    stage: str
    attempt: int
    text: str


class TranslationQueue:
    def __init__(self, path: Path):
        self.path = path
        with connect_sqlite(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS posts (
                    message_id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL UNIQUE,
                    stage TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pending_posts ON posts(stage, available);
                CREATE TABLE IF NOT EXISTS usage (
                    month TEXT PRIMARY KEY, characters INTEGER NOT NULL
                );
            """)

    def add(self, message_id: int, source_id: int, body: str) -> None:
        with connect_sqlite(self.path) as db:
            db.execute("INSERT OR IGNORE INTO posts(message_id,source_id,stage,body) "
                       "VALUES (?,?,'translate',?)", (message_id, source_id, body))

    def claim(self, now: float) -> Job | None:
        # Single transaction across processes: check the budget and debit BEFORE HTTP.
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE posts SET stage='failed',body='' WHERE stage IN ('translate','deliver') "
                       "AND attempt>=? AND available<=?", (MAX_ATTEMPTS, now))
            row = db.execute("SELECT message_id,stage,attempt,body FROM posts "
                             "WHERE stage IN ('deliver','translate') AND available<=? "
                             "ORDER BY stage, message_id LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            message_id, stage, attempt, body = row
            if stage == "translate":
                local = datetime.fromtimestamp(now, HONG_KONG)
                month = local.strftime("%Y-%m")
                db.execute("INSERT OR IGNORE INTO usage VALUES (?,0)", (month,))
                provider_text, _ = translation_input(body)
                characters = len(provider_text)
                debited = db.execute("UPDATE usage SET characters=characters+? "
                                     "WHERE month=? AND characters+?<=?",
                                     (characters, month, characters, MONTHLY_LIMIT)).rowcount
                if not debited:
                    db.execute("UPDATE posts SET available=? WHERE message_id=?",
                               (next_month_start(local), message_id))
                    return None
            db.execute("UPDATE posts SET attempt=attempt+1,available=? WHERE message_id=?",
                       (now + LEASE_SECONDS, message_id))
            return Job(message_id, stage, attempt + 1, body)

    def defer_quota(self, job: Job, reason: str, now: float) -> None:
        retry = (next_month_start(datetime.fromtimestamp(now, HONG_KONG))
                 if reason == "month_full" else now + 86400)
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE posts SET available=?,attempt=0 WHERE message_id=? "
                       "AND stage='translate' AND attempt=?", (retry, job.message_id, job.attempt))

    def advance(self, job: Job, stage: str, body: str = "") -> bool:
        # A late reply from an expired attempt cannot publish or overwrite its successor.
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE posts SET stage=?,body=?,attempt=0,available=0 "
                                   "WHERE message_id=? AND stage=? AND attempt=?",
                                   (stage, body, job.message_id, job.stage, job.attempt)).rowcount)

    def sent(self, message_id: int) -> None:
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE posts SET stage='sent',body='' WHERE message_id=? AND stage='posting'",
                       (message_id,))

    def start_posting(self, job: Job) -> bool:
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE posts SET stage='posting' "
                                   "WHERE message_id=? AND stage='deliver' AND attempt=?",
                                   (job.message_id, job.attempt)).rowcount)

    def rejected(self, job: Job) -> None:
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE posts SET stage='deliver' WHERE message_id=? AND stage='posting' "
                       "AND attempt=?", (job.message_id, job.attempt))
