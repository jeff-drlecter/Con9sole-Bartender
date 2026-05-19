from __future__ import annotations

import time
from pathlib import Path

import discord

from core.permissions import is_admin_or_helper

MENU_COLOR = 0x2B2D31
COOLDOWN_SECONDS = 3.0
MENTION_DEDUPE_TTL_SECONDS = 300.0

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BARTENDER_IMAGE = ASSETS_DIR / "bartender.png"
BARTENDER_ATTACHMENT_NAME = "bartender.png"

USER_MENU_COOLDOWNS: dict[int, float] = {}
MENTION_MESSAGE_DEDUPE: dict[int, float] = {}


def can_use_admin(member: discord.Member | discord.User) -> bool:
    """Backward-compatible admin/helper checker."""
    return is_admin_or_helper(member)


can_use_admin_stats = can_use_admin


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


def apply_bartender_thumbnail(embed: discord.Embed) -> None:
    if BARTENDER_IMAGE.exists():
        embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


def get_retry_after(user_id: int) -> float:
    last_used = USER_MENU_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cooldown(user_id: int) -> None:
    USER_MENU_COOLDOWNS[user_id] = time.time()


def cleanup_mention_dedupe(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    expired_ids = [
        message_id
        for message_id, seen_at in MENTION_MESSAGE_DEDUPE.items()
        if now - seen_at >= MENTION_DEDUPE_TTL_SECONDS
    ]
    for message_id in expired_ids:
        MENTION_MESSAGE_DEDUPE.pop(message_id, None)

    if len(MENTION_MESSAGE_DEDUPE) > 1000:
        newest = sorted(MENTION_MESSAGE_DEDUPE.items(), key=lambda item: item[1], reverse=True)[:300]
        MENTION_MESSAGE_DEDUPE.clear()
        MENTION_MESSAGE_DEDUPE.update(dict(newest))


def claim_mention_message(message_id: int) -> bool:
    now = time.time()
    cleanup_mention_dedupe(now)
    if message_id in MENTION_MESSAGE_DEDUPE:
        return False
    MENTION_MESSAGE_DEDUPE[message_id] = now
    return True
