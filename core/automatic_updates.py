"""Discover release notices from the games' publisher feeds and identify their Discord mirrors."""
from dataclasses import dataclass
from calendar import month_name
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import json
import re

from core import apex_updates, reviewed_games
from core.fc27_publication import VERSION, mentioned_versions, normalized
from core.gta_translation import HONG_KONG, OFFICIAL_UPDATE_CHANNELS

# GetNewsForApp can also include journalism. Only accept the app's own announcements.
APPS = {"EA SPORTS FC": 4080220, "Apex Legends": 1172470, "NBA 2K": 4356430,
        "Battlefield 6": 2807960, "Helldivers 2": 553850, "Monster Hunter": 2246340,
        "Delta Force": 2507950, "GTA": 3240220}
HMT = "Where Winds Meet"
HMT_URL = "https://www.wherewindsmeetgame.com/hmt/news/"
DESTINATIONS = {name: cid for cid, name in OFFICIAL_UPDATE_CHANNELS.items()}
UPDATE = re.compile(r"patch notes?|hotfix|title update|latest update|game update|update summary|"
                    r"balance adjustments|bug fixes|maintenance update|版本更新|更新公告|版本内[容]|版本內容", re.I)
NUMBER = r"\d{1,3}(?:\.\d{1,3}){1,3}"
URL = re.compile(r"https://[^\s<>\[\]()]+")
STEAM_NEWS = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"


@dataclass(frozen=True)
class Notice:
    channel: int
    keys: tuple[str, ...]
    title: str
    excerpt: str
    url: str
    published: float


def identities(name, title, text):
    game = next((g for g, r in reviewed_games.ROUTES.items() if r.channel == name), None)
    combined = title + "\n" + text
    if name == "Apex Legends":
        keys = apex_updates.relay_keys(combined, VERSION)
    elif name == "EA SPORTS FC":
        keys = mentioned_versions(combined)
        for v in re.findall(r"\bFC[™®]?\s*27\s+(?:\|\s*)?(?:Title Update\s+)?v(?:ersion\s+|\.\s*)?(" + VERSION + r")(?![\d.])", combined, re.I):
            keys.add(normalized(v))
    else:
        keys = reviewed_games.relay_keys(game, combined, combined.splitlines())
        if name == "GTA":
            keys |= reviewed_games.relay_keys("gtaweek", combined, combined.splitlines())
    # URLs and exact edition identities survive translations and Discord title changes.
    app = APPS.get(name)
    for url in URL.findall(combined):
        match = re.fullmatch(rf"https://(?:store\.steampowered\.com/news/app/{app}/view/|steamcommunity\.com/(?:app|games|ogg)/{app}/announcements/detail/)(\d+)/?(?:\?[^ ]*)?", url.rstrip(".,"))
        if app and match:
            keys.add(f"steam:{app}:{match[1]}")
    for group, pattern, scope in (
            ("nba27", r"(?:patch notes|NBA\s*2K27)\s*v", ""),
            ("hd2", r"(?:patch|hotfix|liberty:)\s*v?", ""),
            ("wilds", r"\bver\.\s*", " / Steam")):
        if game == group:
            for version in re.findall(pattern + "(" + NUMBER + r")(?!\w|\.\d)", combined, re.I):
                keys.add(f"{group}:{version}{scope}")
                if group == "hd2":
                    keys.add(f"hd2:platform:{version}:PC")
    # Connect cross-platform operator receipts to numbered or dated feed headings.
    if game == "delta":
        date_match = re.search(r"\b(" + "|".join(month_name[1:]) + r") (\d{1,2}) Update\b", title, re.I)
        if date_match:
            # Bind the year below when the source publication date is known.
            keys.add("month-day:delta:" + date_match[1].lower() + "-" + date_match[2])
    for url in URL.findall(combined):
        for g, route in reviewed_games.ROUTES.items():
            if route.channel != name:
                continue
            item = reviewed_games.source(g, url.rstrip(".,"))
            if item and item.edition and g in {"bf6", "gtao", "hd2", "nba27"}:
                keys.add(f"{g}:{item.edition}")
            if g == "delta" and item and item.edition:
                keys.add("delta:day:" + item.edition)
            if g == "gtaweek" and item:
                keys.add(item.key)
    title_alias = reviewed_games.title_key("auto:" + name, title)
    if title_alias and (re.search(r"\d", title) or len(title.split()) >= 5):
        keys.add(title_alias)
    return tuple(sorted(keys))


def dated_keys(keys, stamp):
    dated = datetime.fromtimestamp(stamp, HONG_KONG)
    year = dated.year
    result = set()
    for key in keys:
        if key.startswith("auto:"):
            result.add(key + ":" + dated.strftime("%Y-%m-%d"))
        elif key.startswith("month-day:delta:"):
            month, day = key.rsplit(":", 1)[1].split("-")
            try:
                date = datetime.strptime(f"{year} {month} {day}", "%Y %B %d").date()
            except ValueError:
                continue
            result.update({"delta:day:" + date.isoformat(), "delta:platform:" + date.isoformat() + ":PC"})
        else:
            result.add(key)
    return tuple(sorted(result))


def excerpt(text):
    # Keep complete statements. Never finish a recap halfway through a qualifier or number.
    text = unescape(re.sub(r"<[^>]{1,250}>|\[(?:/?[a-z*][^\]]{0,220})\]", " ", text, flags=re.I))
    text = re.sub(r"https?://\S+|<[@#][!&]?\d+>|@\w+", "", text)
    # Decimal/version numbers must remain intact: split at sentence boundaries instead.
    pieces = re.split(r"(?<=[.!?。！？])(?:\s+|(?=[A-Z\u3400-\u9fff]))|\n+", text)
    picked = []
    for part in pieces:
        part = " ".join(part.split()).strip()
        if (12 <= len(part) <= 350 and not part.endswith(("...", "…"))
                and part.endswith((".", "!", "?", "。", "！", "？"))
                and not re.search(r"join.{0,12}discord|click here|subscribe|^hello|^greetings", part, re.I)):
            picked.append(part)
            if len(picked) == 2:
                break
    return "\n".join(picked)


def steam_notices(name, raw):
    app = APPS[name]
    feed = json.loads(raw)["appnews"]
    if feed["appid"] != app or not isinstance(feed["newsitems"], list):
        raise ValueError("Wrong Steam publisher feed")
    result = []
    for row in feed["newsitems"]:
        if row["appid"] != app or row["feedname"] != "steam_community_announcements" or row["feed_type"] != 1:
            continue
        title, body, gid = row["title"].strip(), row["contents"], str(row["gid"])
        if not re.fullmatch(r"[1-9]\d{5,20}", gid) or not 1 <= len(title) <= 200:
            continue
        eligible = UPDATE.search(title) or "patchnotes" in row.get("tags", [])
        if name == "GTA":
            eligible = eligible or ("GTA Online" in body and re.search(r"this week|weekly|heist event", body, re.I))
        if not eligible:
            continue
        url = f"https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/{gid}"
        if row.get("url") != url:
            continue
        keys = set(dated_keys(identities(name, title, body), int(row["date"])))
        keys.add(f"steam:feed:{app}:{gid}")
        result.append(Notice(DESTINATIONS[name], tuple(sorted(keys)),
                             title, excerpt(body), url, int(row["date"])))
    return result


class HmtIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.item = None
        self.field = None
        self.seen = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ul" and "news_list" in attrs.get("class", "").split():
            self.seen = True
        if tag == "a" and reviewed_games.source("wwmhmt", attrs.get("href", "")):
            self.item = {"url": attrs["href"], "title": attrs.get("title", "")}
        if tag == "p" and self.item is not None:
            self.field = attrs.get("class")

    def handle_data(self, data):
        if self.item is not None and self.field:
            self.item[self.field] = self.item.get(self.field, "") + data

    def handle_endtag(self, tag):
        if tag == "p":
            self.field = None
        if tag == "a" and self.item is not None:
            self.rows.append(self.item)
            self.item = None
            self.field = None


def hmt_notices(raw):
    parser = HmtIndex()
    parser.feed(raw.decode("utf-8"))
    if not parser.seen or not parser.rows:
        raise ValueError("Unrecognised HMT news index")
    result = []
    for item in parser.rows:
        day = datetime.strptime(item["date_year"] + "." + item["date_day"], "%Y.%m.%d").replace(tzinfo=HONG_KONG)
        url, title = item["url"], item["title"]
        effective = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", item["news_text"])
        keys = set(identities(HMT, title, url))
        if effective:
            keys.add("wwmhmt:" + "-".join(x.zfill(2) for x in effective.groups()))
        result.append(Notice(DESTINATIONS[HMT], tuple(sorted(keys)), title, excerpt(item["news_text"]), url, day.timestamp()))
    return result
