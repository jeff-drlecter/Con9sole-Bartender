"""Small opt-in-at-call-site hints; never send messages or translate member text."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import random
import time
from zoneinfo import ZoneInfo

import discord

import config
from core.sqlite_storage import connect_sqlite
from core.storage_paths import DATA_DIR
from features.language_preferences import language

log = logging.getLogger(__name__)
HINT_DB = DATA_DIR / 'member_hints.sqlite3'
HK = ZoneInfo('Asia/Hong_Kong')
DISPLAY_CHANCE = 0.25
MENTION_WEIGHT = 0.60
DAILY_LIMIT = 2
MIN_INTERVAL = 30 * 60
PUBLIC_CONTEXTS = {'drink', 'cheers'}
PRIVATE_CONTEXTS = {'menu', 'more'}


@dataclass(frozen=True)
class Tip:
    key: str
    kind: str
    contexts: tuple[str, ...]
    cogs: tuple[str, ...]
    neutral: str
    hk: str

    def text(self, bot_id: int, code: str) -> str:
        return (self.hk if code == 'hk' else self.neutral).format(bot=f'<@{bot_id}>')


ALL_CONTEXTS = ('drink', 'cheers', 'menu', 'more')
TIPS = (
    Tip('mention_open', 'mention', ALL_CONTEXTS, ('Menu',),
        '單獨提及 {bot}，再按「開主選單」。',
        '單獨 tag {bot}，再撳「開主選單」。'),
    Tip('mention_find', 'mention', ALL_CONTEXTS, ('Menu',),
        '找不到功能？單獨提及 {bot} 開啟選單。',
        '搵唔到功能？單獨 tag {bot} 開選單。'),
    Tip('mention_shortcut', 'mention', ALL_CONTEXTS, ('Menu',),
        '不用記指令：單獨提及 {bot}，從按鈕開始。',
        '唔使記指令：單獨 tag {bot}，由按鈕開始。'),
    Tip('collection', 'feature', ('drink', 'menu', 'more'), ('Drink',),
        '「我的收藏」可以查看已收集的飲品與進度。',
        '「我的收藏」可以睇已收集嘅飲品同進度。'),
    Tip('gift', 'feature', ('drink', 'menu', 'more'), ('Drink',),
        '除了自己喝一杯，也可以請朋友喝一杯。',
        '除咗自己飲一杯，亦可以請朋友飲一杯。'),
    Tip('plan', 'feature', ('cheers', 'menu', 'more'), ('SquadPlans',),
        '今晚才有空？用「約一局」先約好時間與人數。',
        '今晚先得閒？用「約一局」先約好時間同人數。'),
    Tip('next_game', 'feature', ('cheers', 'menu', 'more'), ('SquadCards',),
        '「下次預埋」只提醒下一次；持續關注可選「長期跟局」。',
        '「下次預埋」只提醒下一次；想長期收通知可揀「長期跟局」。'),
    Tip('notifications', 'feature', ('cheers', 'menu', 'more'), ('SquadCards',),
        '想調整組隊提醒？到「偏好與設定 → 我的組隊通知」管理。',
        '想改組隊提醒？去「偏好同設定 → 我的組隊通知」管理。'),
    Tip('member_card', 'feature', ALL_CONTEXTS, ('CommunityLevels',),
        '「我的會員卡」可以查看等級、經驗值與稱號。',
        '「我的會員卡」可以睇等級、經驗值同稱號。'),
    Tip('daily', 'feature', ALL_CONTEXTS, ('CommunityLevels', 'DailyBar'),
        '今日小任務可從會員卡進入，自由參加。',
        '今日小任務可以由會員卡入，自由參加。'),
    Tip('language', 'feature', ALL_CONTEXTS, ('LanguagePreferences',),
        '香港或台灣用語都可以，到「語言設定」隨時切換。',
        '香港或台灣用語都得，去「語言設定」隨時轉。'),
)


class HintStore:
    def __init__(self, path: Path):
        self.path = path

    def reserve(self, guild: int, scope: str, scope_id: int, interaction_id: int,
                tips: list[Tip], *, now: float | None = None, rng=random) -> Tip | None:
        """Reserve before delivery. An uncertain send consumes its slot, never retries."""
        if not tips or rng.random() >= DISPLAY_CHANCE:
            return None
        now = time.time() if now is None else now
        day = datetime.fromtimestamp(now, HK).date().isoformat()
        with connect_sqlite(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS hint_scopes (
                    guild INTEGER NOT NULL, scope TEXT NOT NULL, scope_id INTEGER NOT NULL,
                    day TEXT NOT NULL, count INTEGER NOT NULL, stamp REAL NOT NULL,
                    last_tip TEXT NOT NULL, PRIMARY KEY(guild,scope,scope_id));
                CREATE TABLE IF NOT EXISTS hint_receipts (
                    interaction INTEGER PRIMARY KEY, stamp REAL NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM hint_receipts WHERE interaction=?', (interaction_id,)).fetchone():
                return None
            row = db.execute('SELECT day,count,stamp,last_tip FROM hint_scopes WHERE guild=? AND scope=? AND scope_id=?',
                             (guild, scope, scope_id)).fetchone()
            count = row[1] if row and row[0] == day else 0
            if count >= DAILY_LIMIT or (row and now - row[2] < MIN_INTERVAL):
                return None
            kind = 'mention' if rng.random() < MENTION_WEIGHT else 'feature'
            candidates = [tip for tip in tips if tip.kind == kind]
            if not candidates:
                return None  # Missing capabilities never alter the requested weight.
            fresh = [tip for tip in candidates if not row or tip.key != row[3]]
            if not fresh:
                return None
            tip = rng.choice(fresh)
            db.execute('INSERT INTO hint_receipts VALUES(?,?)', (interaction_id, now))
            db.execute('INSERT OR REPLACE INTO hint_scopes VALUES(?,?,?,?,?,?,?)',
                       (guild, scope, scope_id, day, count + 1, now, tip.key))
            # Interaction tokens expire far earlier; keep two days for uncertain retries.
            db.execute('DELETE FROM hint_receipts WHERE stamp<?', (now - 2 * 86400,))
        return tip


async def add_member_hint(bot, interaction, embed: discord.Embed, *, context: str,
                          private: bool = False) -> None:
    """Decorate only approved success surfaces; errors leave the original untouched."""
    if os.getenv('MEMBER_HINTS_ENABLED', '1').casefold() not in {'1', 'true', 'yes'}:
        return
    if context not in (PRIVATE_CONTEXTS if private else PUBLIC_CONTEXTS):
        return
    try:
        guild_id, channel_id = interaction.guild_id, interaction.channel_id
        user_id, event_id = interaction.user.id, interaction.id
        bot_id = bot.user.id
        if (guild_id != config.GUILD_ID or interaction.user.bot
                or not all(type(value) is int and value > 0 for value in (guild_id, channel_id, user_id, event_id, bot_id))):
            return
        description = embed.description or ''
        if '\n\n💡 ' in description:
            return
        code = language(interaction.user) if private else 'neutral'
        tips = [tip for tip in TIPS if context in tip.contexts
                and all(bot.get_cog(name) is not None for name in tip.cogs)]
        # Reserve only a tip which fits without trimming existing information.
        tips = [tip for tip in tips if len(description) + len(tip.text(bot_id, code)) + 5 <= 4096
                and len(embed) + len(tip.text(bot_id, code)) + 5 <= 6000]
        if not tips:
            return
        # Optional copy must not delay an interaction's initial acknowledgement.
        # A timed-out thread can still reserve a slot; conservatively keep it.
        async with asyncio.timeout(0.25):
            tip = await asyncio.to_thread(HintStore(HINT_DB).reserve, guild_id,
                                          'private' if private else 'public',
                                          user_id if private else channel_id, event_id, tips)
        if tip:
            embed.description = description + '\n\n💡 ' + tip.text(bot_id, code)
    except Exception as exc:
        # Hints are optional: no member content, IDs or credentials in error output.
        log.warning('Member hint skipped: %s', type(exc).__name__)
