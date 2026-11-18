"""Small single-process directory; malformed state is preserved and fails closed."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from core.json_storage import atomic_write_json

MAX_CARDS = 500
STATUSES = {'open': '招募中', 'closed': '暫停招募'}


class DirectoryError(ValueError):
    """An actionable input error, safe to show privately."""


class DirectoryUnavailable(Exception):
    """Existing state cannot safely be read or replaced."""


def stable_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', value):
        raise DirectoryError('公會代碼須為 1–32 個小寫英文字母、數字、底線或連字號，首字須為字母或數字。')
    return value


def public_text(value: str, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DirectoryError(f'{label}格式不正確。')
    value = value.strip()
    if (not value and not empty) or len(value) > maximum:
        raise DirectoryError(f'{label}須為 {0 if empty else 1}–{maximum} 字。')
    if any(unicodedata.category(c).startswith('C') and not (empty and c == '\n') for c in value):
        raise DirectoryError(f'{label}不可包含控制字元；只有公開簡介可換行。')
    return value


def validate_card(card: dict) -> None:
    if not isinstance(card, dict) or set(card) != {'key', 'name', 'game', 'pic_id', 'notes', 'status', 'archived'}:
        raise DirectoryError('公會資料格式不完整。')
    stable_key(card['key'])
    for field, maximum, empty in [('name', 80, False), ('game', 80, False), ('notes', 700, True)]:
        if public_text(card[field], field, maximum, empty=empty) != card[field]:
            raise DirectoryError('公會資料格式不正確。')
    if type(card['pic_id']) is not int or not 0 < card['pic_id'] < 2**64:
        raise DirectoryError('聯絡 PIC 格式不正確。')
    if card['status'] not in STATUSES or type(card['archived']) is not bool:
        raise DirectoryError('招募／封存狀態不正確。')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class Directory:
    def __init__(self, path: Path, guild_id: int):
        self.path, self.guild_id = Path(path), guild_id

    def _load(self) -> dict:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {'version': 1, 'guild_id': self.guild_id, 'cards': {}}
        except OSError as exc:
            raise DirectoryUnavailable from exc
        try:
            if len(raw) > 4_000_000:
                raise ValueError('State too large')
            state = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(state, dict) or set(state) != {'version', 'guild_id', 'cards'}
                    or type(state['version']) is not int or state['version'] != 1
                    or type(state['guild_id']) is not int or state['guild_id'] != self.guild_id
                    or not isinstance(state['cards'], dict) or len(state['cards']) > MAX_CARDS):
                raise ValueError('Invalid directory schema')
            names = set()
            for key, card in state['cards'].items():
                validate_card(card)
                if key != card['key'] or card['name'].casefold() in names:
                    raise ValueError('Duplicate or mismatched identity')
                names.add(card['name'].casefold())
            return state
        except (ValueError, TypeError, UnicodeError, KeyError) as exc:
            raise DirectoryUnavailable from exc

    def cards(self, *, archived: bool = False) -> list[dict]:
        return sorted((c for c in self._load()['cards'].values() if c['archived'] == archived),
                      key=lambda c: (c['name'].casefold(), c['key']))

    def get(self, key: str) -> dict:
        card = self._load()['cards'].get(stable_key(key))
        if card is None:
            raise DirectoryError('找不到此公會代碼，請先用 /community list 查看。')
        return card

    def save(self, key: str, *, create: bool = False, **changes) -> dict:
        key = stable_key(key)
        state = self._load()
        cards = state['cards']
        if create:
            if key in cards:
                raise DirectoryError('此公會代碼已存在（可能已封存）；請編輯或還原原有公會。')
            if len(cards) >= MAX_CARDS:
                raise DirectoryError('目錄已達 500 張上限（包括封存），請聯絡維護人員。')
            card = dict(key=key, archived=False, **changes)
        else:
            if key not in cards:
                raise DirectoryError('找不到此公會代碼，請先用 /community list 查看。')
            card = dict(cards[key], **changes)
        validate_card(card)
        if any(c['key'] != key and c['name'].casefold() == card['name'].casefold() for c in cards.values()):
            raise DirectoryError('此公會名稱已存在（包括已封存，英文字母不分大小寫）；請加上分隊名稱。')
        cards[key] = card
        try:
            atomic_write_json(self.path, state)
        except OSError as exc:
            raise DirectoryUnavailable from exc
        return card
