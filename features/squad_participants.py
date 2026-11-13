"""Per-card participant snapshots; never confuse attendance with subscriptions."""
from __future__ import annotations

import json

from core.sqlite_storage import connect_sqlite, initialize_once
from core.storage_paths import STATS_DB


@initialize_once
def initialize():
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS squad_participant_snapshots (
            message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, names TEXT NOT NULL, legacy TEXT NOT NULL)''')


def save(message_id, guild_id, channel_id, names):
    initialize()
    names = {str(uid): str(name) for uid, name in names.items() if str(uid).isdecimal()}
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('''INSERT INTO squad_participant_snapshots VALUES(?,?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET names=excluded.names,legacy=excluded.legacy
            WHERE guild_id=excluded.guild_id AND channel_id=excluded.channel_id''',
            (message_id, guild_id, channel_id, json.dumps(names, ensure_ascii=False), '[]'))


def preserve_legacy(message_id, guild_id, channel_id, lines):
    """Keep historical display text without guessing user IDs from old names."""
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        conn.execute('INSERT OR IGNORE INTO squad_participant_snapshots VALUES(?,?,?,?,?)',
            (message_id, guild_id, channel_id, '{}', json.dumps(lines, ensure_ascii=False)))


def get(message_id, guild_id, channel_id):
    initialize()
    with connect_sqlite(STATS_DB) as conn:
        row = conn.execute('''SELECT names,legacy FROM squad_participant_snapshots
            WHERE message_id=? AND guild_id=? AND channel_id=?''',
            (message_id, guild_id, channel_id)).fetchone()
    return dict(names=json.loads(row[0]), legacy=json.loads(row[1])) if row else None


def compact_legacy(embed):
    """Return names removed from an old embed so callers can save before editing."""
    legacy, lines = [], []
    for line in (embed.description or '').splitlines():
        if line.startswith('👥 ') and ' · ' in line:
            heading, names = line.split(' · ', 1)
            if names and not names.startswith('按「本局參與者」'):
                legacy.append(names)
                lines.append(heading + ' · 按「本局參與者」查看')
                continue
        lines.append(line)
    if embed.description is not None:
        embed.description = '\n'.join(lines)
    for index in reversed(range(len(embed.fields))):
        field = embed.fields[index]
        if field.name in {'一齊玩過', '一起玩過', '參與成員', '本局參與者'}:
            legacy.append(field.value)
            embed.remove_field(index)
    return legacy
