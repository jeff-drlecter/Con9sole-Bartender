"""Persistent stream roster and cadence. No credentials or webhook URLs are stored here."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

MEMBER_CHANNEL = 1299646760582381680
PARTNER_CHANNEL = 1401379808440745984
AUDIENCE_ROLE = 1401328542112944148
MAX_STREAMERS = 100


def normalize_login(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r'^https://(?:www\.)?twitch\.tv/', '', value).rstrip('/')
    if not re.fullmatch(r'[a-z0-9_]{1,25}', value):
        raise ValueError('請輸入有效 Twitch 帳號或 https://www.twitch.tv/帳號。')
    return value


def default_state() -> dict:
    return {'version': 1, 'enabled': False, 'partner_minutes': 30,
            'member_channel': MEMBER_CHANNEL, 'partner_channel': PARTNER_CHANNEL,
            'member_ping': True, 'entries': {}, 'metrics': {}}


class AlertStore:
    """A single snapshot transaction preserves roster and delivery state together."""
    def __init__(self, path: Path, bootstrap: str = ''):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS twitch_alert_state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
            row = db.execute('SELECT body FROM twitch_alert_state WHERE id=1').fetchone()
            if row:
                self.state = json.loads(row[0])  # Fail closed on corruption; never resend from empty defaults.
                if self.state.get('version') != 1:
                    raise ValueError('Unsupported Twitch alert state version')
            else:
                self.state = default_state()
                for item in json.loads(bootstrap or '[]'):
                    self.add(item['login'], item['group'], save=False)
                db.execute('INSERT INTO twitch_alert_state VALUES(1,?)', (json.dumps(self.state),))

    def save(self):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE twitch_alert_state SET body=? WHERE id=1', (json.dumps(self.state),))

    def add(self, login: str, group: str, *, save: bool = True):
        login = normalize_login(login)
        if group not in ('member', 'partner'):
            raise ValueError('類別請填 成員 或 友台。')
        entries = self.state['entries']
        if login in entries:
            raise ValueError('名單已有呢個帳號。')
        if len(entries) >= MAX_STREAMERS:
            raise ValueError('名單上限為 100 個帳號。')
        entries[login] = {'group': group, 'enabled': True, 'initialized': False,
                          'last_check': 0, 'stream_id': None, 'started_at': None,
                          'message_id': None, 'message_channel': None, 'pending': None}
        if save:
            self.save()
        return login

    def due(self, now: float) -> list[str]:
        return [login for login, e in self.state['entries'].items()
                if e['enabled'] and now - e['last_check'] >=
                (300 if e['group'] == 'member' else self.state['partner_minutes'] * 60)]


def transition(entry: dict, stream: dict | None) -> str:
    """Only valid complete Twitch responses may be passed to this function."""
    if not entry['initialized']:
        return 'baseline'
    if entry.get('pending'):
        return 'pending'
    if stream and stream['id'] != entry.get('stream_id'):
        return 'live'
    if not stream and entry.get('stream_id'):
        return 'offline'
    return 'unchanged'
