"""Plan a bilingual Discord layout offline from an ordered, complete article."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
import re
from urllib.parse import urlsplit

from core.gta_translation import SOURCE_TOKEN

BLUE = 0x3498DB
PURPLE = 0x9B59B6
DESCRIPTION_LIMIT = 4096
EMBED_TOTAL_LIMIT = 6000
# Conservative single-file limit for an offline plan. Never truncate an attachment.
TEXT_FILE_LIMIT = 10 * 1024 * 1024
REFERENCE = re.compile(r"\{ref(\d+)\}")


def outline(text: str) -> list:
    """Compare structure independently of words, wrapping and translated length."""
    shape = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            item = "break"
        elif stripped.startswith("|") and stripped.endswith("|"):
            cells = re.split(r"(?<!\\)\|", stripped[1:-1])
            divider = all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)
            item = ("table", divider, tuple(bool(c.strip()) for c in cells))
        elif marker := re.match(r"^(\s*)([-*+] |\d+[.)] |#{1,6} )", line):
            item = ("marker", marker[1], marker[2])
        else:
            item = "paragraph"
        if item not in ("paragraph", "break") or not shape or shape[-1] != item:
            shape.append(item)
    return shape


@dataclass(frozen=True)
class Block:
    key: str
    section: str
    english: str
    chinese: str
    links: tuple[str, ...] = ()

    def render(self, language: str) -> str:
        text = self.chinese if language == "zh" else self.english
        if not text.strip():
            raise ValueError(f"Incomplete {language} full text at {self.key}")
        if re.search(r"https?://", text, re.I):
            raise ValueError(f"Source links must use shared references at {self.key}")
        if REFERENCE.findall(text) != [str(i) for i in range(len(self.links))]:
            raise ValueError(f"Missing or reordered {language} link at {self.key}")
        for url in self.links:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or any(c.isspace() or c in "<>" for c in url)):
                raise ValueError(f"Invalid source link at {self.key}")
        return REFERENCE.sub(lambda m: "<" + self.links[int(m[1])] + ">", text)


def units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class AttachmentNeeded(ValueError):
    """Lossless inline display is unavailable for this text."""


def split_large_block(text: str):
    # Preserve every code point, including separators, and keep masked links intact.
    start = 0
    protected = iter(SOURCE_TOKEN.finditer(text))
    token = next(protected, None)
    while start < len(text):
        end = min(start + DESCRIPTION_LIMIT, len(text))
        if units(text[start:end]) > DESCRIPTION_LIMIT:
            size = 0
            for end in range(start, end):
                size += 2 if ord(text[end]) > 0xffff else 1
                if size > DESCRIPTION_LIMIT:
                    break
        if end < len(text):
            soft = text.rfind("\n", start, end)
            if soft - start < DESCRIPTION_LIMIT // 4:
                soft = text.rfind(" ", start, end)
            if soft > start and text[start:soft].strip():
                end = soft + 1
            while token and token.end() <= end:
                token = next(protected, None)
            if token and token.start() < end < token.end():
                end = token.start() if token.start() > start else token.end()
            if units(text[start:end]) > DESCRIPTION_LIMIT:
                raise AttachmentNeeded
        yield text[start:end]
        start = end


def paginate(blocks: list[Block], texts: list[str]) -> list[str]:
    """Keep each subsection together when it fits, then prefer whole blocks."""
    pages = []
    current = ""
    items = zip(blocks, texts, strict=True)
    for _, group in groupby(items, key=lambda item: item[0].section):
        parts = [text for _, text in group]
        section = "".join(parts)
        if units(section) <= DESCRIPTION_LIMIT:
            parts = [section]
        for part in parts:
            for piece in ([part] if units(part) <= DESCRIPTION_LIMIT else split_large_block(part)):
                if current and units(current) + units(piece) > DESCRIPTION_LIMIT:
                    pages.append(current)
                    current = ""
                current += piece
    if current:
        pages.append(current)
    if any(not page.strip() for page in pages):
        raise AttachmentNeeded
    return pages


def message(title: str, color: int, bodies: list[str]) -> dict:
    return {"embeds": [{"title": title, "color": color, "description": body} for body in bodies],
            "allowed_mentions": {"parse": []}}


def with_full_file(title: str, color: int, first: str, full_text: str, name: str) -> dict:
    if len(full_text.encode("utf-8")) > TEXT_FILE_LIMIT:
        raise ValueError("Complete text exceeds the preview attachment limit; publication blocked")
    result = message(title, color, [first])
    result["content"] = ("完整繁中譯文收錄於本帖文字附件。" if color == BLUE else
                         "The attached text contains the complete English original.")
    result["text_attachment"] = {"filename": name, "text": full_text}
    return result


def full_layout(blocks: list[Block]) -> dict:
    if not blocks or len({b.key for b in blocks}) != len(blocks):
        raise ValueError("Expected a nonempty ordered article with unique block keys")
    for block in blocks:
        if outline(block.english) != outline(block.chinese):
            raise ValueError(f"Incomplete bilingual structure at {block.key}")
    plan = {}
    for language, title, colour in (("zh", "繁體中文｜全文", BLUE), ("en", "English Original", PURPLE)):
        texts = [("" if i == 0 else "\n\n") + block.render(language) for i, block in enumerate(blocks)]
        try:
            pages = paginate(blocks, texts)
        except AttachmentNeeded:
            pages = []
        if not pages or (language == "zh" and
                         (len(pages) > 10 or sum(units(p) + units(title) for p in pages) > EMBED_TOTAL_LIMIT)):
            # Keep all Chinese in a single parent message even above the embed limit.
            file = with_full_file(title, colour, pages[0] if pages else title, "".join(texts),
                                  f"FC27-{'繁中全文' if language == 'zh' else 'English-Original'}.md")
            messages = [file]
        elif language == "zh":
            messages = [message(title, colour, pages)]
        else:
            messages = [message(title, colour, [p]) for p in pages]
        if language == "zh":
            plan["parent"] = messages[0]
        else:
            plan["thread"] = {"name": "🟪 English Original", "parent": "parent", "messages": messages}
    return plan
