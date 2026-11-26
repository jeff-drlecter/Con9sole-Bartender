"""Identities for manually reviewed Apex articles and matching official relays."""
from datetime import date
import re

NEWS = "https://www.ea.com/games/apex-legends/apex-legends/news/"
HUB = "https://forums.ea.com/blog/apex-legends-game-info-hub-en/"
ISO_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
SLUG = r"[a-z0-9]+(?:-+[a-z0-9]+)*"


def article_key(url):
    """Only individual patch articles and update posts in the official English blog."""
    if len(url) > 240:
        return None
    if url.startswith(NEWS) and re.fullmatch(SLUG + r"-patch-notes", url[len(NEWS):]):
        return url
    if url.startswith(HUB):
        path = url[len(HUB):].replace("apex-legends%E2%84%A2-", "apex-legends-").replace(
            "apex-legends™-", "apex-legends-")
        match = re.fullmatch(r"(" + SLUG + r")/([1-9][0-9]*)", path)
        if match and re.search(r"(?:^|-)(?:patch-notes|latest-update|hotfix(?:es)?)(?:-|$)", match[1]):
            return "apex:hub/" + match[2]
    return None


def article_keys(url):
    key = article_key(url)
    if not key:
        return set()
    # EA mirrors its named patch notes under the same slug in News and the Info Hub.
    match = re.fullmatch(re.escape(HUB) + r"apex-legends(?:™|%E2%84%A2)?-(" + SLUG
                         + r"-patch-notes)/[1-9][0-9]*", url)
    return {key, NEWS + match[1]} if match else {key}


def calendar_day(first, second, year):
    # EA uses both day-first and month-first titles. Never infer an ambiguous day.
    if first <= 12 and second <= 12 and first != second:
        return None
    month, day = (first, second) if first <= 12 else (second, first)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def dated_hotfix(url):
    if not url.startswith(HUB) or not article_key(url):
        return None
    slug = url[len(HUB):].split("/")[0]
    match = re.search(r"-([0-9]{1,2})-([0-9]{1,2})-?([0-9]{4})$", slug)
    return calendar_day(*map(int, match.groups())) if match else None


def relay_keys(text, version_pattern):
    articles = []
    releases = set()
    for url in re.findall(r"https://[^\s<>()\]]+", text):
        canonical = url.rstrip(".,").split("?", 1)[0].split("#", 1)[0]
        aliases = article_keys(canonical)
        if aliases:
            articles.append(aliases)
            day = dated_hotfix(canonical)
            if day:
                releases.add(day)
    for match in re.finditer(r"\bApex Legends\s*[:｜—-]?\s*(?:Latest Update|Hotfix)\s*[-:]?\s*"
                             r"([0-9]{1,2})[./]\s*([0-9]{1,2})[./]([0-9]{4})\b", text, re.I):
        day = calendar_day(*map(int, match.groups()))
        if day:
            releases.add(day)
    for match in re.finditer(r"\bApex(?: Legends)?\s*[|｜:—-]?\s*(?:hotfix\s+|patch\s+|update\s+|version\s+)?"
                             rf"(?:({ISO_DATE})|v?({version_pattern}))(?!\w|[.-][0-9])", text, re.I):
        if match[1]:
            try:
                releases.add(date.fromisoformat(match[1]).isoformat())
            except ValueError:
                continue
        else:
            version = match[2]
            releases.add(version if version.count(".") == 2 else version + ".0")
    # A multi-release roundup must retain the relay's regular translation.
    if len(releases) > 1 or (len(articles) > 1 and not set.intersection(*articles)):
        return set()
    return {"apex:" + value for value in releases}.union(*articles)
