"""Reviewed official game update copy, translation budget and durable delivery receipts."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import re

from core import apex_updates, reviewed_games
from core.gta_translation import APEX_CHANNEL_ID, FC_CHANNEL_ID, HONG_KONG, OFFICIAL_UPDATE_CHANNELS, TranslationQueue, reserve_translation
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


def normalized(value, game="fc27"):
    if game in reviewed_games.ROUTES:
        try:
            return reviewed_games.identifier(game, value)
        except ValueError as exc:
            raise ReviewError(str(exc)) from exc
    if game not in {"fc27", "apex"}:
        raise ReviewError("未支援這款遊戲。")
    if game == "apex" and re.fullmatch(apex_updates.ISO_DATE, value.strip()):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise ReviewError("請輸入有效的更新日期（YYYY-MM-DD）。") from exc
    value = value.strip().lower().removeprefix("v")
    if not re.fullmatch(VERSION, value):
        if game == "apex":
            raise ReviewError("請輸入 Apex 版本號，無版本時請填 YYYY-MM-DD。")
        raise ReviewError("請輸入 FC27 更新版本，例如 1.3.0。")
    return value if value.count(".") == 2 else value + ".0"


def receipt_key(game, version):
    # Numeric FC keys predate the multi-game publisher and must remain resumable.
    return version if game == "fc27" else game + ":" + version


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
    game: str = "fc27"
    headline: str = ""

    @property
    def key(self):
        return receipt_key(self.game, self.version)

    @property
    def game_name(self):
        if self.game in reviewed_games.ROUTES:
            return reviewed_games.ROUTES[self.game].name
        return "Apex Legends" if self.game == "apex" else "FC27"

    @property
    def channel_id(self):
        if self.game in reviewed_games.ROUTES:
            label = reviewed_games.ROUTES[self.game].channel
            ids = [cid for cid, name in OFFICIAL_UPDATE_CHANNELS.items() if label == name]
            if len(ids) != 1:
                raise ReviewError("未能唯一核對官方更新頻道。")
            return ids[0]
        if self.game not in {"apex", "fc27"}:
            raise ReviewError("未支援這款遊戲。")
        return APEX_CHANNEL_ID if self.game == "apex" else FC_CHANNEL_ID

    @property
    def owner_keys(self):
        if self.game == "apex":
            return {self.key}.union(*(apex_updates.article_keys(url) for url in self.urls))
        if self.game in reviewed_games.ROUTES:
            items = [reviewed_games.source(self.game, url) for url in self.urls]
            if not all(items):
                raise ReviewError("請核對已批准的官方原文。")
            keys = {self.key} | reviewed_games.article_keys(self.game, items) | reviewed_games.platform_keys(self.game, self.version)
            if self.game == "gtaweek" and (key := reviewed_games.title_key(self.game, self.headline)):
                keys.add(key)
            return keys
        return {self.key}

    @classmethod
    def from_input(cls, version, links, english, quote, *, game="fc27", headline=""):
        version = normalized(version, game)
        urls = tuple(dict.fromkeys(links.split()))
        if not 1 <= len(urls) <= 2:
            raise ReviewError("請提供一至兩條同一更新的官方英文文章連結。")
        if game in reviewed_games.ROUTES:
            headline = clean(headline, 150)
            if "\n" in headline:
                raise ReviewError("請填寫單行官方標題。")
            edition = version.split(" / ")[0]
            if not reviewed_games.check_heading(game, edition, headline):
                raise ReviewError("官方文章標題與版本不符。")
            for url in urls:
                item = reviewed_games.source(game, url)
                if (not item or (item.edition and item.edition != edition)
                        or (game == "gtaweek" and item.key.rsplit(":", 1)[-1] != version.split(" / ")[1])
                        or (item.month_day and edition[5:].replace("-", "") != item.month_day)):
                    raise ReviewError("請核對官方更新原文、版本、地區及日期。")
        elif game == "apex":
            if any(not apex_updates.article_key(url) for url in urls):
                raise ReviewError("請提供 Apex 官方更新文章連結。")
            dates = {day for url in urls if (day := apex_updates.dated_hotfix(url))}
            named_patches = {key for url in urls for key in apex_updates.article_keys(url)
                             if key.startswith(apex_updates.NEWS)}
            if (len(dates) > 1 or len(named_patches) > 1
                    or ("-" in version and dates and version not in dates)):
                raise ReviewError("請核對 Apex 官方更新是否屬於同一次更新及同一發布日期。")
        elif any(source_version(url) != version for url in urls):
            raise ReviewError("請填寫同版本的 EA FC27 英文官網或 Game Info Hub 原文，最多兩條。")
        english, quote = clean(english, 1600), clean(quote, 200)
        if game == "wwmhmt":
            if (not all(re.search(r"[\u3400-\u9fff]", s) for s in (english, quote)) or len(quote) > 60
                    or "\n" in quote):
                raise ReviewError("請提供人工繁中摘要及 60 字以內的官方繁中短引。")
            return cls(version, urls, english, quote, recap=english, gloss=quote, game=game, headline=headline)
        if ("\n" in quote or len(quote.split()) > 25 or not all(re.search("[A-Za-z]", v) for v in (english, quote))
                or re.search(r"[\u3400-\u9fff]", english + quote)):
            raise ReviewError("請提供自撰英文摘要及最多 25 個英文詞的官方短引。")
        return cls(version, urls, english, quote, game=game, headline=headline)

    def check_translation(self):
        checked = self.from_input(self.version, "\n".join(self.urls), self.english, self.quote, game=self.game, headline=self.headline)
        if (self.version, self.urls, self.english, self.quote) != (checked.version, checked.urls, checked.english, checked.quote):
            raise ReviewError("確認稿的版本或來源格式已改變，請核對原稿。")
        if self.game == "wwmhmt" and self.gloss != self.quote:
            raise ReviewError("請保留官方繁中短引的原文。")
        for original, translation, limit in ((self.english, self.recap, 2200), (self.quote, self.gloss, 450)):
            clean(translation, limit)
            numbers = r"[+-]?[0-9]+(?:[.][0-9]+)*%?"
            if (not re.search(r"[\u3400-\u9fff]", translation)
                    or Counter(re.findall(numbers, original.replace("−", "-"))) !=
                    Counter(re.findall(numbers, translation.replace("−", "-").replace("％", "%")))):
                raise ReviewError("請校訂繁中譯文，保留英文底稿的數字及精度，然後再預覽。")

    def pack(self):
        fields = asdict(self)
        if not self.headline:
            del fields["headline"]
        if self.game == "fc27":
            del fields["game"]  # Preserve the exact packet format used by deployed FC receipts.
        return json.dumps(fields, ensure_ascii=False, sort_keys=True)

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
        if url.startswith(HUB):
            return "hub/" + url.rsplit("/", 1)[1]
        for game in reviewed_games.ROUTES:
            item = reviewed_games.source(game, url)
            if item:
                return item.key
        keys = apex_updates.article_keys(url)
        # Named patch mirrors use the same primary-source budget and cached translation.
        return min(keys, key=lambda key: not key.startswith(apex_updates.NEWS), default=url)

    def check_sources(self, draft):
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_sources(db, draft, bind=draft.game == "fc27")

    def _check_sources(self, db, draft, *, bind):
        owner_keys = draft.owner_keys
        for key in owner_keys:
            owner = db.execute("SELECT owner FROM fc27_delivery_owner WHERE version=?", (key,)).fetchone()
            if owner and owner[0] != "reviewed":
                raise ReviewError("此更新已有官方轉發，請核對原帖。")
        articles = (owner_keys - {draft.key} if draft.game != "fc27"
                    else {self.article(url) for url in draft.urls})
        for key in articles:
            if bind:
                db.execute("INSERT OR IGNORE INTO fc27_article_versions VALUES (?,?)", (key, draft.key))
            row = db.execute("SELECT version FROM fc27_article_versions WHERE article=?", (key,)).fetchone()
            if row and row[0] != draft.key:
                raise ReviewError("同一篇官方文章已對應另一版本，請核對來源。")

    def translation(self, url, text, now, *, provider_available=True, channel_id=FC_CHANNEL_ID):
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
            if not reserve_translation(db, now, text, channel_id):
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
            self._check_sources(db, draft, bind=True)
            db.executemany("INSERT OR IGNORE INTO fc27_delivery_owner VALUES (?,'reviewed')",
                           [(key,) for key in draft.owner_keys])
            db.execute("INSERT OR IGNORE INTO fc27_publications(version,packet,phase) VALUES (?,?,'parent')",
                       (draft.key, draft.pack()))
            if db.execute("SELECT packet FROM fc27_publications WHERE version=?", (draft.key,)).fetchone()[0] != draft.pack():
                raise ReviewError("此版本已有另一份確認稿，請只輸入版本號載入原稿。")

    def move(self, version, expected, phase, *, parent=None, source=None):
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE fc27_publications SET phase=?,parent=COALESCE(?,parent),"
                                   "source=COALESCE(?,source) WHERE version=? AND phase=?",
                                   (phase, parent, source, version, expected)).rowcount)
