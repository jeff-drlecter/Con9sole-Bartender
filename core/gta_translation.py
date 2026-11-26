"""Shared delivery receipts and translation quota for official game updates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from core.sqlite_storage import connect_sqlite


GTA_CHANNEL_ID = 1460576839385743493
FC_CHANNEL_ID = 1424226055446593556
APEX_CHANNEL_ID = 1464858693014392924
OFFICIAL_UPDATE_CHANNELS = {
    GTA_CHANNEL_ID: "GTA",
    FC_CHANNEL_ID: "EA SPORTS FC",
    1424320426095415397: "NBA 2K",
    1426660324827857020: "Delta Force",
    1426669343160406056: "Helldivers 2",
    1426670580714836149: "Monster Hunter",
    1433362456456990811: "Battlefield 6",
    1440622034597052526: "Where Winds Meet",
    APEX_CHANNEL_ID: "Apex Legends",
}
MONTHLY_LIMIT = 450_000


class TranslationLimit(Exception):
    """The shared provider refused this request under its usage quota."""


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
GENERIC_VEHICLE = re.compile(
    r"\ba vehicle(?=\s+and\s+\d+\s+(?:bonus\s+)?(?:prizes?|rewards?)\b)", re.I
)
VEHICLE_MARKER = "GTA0V"


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


def translation_input(text: str, channel_id: int = GTA_CHANNEL_ID) -> tuple[str, dict[str, str]]:
    """Build the exact payload for both quota reservation and the provider request."""
    prefix = "GTALINK"
    while prefix.lower() in text.lower():
        prefix += "X"
    replacements = {}

    def mark(match: re.Match) -> str:
        marker = f"{prefix}{len(replacements)}Z"
        link = match["link"]
        replacements[marker] = f"[立即收聽]({link})" if match["listen"] else link
        return marker

    source = LINK_ACTION.sub(mark, text)
    if channel_id == GTA_CHANNEL_ID and VEHICLE_MARKER.casefold() not in source.casefold():
        source, protected = GENERIC_VEHICLE.subn(VEHICLE_MARKER, source)
        if protected:
            replacements[VEHICLE_MARKER] = "一輛載具"
    return source, replacements


def reserve_translation(db, now: float, text: str, channel_id: int) -> bool:
    """Debit the exact provider input inside the caller's receipt transaction."""
    month = datetime.fromtimestamp(now, HONG_KONG).strftime("%Y-%m")
    source, _ = translation_input(text, channel_id)
    length = len(source)
    db.execute("INSERT OR IGNORE INTO usage VALUES (?,0)", (month,))
    return bool(db.execute("UPDATE usage SET characters=characters+? "
                           "WHERE month=? AND characters+?<=?",
                           (length, month, length, MONTHLY_LIMIT)).rowcount)


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
    channel_id: int


class TranslationQueue:
    def __init__(self, path: Path):
        self.path = path
        with connect_sqlite(path) as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS posts (
                    message_id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL UNIQUE,
                    stage TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pending_posts ON posts(stage, available);
                CREATE TABLE IF NOT EXISTS usage (
                    month TEXT PRIMARY KEY, characters INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fc27_delivery_owner (
                    version TEXT PRIMARY KEY, owner TEXT NOT NULL
                );
            """)
            # All receipts predating the channel column came from the GTA pilot.
            if "channel_id" not in {row[1] for row in db.execute("PRAGMA table_info(posts)")}:
                db.execute(f"ALTER TABLE posts ADD COLUMN channel_id INTEGER NOT NULL DEFAULT {GTA_CHANNEL_ID}")

    def add(self, message_id: int, source_id: int, body: str, *, channel_id: int = GTA_CHANNEL_ID,
            review_keys: tuple[str, ...] = ()) -> None:
        if channel_id not in OFFICIAL_UPDATE_CHANNELS:
            raise ValueError("Unknown official update channel")
        with connect_sqlite(self.path) as db:
            if review_keys:
                db.execute("BEGIN IMMEDIATE")
                if any(db.execute("SELECT 1 FROM fc27_delivery_owner WHERE version=? AND owner='reviewed'",
                                  (key,)).fetchone() for key in review_keys):
                    return
                db.executemany("INSERT OR IGNORE INTO fc27_delivery_owner VALUES (?,'relay')",
                               [(key,) for key in review_keys])
            db.execute("INSERT OR IGNORE INTO posts(message_id,source_id,stage,body,channel_id) "
                       "SELECT ?,?,'translate',?,? WHERE ?", (message_id, source_id, body, channel_id, bool(body)))

    def claim(self, now: float) -> Job | None:
        # Single transaction across processes: check the budget and debit BEFORE HTTP.
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE posts SET stage='failed',body='' WHERE stage IN ('translate','deliver') "
                       "AND attempt>=? AND available<=?", (MAX_ATTEMPTS, now))
            row = db.execute("SELECT message_id,stage,attempt,body,channel_id FROM posts "
                             "WHERE stage IN ('deliver','translate') AND available<=? "
                             "ORDER BY stage, message_id LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            message_id, stage, attempt, body, channel_id = row
            if stage == "translate" and not reserve_translation(db, now, body, channel_id):
                local = datetime.fromtimestamp(now, HONG_KONG)
                db.execute("UPDATE posts SET available=? WHERE message_id=?",
                           (next_month_start(local), message_id))
                return None
            db.execute("UPDATE posts SET attempt=attempt+1,available=? WHERE message_id=?",
                       (now + LEASE_SECONDS, message_id))
            return Job(message_id, stage, attempt + 1, body, channel_id)

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
