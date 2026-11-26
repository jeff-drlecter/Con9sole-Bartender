"""Reviewed FC27 release copy, translation budget and durable delivery receipts."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import re

from core.gta_translation import FC_CHANNEL_ID, HONG_KONG, TranslationQueue, reserve_translation
from core.sqlite_storage import connect_sqlite


BOT_ID = 1417409362405756979
NEWS = "https://www.ea.com/games/ea-sports-fc/fc-27/news/"
HUB = "https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/"
NUMBER = r"(?:0|[1-9][0-9]{0,2})"
VERSION = rf"{NUMBER}\.{NUMBER}(?:\.{NUMBER})?"
SOURCE_MONTH_LIMIT = 6000
DATE_START = datetime(2026, 7, 1, tzinfo=HONG_KONG)


class ReviewError(ValueError):
    """Safe, content-free operator feedback."""


def normalized(value):
    value = value.strip().lower().removeprefix("v")
    if not re.fullmatch(VERSION, value):
        raise ReviewError("請輸入 FC27 更新版本，例如 1.3.0。")
    return value if value.count(".") == 2 else value + ".0"


def source_version(url):
    # Exact English EA article routes. A forum topic, mirror slug, query or external
    # redirect cannot be supplied as the link behind the English attribution.
    if len(url) > 240 or any(ch in url for ch in "?#@<>()[]\\ \r\n"):
        return None
    pattern = VERSION.replace(r"\.", "-")
    for base, slug in (
        (NEWS, rf"(?:fc27-title-update-v|update-v)({pattern})(?:-pitch-notes)?"),
        (HUB, rf"ea-sports-fc(?:™)?-27--title-update-v({pattern})(?:-pitch-notes)?/[1-9][0-9]*"),
    ):
        if url.startswith(base):
            match = re.fullmatch(slug, url[len(base):].replace("%E2%84%A2", "™"))
            if match:
                return normalized(match[1].replace("-", "."))
    return None


def mentioned_versions(text):
    """Use explicit FC27 context or an exact official article URL to identify a relay."""
    versions = set()
    for url in re.findall(r"https://[^\s<>()\]]+", text):
        version = source_version(url.rstrip(".,"))
        if version:
            versions.add(version)
    for match in re.finditer(rf"\bFC(?:™)?\s*27\s*[|｜:—-]?\s*(?:title update\s*|version\s*)?"
                             rf"v?({VERSION})(?!\d|\.\d)", text, re.I):
        versions.add(normalized(match[1]))
    return versions


def clean(value, limit):
    value = value.strip()
    if (not value or len(value.encode("utf-16-le")) // 2 > limit
            or any(x in value for x in ("@", "<", ">", "://", "](", "discord.gg/"))
            or any(ord(c) < 32 and c != "\n" for c in value)):
        raise ReviewError("文字過長或含有提及、連結或控制字元。請在來源欄填寫連結。")
    return value


@dataclass(frozen=True)
class Release:
    version: str
    urls: tuple[str, ...]
    english: str
    quote: str
    recap: str = ""
    gloss: str = ""

    @classmethod
    def from_input(cls, version, links, english, quote):
        version = normalized(version)
        urls = tuple(dict.fromkeys(links.split()))
        if not 1 <= len(urls) <= 2 or any(source_version(url) != version for url in urls):
            raise ReviewError("請填寫同版本的 EA FC27 英文官網或 Game Info Hub 原文，最多兩條。")
        english, quote = clean(english, 1600), clean(quote, 200)
        if ("\n" in quote or len(quote.split()) > 25 or not all(re.search("[A-Za-z]", v) for v in (english, quote))
                or re.search(r"[\u3400-\u9fff]", english + quote)):
            raise ReviewError("請提供自撰英文摘要及最多 25 個英文詞的官方短引。")
        return cls(version, urls, english, quote)

    def check_translation(self):
        checked = self.from_input(self.version, "\n".join(self.urls), self.english, self.quote)
        if (self.version, self.urls, self.english, self.quote) != (checked.version, checked.urls, checked.english, checked.quote):
            raise ReviewError("確認稿的版本或來源格式已改變，請核對原稿。")
        for original, translation, limit in ((self.english, self.recap, 2200), (self.quote, self.gloss, 450)):
            clean(translation, limit)
            numbers = r"[+-]?[0-9]+(?:[.][0-9]+)*%?"
            if (not re.search(r"[\u3400-\u9fff]", translation)
                    or Counter(re.findall(numbers, original.replace("−", "-"))) !=
                    Counter(re.findall(numbers, translation.replace("−", "-").replace("％", "%")))):
                raise ReviewError("請校訂繁中譯文，保留英文底稿的數字及精度，然後再預覽。")

    def pack(self):
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def unpack(cls, data):
        fields = json.loads(data)
        fields["urls"] = tuple(fields["urls"])
        return cls(**fields)


class Receipts:
    def __init__(self, path):
        self.path = path
        TranslationQueue(path)
        with connect_sqlite(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS fc27_publications (
                    version TEXT PRIMARY KEY, packet TEXT NOT NULL, phase TEXT NOT NULL,
                    parent INTEGER, source INTEGER
                );
                CREATE TABLE IF NOT EXISTS fc27_text_cache (
                    url TEXT, digest TEXT, attempted REAL, attempts INTEGER, value TEXT,
                    PRIMARY KEY(url,digest)
                );
                CREATE TABLE IF NOT EXISTS fc27_source_usage (
                    url TEXT, month TEXT, characters INTEGER NOT NULL, PRIMARY KEY(url,month)
                );
                CREATE TABLE IF NOT EXISTS fc27_article_versions (
                    article TEXT PRIMARY KEY, version TEXT NOT NULL
                );
            """)

    @staticmethod
    def article(url):
        return "hub/" + url.rsplit("/", 1)[1] if url.startswith(HUB) else url

    def check_sources(self, draft):
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT owner FROM fc27_delivery_owner WHERE version=?", (draft.version,)).fetchone()
            if owner and owner[0] == "relay":
                raise ReviewError("此版本已有官方轉發，請核對原帖。")
            for url in draft.urls:
                key = self.article(url)
                db.execute("INSERT OR IGNORE INTO fc27_article_versions VALUES (?,?)", (key, draft.version))
                if db.execute("SELECT version FROM fc27_article_versions WHERE article=?", (key,)).fetchone()[0] != draft.version:
                    raise ReviewError("同一篇官方文章已對應另一版本，請核對來源。")

    def translation(self, url, text, now, *, provider_available=True):
        url = self.article(url)
        digest = hashlib.sha256(text.encode()).hexdigest()
        month = datetime.fromtimestamp(now, HONG_KONG).strftime("%Y-%m")
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value,attempts,attempted FROM fc27_text_cache WHERE url=? AND digest=?",
                             (url, digest)).fetchone()
            if row:
                if row[0] is not None:
                    return row[0], None
            if not provider_available:
                raise ReviewError("助手的共用翻譯服務尚未啟用。")
            if row:
                current_month = datetime.fromtimestamp(row[2], HONG_KONG).strftime("%Y-%m") == month
                if (current_month and row[1] >= 2) or now - row[2] < 120:
                    raise ReviewError("這段原文的翻譯正在處理，或本月已達兩次嘗試上限。")
                if not current_month:
                    db.execute("UPDATE fc27_text_cache SET attempts=0 WHERE url=? AND digest=?", (url, digest))
            db.execute("INSERT OR IGNORE INTO fc27_source_usage VALUES (?,?,0)", (url, month))
            if not db.execute("UPDATE fc27_source_usage SET characters=characters+? WHERE url=? AND month=? "
                              "AND characters+?<=?", (len(text), url, month, len(text), SOURCE_MONTH_LIMIT)).rowcount:
                raise ReviewError("這篇來源已達每月翻譯上限。")
            if not reserve_translation(db, now, text, FC_CHANNEL_ID):
                raise ReviewError("本月共用翻譯額度不足。")
            db.execute("INSERT INTO fc27_text_cache VALUES (?,?,?,1,NULL) ON CONFLICT(url,digest) "
                       "DO UPDATE SET attempted=excluded.attempted, attempts=attempts+1", (url, digest, now))
            return None, (url, digest, now)

    def cache_result(self, ticket, value):
        with connect_sqlite(self.path) as db:
            if not db.execute("UPDATE fc27_text_cache SET value=? WHERE url=? AND digest=? AND attempted=?",
                              (value, *ticket)).rowcount:
                raise ReviewError("這次翻譯已逾時，請重新開啟預覽。")

    def receipt(self, version):
        with connect_sqlite(self.path) as db:
            return db.execute("SELECT packet,phase,parent,source FROM fc27_publications WHERE version=?",
                              (version,)).fetchone()

    def begin(self, draft):
        draft.check_translation()
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO fc27_delivery_owner VALUES (?,'reviewed')", (draft.version,))
            if db.execute("SELECT owner FROM fc27_delivery_owner WHERE version=?", (draft.version,)).fetchone()[0] != "reviewed":
                raise ReviewError("此版本已有官方轉發進入翻譯流程，請核對原帖。")
            db.execute("INSERT OR IGNORE INTO fc27_publications(version,packet,phase) VALUES (?,?,'parent')",
                       (draft.version, draft.pack()))
            if db.execute("SELECT packet FROM fc27_publications WHERE version=?", (draft.version,)).fetchone()[0] != draft.pack():
                raise ReviewError("此版本已有另一份確認稿，請只輸入版本號載入原稿。")

    def move(self, version, expected, phase, *, parent=None, source=None):
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE fc27_publications SET phase=?,parent=COALESCE(?,parent),"
                                   "source=COALESCE(?,source) WHERE version=? AND phase=?",
                                   (phase, parent, source, version, expected)).rowcount)
