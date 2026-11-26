"""Trusted publisher routes for operator-reviewed updates. No network or polling."""
from dataclasses import dataclass
from datetime import date
import hashlib
import unicodedata
import re


@dataclass(frozen=True)
class Route:
    name: str
    channel: str  # Name in OFFICIAL_UPDATE_CHANNELS, whose IDs are the only destinations.
    publisher: str
    example: str
    platforms: tuple[str, ...] = ()


ROUTES = {
    "bf6": Route("Battlefield 6 / REDSEC", "Battlefield 6", "EA · Battlefield", "2.1.2.5"),
    "hd2": Route("Helldivers 2", "Helldivers 2", "Arrowhead Game Studios", "7.2.0 / 原文範圍",
                 ("原文範圍", "PC", "PS5", "Xbox")),
    "gtao": Route("GTA Online 更新", "GTA", "Rockstar Games", "1.73"),
    "gtaweek": Route("GTA Online 每週活動", "GTA", "Rockstar Games", "2026-11-05 / 4k17a844oakk5o"),
    "delta": Route("Delta Force", "Delta Force", "Delta Force Team", "2026-11-10 / 跨平台",
                   ("跨平台", "PC", "主機", "手機", "原文範圍")),
    "wilds": Route("Monster Hunter Wilds", "Monster Hunter", "CAPCOM · Steam", "1.042.00.03 / Steam", ("Steam",)),
    "wwmhmt": Route("燕雲十六聲（港澳台）", "Where Winds Meet", "燕雲十六聲 · 港澳台官網", "2026-11-26"),
    "nba27": Route("NBA 2K27", "NBA 2K", "2K · NBA 2K27", "3.0"),
}

NUMERIC = r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}"
DAY = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
DATED = {"delta", "gtaweek", "wwmhmt"}
NBA_PAGE = "https://nba.2k.com/2k27/patch-updates/"
# These publisher URLs have opaque identifiers or titles shared with promos/other games.
# Add confirmed aliases here when an otherwise ambiguous URL has been checked.
WEEKLY_TITLES = {
    "Take Down the Kortz Center and More High-Value Targets in This Week’s Heist Event",
    "Compete Across Entrepreneurial Endeavors in the GTA Online Business Rivalries Event",
}
WEEKLY = {
    "4k17a844oakk5o/take-down-the-kortz-center-and-more-high-value-targets-in-this-week-s": "2026-11-05",
    "ak43aoa18a19o2/compete-across-entrepreneurial-endeavors-in-the-gta-online-business-ri": "2026-09-03",
}
DELTA_UPDATES = {
    "news-major-update-season-aurora-is-coming": ("de0db9f6a0ac1a4621a864eaa9442413c49d", "2026-11-10"),
    "news-november-12-update-balance-adjustments-and-bug-fixes": ("2e423c09a6473a4867a820ba6ff13ef3bdfc", "2026-11-12"),
}


def identifier(game, value):
    route = ROUTES[game]
    parts = [s.strip() for s in value.strip().split("/")]
    value = parts[0].removeprefix("v")
    if game in DATED:
        if not re.fullmatch(DAY, value):
            raise ValueError("請按官方更新日期輸入 YYYY-MM-DD。")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("更新日期無效。") from exc
    elif not re.fullmatch(NUMERIC, value):
        raise ValueError("請按原文輸入版本號，保留所有數位。")
    if game == "gtaweek":
        if len(parts) != 2 or not re.fullmatch(r"[a-z0-9]{10,20}", parts[1]):
            raise ValueError("請輸入日期 / 官方 Newswire 文章 ID。")
        return value + " / " + parts[1]
    if route.platforms:
        if len(parts) != 2 or parts[1] not in route.platforms:
            raise ValueError("請在版本或日期後加 / 及平台：" + "、".join(route.platforms))
        return value + " / " + parts[1]
    if len(parts) != 1:
        raise ValueError("同一次更新共用一帖，請在摘要列明各平台及日期。")
    return value


@dataclass(frozen=True)
class Source:
    key: str
    edition: str = ""  # Source carries an independently identifiable version or date.
    month_day: str = ""


def source(game, url):
    """Recognize only canonical articles. Operators verify the visible title/content before review."""
    if len(url) > 240:
        return None
    if game == "bf6":
        match = re.fullmatch(r"https://www\.ea\.com/games/battlefield/battlefield-6/news/battlefield-6-game-update-([0-9]+(?:-[0-9]+){2,3})", url)
        if match:
            return Source(url, match[1].replace("-", "."))
    if game == "hd2":
        match = re.fullmatch(r"https://arrowhead\.zendesk\.com/hc/en-us/articles/([0-9]+)-[A-Za-z0-9%-]+?-([0-9]+-[0-9]+-[0-9]+)(?:-%E2%9A%99%EF%B8%8F)?", url)
        if match:
            return Source("hd2:article:" + match[1], match[2].replace("-", "."))
    if game == "gtao":
        match = re.fullmatch(r"https://support\.rockstargames\.com/articles/([A-Za-z0-9]+)/gtav-title-update-([0-9]+-[0-9]+)-notes(?:-[a-z0-9-]+)?", url)
        if match:
            return Source("gtao:article:" + match[1], match[2].replace("-", "."))
    if game == "gtaweek":
        path = url.removeprefix("https://www.rockstargames.com/newswire/article/")
        if path != url:
            if path in WEEKLY:
                return Source("gtaweek:article:" + path.split("/")[0], WEEKLY[path])
            match = re.fullmatch(r"([a-z0-9]{10,20})/([a-z0-9]+(?:-[a-z0-9]+)+)", path)
            if (match and "gta-online" in match[2] and re.search(r"(?:^|-)(?:weekly|this-week|event)(?:-|$)", match[2])
                    and not re.search(r"(?:gta-vi|gta-6|red-dead)", match[2])):
                return Source("gtaweek:article:" + match[1])
    if game == "delta":
        for slug, (article_id, day) in DELTA_UPDATES.items():
            if url in (f"https://www.playdeltaforce.com/en/detail/{slug}.html",
                       f"https://www.playdeltaforce.com/en/detail.html?content_id={article_id}",
                       f"https://www.playdeltaforce.com/en/detail.html?content_id={article_id}&father_content_id={article_id}"):
                return Source("delta:article:" + article_id, day)
        match = re.fullmatch(r"https://www\.playdeltaforce\.com/en/detail/news-([a-z]+)-([0-9]{1,2})-update-(?:balance-adjustments-and-bug-fixes|bug-fixes|patch-notes)\.html", url)
        months = "january february march april may june july august september october november december".split()
        if match and match[1] in months:
            return Source(url, month_day=f"{months.index(match[1])+1:02}{int(match[2]):02}")
    if game == "wilds":
        match = re.fullmatch(r"https://(?:store\.steampowered\.com/news/app/2246340/view/|steamcommunity\.com/(?:app|games)/2246340/announcements/detail/)([1-9][0-9]{5,20})(?:\?l=english)?", url)
        if match:
            version = "1.042.00.03" if match[1] == "668380665149915562" else ""
            return Source("wilds:article:" + match[1], version)
    if game == "wwmhmt":
        match = re.fullmatch(r"https://www\.wherewindsmeetgame\.com/hmt/news/official/([0-9]{4})update\.html", url)
        if match:
            return Source(url, month_day=match[1])
    if game == "nba27" and url == NBA_PAGE:
        return Source(url)
    return None


def platform_keys(game, version):
    if not ROUTES[game].platforms:
        return set()
    edition, scope = version.split(" / ")
    platforms = set(ROUTES[game].platforms) - {"跨平台", "原文範圍"}
    covered = platforms if scope in {"跨平台", "原文範圍"} else {scope}
    return {f"{game}:platform:{edition}:{p}" for p in covered}


def check_heading(game, edition, headline):
    if game == "wilds":
        return bool(re.fullmatch(r"Update Summary\s*\(Ver\.\s*" + re.escape(edition) + r"\)", headline, re.I))
    if game == "nba27":
        return bool(re.fullmatch(r"NBA\s+2K27\s+v" + re.escape(edition), headline, re.I))
    return True


def article_keys(game, sources):
    # NBA reuses one URL for a sequence of unrelated versions. A bare link has no identity.
    if game == "nba27":
        return set()
    return {s.key for s in sources}


def title_key(game, title):
    value = unicodedata.normalize("NFKC", title).strip(" #*\t").casefold()
    value = " ".join(value.split())
    if len(value) < 12 or len(value) > 150 or "://" in value:
        return None
    return game + ":title:" + hashlib.sha256(value.encode()).hexdigest()[:32]


def relay_keys(game, text, titles=()):
    keys = set()
    for url in re.findall(r"https://[^\s<>()\]]+", text):
        url = url.rstrip(".,").split("#", 1)[0]
        item = source(game, url)
        if item is None and game != "delta":
            item = source(game, url.split("?", 1)[0])
        if item and game != "nba27":
            keys.add(item.key)
    if len(keys) > 1:
        return set()  # A roundup must not be suppressed as one reviewed article.
    patterns = {
        "nba27": r"\bNBA\s*2K27\s*(?:patch\s+|update\s+)?v",
        "bf6": r"\bBattlefield\s+6\s+game\s+update\s+",
        "gtao": r"\bGTAV\s+title\s+update\s+",
    }
    if game == "nba27" and re.search(r"NBA\s*2K27", text, re.I):
        patterns[game] = r"(?:\bNBA\s*2K27\s*(?:patch\s+|update\s+)?v|\bPATCH NOTES\s+v)"
    if game in patterns:
        versions = {m[1] for m in re.finditer(patterns[game] + "(" + NUMERIC + r")(?!\w|\.\d)", text, re.I)}
        if len(versions) > 1:
            return set()
        keys.update(f"{game}:{v}" for v in versions)
    if game == "gtaweek":
        # A bare Rockstar short URL may carry an intact official Newswire headline.
        known = {title_key(game, title) for title in WEEKLY_TITLES}
        seen = {title_key(game, title) for title in titles} & known
        if len(seen) > 1:
            return set()
        keys.update(seen)
    return keys
