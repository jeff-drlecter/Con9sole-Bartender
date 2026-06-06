from __future__ import annotations

import asyncio
import atexit
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import Deque, Dict, List

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.safe_send import send_or_followup
from data.drink_data import (
    ALL_DRINKS,
    BARTENDER_ATTACHMENT_NAME,
    DRINK_COOLDOWN_SECONDS,
    DrinkEntry,
    ICON_MAP,
    RARITY_STYLE,
    RECENT_HISTORY_LIMIT,
    SEASONAL_DRINKS,
)
from features.drink_catalog import (
    build_tasting_note,
    catalog_by_rarity,
    drink_catalog,
    format_collection_row,
    progress_bar,
    rarity_color,
    rarity_label,
)
from features.drink_result import build_bartender_result_payload
from features.drink_storage import (
    DATA_DIR,
    EVENT_GIFT_DRINK,
    EVENT_SELF_DRINK,
    count_distinct_drinks,
    count_events,
    fetch_collection_rarity_counts,
    fetch_collection_rows,
    format_member_ref,
    format_recent_event,
    init_drink_events_db,
    recent_event,
    record_drink_event,
    top_member_id,
)


DRINK_STATE_PATH = DATA_DIR / "drink_state.json"

GIFT_DRINK_TARGET_TIMEOUT_SECONDS = 60.0
COLLECTION_PAGE_LIMIT = 12


def _default_drink_state() -> dict[str, object]:
    return {
        "version": 2,
        "cooldowns": {},
        "gift_cooldowns": {},
        "recent_drinks": {},
    }


def _load_drink_state() -> dict[str, object]:
    try:
        if not DRINK_STATE_PATH.exists():
            return _default_drink_state()

        raw = json.loads(DRINK_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _default_drink_state()

        raw.setdefault("version", 2)
        raw.setdefault("cooldowns", {})
        raw.setdefault("gift_cooldowns", {})
        raw.setdefault("recent_drinks", {})
        return raw
    except Exception:
        return _default_drink_state()


_DRINK_STATE: dict[str, object] = _load_drink_state()


def _state_cooldowns() -> dict[str, float]:
    data = _DRINK_STATE.setdefault("cooldowns", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["cooldowns"] = data
    return data  # type: ignore[return-value]


def _state_gift_cooldowns() -> dict[str, float]:
    data = _DRINK_STATE.setdefault("gift_cooldowns", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["gift_cooldowns"] = data
    return data  # type: ignore[return-value]


def _state_recent_drinks() -> dict[str, list[str]]:
    data = _DRINK_STATE.setdefault("recent_drinks", {})
    if not isinstance(data, dict):
        data = {}
        _DRINK_STATE["recent_drinks"] = data
    return data  # type: ignore[return-value]


def _save_drink_state() -> None:
    try:
        DRINK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DRINK_STATE_PATH.with_suffix(DRINK_STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(_DRINK_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DRINK_STATE_PATH)
    except Exception:
        pass


DRINK_USER_COOLDOWNS: dict[int, float] = {
    int(user_id): float(ts)
    for user_id, ts in _state_cooldowns().items()
    if str(user_id).isdigit()
}

GIFT_DRINK_USER_COOLDOWNS: dict[int, float] = {
    int(user_id): float(ts)
    for user_id, ts in _state_gift_cooldowns().items()
    if str(user_id).isdigit()
}

atexit.register(_save_drink_state)


@dataclass
class GiftDrinkPending:
    started_at: float
    cancel_event: asyncio.Event


PENDING_GIFT_DRINK_REQUESTS: dict[int, GiftDrinkPending] = {}


def get_drink_retry_after(user_id: int) -> float:
    last_used = DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def get_gift_drink_retry_after(user_id: int) -> float:
    last_used = GIFT_DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def has_drink_cooldown(user_id: int) -> bool:
    return get_drink_retry_after(user_id) > 0


def has_gift_drink_cooldown(user_id: int) -> bool:
    return get_gift_drink_retry_after(user_id) > 0


def touch_drink_cooldown(user_id: int) -> None:
    ts = time.time()
    DRINK_USER_COOLDOWNS[user_id] = ts
    _state_cooldowns()[str(user_id)] = ts
    _save_drink_state()


def touch_gift_drink_cooldown(user_id: int) -> None:
    ts = time.time()
    GIFT_DRINK_USER_COOLDOWNS[user_id] = ts
    _state_gift_cooldowns()[str(user_id)] = ts
    _save_drink_state()


def clear_drink_cooldown(user_id: int) -> None:
    DRINK_USER_COOLDOWNS.pop(user_id, None)
    _state_cooldowns().pop(str(user_id), None)
    _save_drink_state()


def clear_gift_drink_cooldown(user_id: int) -> None:
    GIFT_DRINK_USER_COOLDOWNS.pop(user_id, None)
    _state_gift_cooldowns().pop(str(user_id), None)
    _save_drink_state()


def cleanup_pending_gift_requests() -> None:
    now = time.time()
    expired_user_ids = [
        user_id
        for user_id, pending in PENDING_GIFT_DRINK_REQUESTS.items()
        if now - pending.started_at >= GIFT_DRINK_TARGET_TIMEOUT_SECONDS
    ]
    for user_id in expired_user_ids:
        pending = PENDING_GIFT_DRINK_REQUESTS.pop(user_id, None)
        if pending is not None and not pending.cancel_event.is_set():
            pending.cancel_event.set()


def current_seasonal_pool() -> List[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return pool
    return []


def build_gift_prompt_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🥂 賜酒",
        description=(
            f"{user.mention}，請喺 **60 秒內** 喺呢個 channel tag 一位你想賜酒嘅成員。\n\n"
            "例：`@jeff`\n\n"
            "你亦可以撳下面嘅 **取消** 按鈕。"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜只會讀取你下一個訊息。")
    return embed


def build_drink_stats_embed(guild: discord.Guild | None, user: discord.Member | discord.User) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id

    self_count = count_events(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )
    given_count = count_events(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    received_count = count_events(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    total_count = self_count + given_count + received_count

    top_given = top_member_id(
        guild_id,
        "target_id",
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    top_received = top_member_id(
        guild_id,
        "actor_id",
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )

    recent_self = recent_event(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )
    recent_given = recent_event(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    recent_received = recent_event(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )

    top_given_text = "暫時未有紀錄"
    if top_given is not None:
        top_given_text = f"{format_member_ref(guild, top_given[0])}｜`{top_given[1]}` 次"

    top_received_text = "暫時未有紀錄"
    if top_received is not None:
        top_received_text = f"{format_member_ref(guild, top_received[0])}｜`{top_received[1]}` 次"

    embed = discord.Embed(
        title=f"🥂 {user.display_name} 的酒保紀錄",
        description=(
            f"🍹 **自己叫酒：** `{self_count}` 杯\n"
            f"🥂 **賜酒畀人：** `{given_count}` 杯\n"
            f"🍷 **收到賜酒：** `{received_count}` 杯\n"
            f"📊 **總酒保互動：** `{total_count}` 次"
        ),
        color=0x2B2D31,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="最常賜酒對象", value=top_given_text, inline=False)
    embed.add_field(name="最常收到來自", value=top_received_text, inline=False)
    embed.add_field(name="最近自己叫酒", value=format_recent_event(guild, recent_self, user_id=user_id, kind="self"), inline=False)
    embed.add_field(name="最近賜酒", value=format_recent_event(guild, recent_given, user_id=user_id, kind="given"), inline=False)
    embed.add_field(name="最近收到賜酒", value=format_recent_event(guild, recent_received, user_id=user_id, kind="received"), inline=False)
    embed.set_footer(text="Con9sole Bartender｜酒保紀錄 v1")
    return embed


def build_drink_collection_embed(guild: discord.Guild | None, user: discord.Member | discord.User) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id

    catalog = drink_catalog()
    grouped_catalog = catalog_by_rarity()
    total_catalog = len(catalog)

    all_rows = fetch_collection_rows(guild_id, user_id)
    unlocked_total = len(all_rows)
    progress = (unlocked_total / total_catalog * 100) if total_catalog else 0.0
    bar = progress_bar(unlocked_total, total_catalog)

    self_unique = count_distinct_drinks(
        guild_id,
        "event_type = ? AND actor_id = ? AND target_id = ?",
        (EVENT_SELF_DRINK, user_id, user_id),
    )
    given_unique = count_distinct_drinks(
        guild_id,
        "event_type = ? AND actor_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )
    received_unique = count_distinct_drinks(
        guild_id,
        "event_type = ? AND target_id = ?",
        (EVENT_GIFT_DRINK, user_id),
    )

    unlocked_by_rarity = fetch_collection_rarity_counts(guild_id, user_id)
    rarity_lines: list[str] = []
    for rarity, drinks in grouped_catalog.items():
        total = len(drinks)
        unlocked = unlocked_by_rarity.get(rarity, 0)
        rarity_lines.append(f"{rarity_label(rarity)}：`{unlocked}` / `{total}`")

    recent_rows = all_rows[:5]
    recent_text = "暫時未有解鎖紀錄"
    if recent_rows:
        recent_text = "\n".join(format_collection_row(row) for row in recent_rows)

    embed = discord.Embed(
        title=f"🍾 {user.display_name} 的酒單收藏",
        description=(
            f"**已解鎖酒款：** `{unlocked_total}` / `{total_catalog}`\n"
            f"**收藏進度：** `{progress:.1f}%`\n"
            f"`{bar}`\n\n"
            f"🍹 **自己叫酒解鎖：** `{self_unique}` 款\n"
            f"🍷 **收到賜酒解鎖：** `{received_unique}` 款\n"
            f"🥂 **賜酒畀人解鎖：** `{given_unique}` 款"
        ),
        color=0x2B2D31,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="稀有度收藏", value="\n".join(rarity_lines) or "暫時未有資料", inline=False)
    embed.add_field(name="最近解鎖", value=recent_text, inline=False)
    embed.set_footer(text="Con9sole Bartender｜🍹 自己叫酒｜🍷 收到賜酒｜🥂 賜酒畀人")
    return embed


def build_drink_collection_rarity_embed(
    guild: discord.Guild | None,
    user: discord.Member | discord.User,
    rarity: str,
) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id

    grouped_catalog = catalog_by_rarity()
    total = len(grouped_catalog.get(rarity, []))
    rows = fetch_collection_rows(guild_id, user_id, rarity=rarity)
    unlocked = len(rows)
    locked = max(0, total - unlocked)

    shown_rows = rows[:COLLECTION_PAGE_LIMIT]
    if shown_rows:
        list_text = "\n".join(format_collection_row(row) for row in shown_rows)
        if unlocked > COLLECTION_PAGE_LIMIT:
            list_text += f"\n…仲有 `{unlocked - COLLECTION_PAGE_LIMIT}` 款已解鎖未顯示。"
    else:
        list_text = "暫時未解鎖呢個稀有度嘅酒款。"

    hidden_text = f"❔ `{locked}` 款仍藏喺吧枱深處。" if locked else "✅ 呢個稀有度已全部解鎖。"

    embed = discord.Embed(
        title=f"🍾 {user.display_name} 的{rarity_label(rarity)}收藏",
        description=(
            f"**解鎖進度：** `{unlocked}` / `{total}`\n"
            f"`{progress_bar(unlocked, total)}`\n\n"
            f"**已解鎖**\n"
            f"{list_text}\n\n"
            f"**未解鎖**\n"
            f"{hidden_text}"
        ),
        color=rarity_color(rarity),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Con9sole Bartender｜不顯示未解鎖酒名，保留探索感。")
    return embed


def build_drink_collection_recent_embed(guild: discord.Guild | None, user: discord.Member | discord.User) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id
    rows = fetch_collection_rows(guild_id, user_id, limit=COLLECTION_PAGE_LIMIT)

    if rows:
        text = "\n".join(format_collection_row(row) for row in rows)
    else:
        text = "暫時未有解鎖紀錄。先去吧枱叫一杯，或者等朋友賜一杯酒俾你。"

    embed = discord.Embed(
        title=f"🕒 {user.display_name} 最近解鎖酒款",
        description=text,
        color=0x2B2D31,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Con9sole Bartender｜最近解鎖會按最後互動時間排序。")
    return embed


class DrinkCollectionView(discord.ui.View):
    def __init__(self, *, owner_id: int, guild: discord.Guild | None, target_user: discord.Member | discord.User) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.guild = guild
        self.target_user = target_user
        self._add_rarity_buttons()

    def _add_rarity_buttons(self) -> None:
        button_styles = [
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.primary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.danger,
        ]
        for index, rarity in enumerate(list(RARITY_STYLE.keys())[:4]):
            meta = RARITY_STYLE.get(rarity, {})
            label = str(meta.get("label", rarity))[:80]
            emoji = str(meta.get("emoji", "🍸"))
            style = button_styles[index] if index < len(button_styles) else discord.ButtonStyle.secondary
            self.add_item(DrinkCollectionRarityButton(rarity=rarity, label=label, emoji=emoji, style=style, row=0))

        self.add_item(DrinkCollectionRecentButton(row=1))
        self.add_item(DrinkCollectionSummaryButton(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個酒單收藏面板只限發起者使用。", ephemeral=True)
            return False
        return True


class DrinkCollectionRarityButton(discord.ui.Button):
    def __init__(self, *, rarity: str, label: str, emoji: str, style: discord.ButtonStyle, row: int) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.rarity = rarity

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_rarity_embed(self.view.guild, self.view.target_user, self.rarity)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionRecentButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(label="最近解鎖", emoji="🕒", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_recent_embed(self.view.guild, self.view.target_user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class DrinkCollectionSummaryButton(discord.ui.Button):
    def __init__(self, *, row: int) -> None:
        super().__init__(label="總覽", emoji="🍾", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, DrinkCollectionView):
            await interaction.response.send_message("❌ 酒單收藏面板狀態異常，請重新開啟。", ephemeral=True)
            return

        embed = build_drink_collection_embed(self.view.guild, self.view.target_user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class GiftDrinkCancelView(discord.ui.View):
    def __init__(self, *, owner_id: int, cancel_event: asyncio.Event) -> None:
        super().__init__(timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.cancel_event = cancel_event

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個賜酒取消按鈕只限發起者使用。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.cancel_event.is_set():
            await interaction.response.send_message("賜酒操作已經取消或逾時。", ephemeral=True)
            return

        self.cancel_event.set()
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(content="已取消賜酒。", embed=None, view=self)
        self.stop()


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

        for raw_user_id, drinks in _state_recent_drinks().items():
            try:
                user_id = int(raw_user_id)
            except Exception:
                continue
            if isinstance(drinks, list):
                self.user_recent_draws[user_id] = deque(
                    [str(item) for item in drinks][-RECENT_HISTORY_LIMIT:],
                    maxlen=RECENT_HISTORY_LIMIT,
                )

        init_drink_events_db()

    async def _record_usage(self, interaction: discord.Interaction, feature: str = "drink") -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage(feature, interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _check_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

    async def _check_gift_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_gift_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在準備賜酒，請等 {retry_after:.1f} 秒後再試。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False
        return True

    async def _enforce_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        ok = await self._check_drink_cooldown(interaction)
        if not ok:
            return False

        touch_drink_cooldown(interaction.user.id)
        return True

    async def _enforce_gift_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        ok = await self._check_gift_drink_cooldown(interaction)
        if not ok:
            return False

        touch_gift_drink_cooldown(interaction.user.id)
        return True

    def _pick_rarity(self) -> str:
        labels = list(RARITY_STYLE.keys())
        weights = [RARITY_STYLE[label]["weight"] for label in labels]
        return random.choices(labels, weights=weights, k=1)[0]

    def _build_pool_for_rarity(self, rarity: str) -> List[DrinkEntry]:
        pool = [drink for drink in ALL_DRINKS if drink.rarity == rarity]
        seasonal = [drink for drink in current_seasonal_pool() if drink.rarity == rarity]
        return pool + seasonal

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        pool = self._build_pool_for_rarity(rarity)
        if not pool:
            pool = ALL_DRINKS + current_seasonal_pool()

        recent = set(self.user_recent_draws[user_id])

        weights = [
            1 if drink.eng in recent else 4
            for drink in pool
        ]

        chosen = random.choices(pool, weights=weights, k=1)[0]
        self.user_recent_draws[user_id].append(chosen.eng)

        _state_recent_drinks()[str(user_id)] = list(self.user_recent_draws[user_id])
        _save_drink_state()

        return chosen

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None,
        drink: DrinkEntry,
    ) -> str:
        icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])
        giver = interaction.user.mention
        receiver = (to or interaction.user).mention
        drink_name = f"**{drink.eng}（{drink.zh}）**"

        if to and to.id != interaction.user.id:
            return f"{icon} {giver} 賜一杯 {drink_name} 給 {receiver}。"

        return f"{icon} Bartender Special：酒保為 {giver} 調製了一杯 {drink_name}。"

    async def _wait_for_gift_target(self, interaction: discord.Interaction) -> discord.Member | None:
        if interaction.channel is None:
            await send_or_followup(interaction, content="❌ 搵唔到目前 channel，請重新試一次。", ephemeral=True)
            return None

        cleanup_pending_gift_requests()
        if interaction.user.id in PENDING_GIFT_DRINK_REQUESTS:
            await send_or_followup(
                interaction,
                content="⏳ 你已經有一個等待 tag 對象嘅賜酒操作。請先完成，或者撳該訊息嘅取消按鈕。",
                ephemeral=True,
            )
            return None

        # IMPORTANT:
        # Opening the gift prompt must NOT consume cooldown.
        # Cancel / timeout / invalid target must NOT consume cooldown.
        # Gift cooldown is separate from self-drink cooldown.
        # Cooldown is consumed only when a valid target is confirmed and the drink is actually sent.
        ok = await self._check_gift_drink_cooldown(interaction)
        if not ok:
            return None

        cancel_event = asyncio.Event()
        PENDING_GIFT_DRINK_REQUESTS[interaction.user.id] = GiftDrinkPending(
            started_at=time.time(),
            cancel_event=cancel_event,
        )

        view = GiftDrinkCancelView(owner_id=interaction.user.id, cancel_event=cancel_event)
        await send_or_followup(
            interaction,
            embed=build_gift_prompt_embed(interaction.user),
            view=view,
            ephemeral=True,
        )

        def check(message: discord.Message) -> bool:
            if message.author.bot:
                return False
            if message.author.id != interaction.user.id:
                return False
            if message.channel.id != interaction.channel_id:
                return False
            return True

        message_task = asyncio.create_task(
            self.bot.wait_for(
                "message",
                check=check,
                timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS,
            )
        )
        cancel_task = asyncio.create_task(cancel_event.wait())

        try:
            done, pending_tasks = await asyncio.wait(
                {message_task, cancel_task},
                timeout=GIFT_DRINK_TARGET_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending_tasks:
                task.cancel()

            if cancel_task in done and cancel_event.is_set():
                return None

            if message_task not in done:
                await interaction.followup.send("⏳ 已逾時，賜酒已取消。", ephemeral=True)
                return None

            try:
                message = message_task.result()
            except asyncio.TimeoutError:
                await interaction.followup.send("⏳ 已逾時，賜酒已取消。", ephemeral=True)
                return None
        finally:
            PENDING_GIFT_DRINK_REQUESTS.pop(interaction.user.id, None)
            view.stop()

        if message.content.strip().casefold() in {"cancel", "取消", "stop"}:
            await interaction.followup.send("已取消賜酒。", ephemeral=True)
            return None

        if len(message.mentions) != 1:
            await interaction.followup.send("❌ 請只 tag 一位成員。", ephemeral=True)
            return None

        target = message.mentions[0]
        if not isinstance(target, discord.Member):
            if interaction.guild is not None:
                target = interaction.guild.get_member(target.id)

        if target is None or not isinstance(target, discord.Member):
            await interaction.followup.send("❌ 搵唔到呢位成員，請重新試一次。", ephemeral=True)
            return None

        if target.id == interaction.user.id:
            await interaction.followup.send("🍹 想自己飲可以直接用調酒，賜酒請 tag 另一位成員。", ephemeral=True)
            return None

        if target.bot:
            await interaction.followup.send("🤖 酒保暫時唔向 bot 賜酒，請 tag 一位真人成員。", ephemeral=True)
            return None

        return target

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
        feature: str | None = None,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_drink_cooldown(interaction)
            if not ok:
                return

        is_gift = bool(to and to.id != interaction.user.id)
        event_type = EVENT_GIFT_DRINK if is_gift else EVENT_SELF_DRINK
        usage_feature = feature or ("drink_gift" if is_gift else "drink")

        await self._record_usage(interaction, feature=usage_feature)

        rarity = self._pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        record_drink_event(
            guild_id=interaction.guild_id,
            event_type=event_type,
            actor_id=interaction.user.id,
            target_id=to.id if is_gift and to is not None else interaction.user.id,
            drink=drink,
        )

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 **限定供應：** {drink.limited_tag}" if drink.limited_tag else ""
        tasting_note = build_tasting_note(drink)
        style_icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])

        rarity_line = f"{rarity_meta['emoji']} {rarity_meta['label']}"
        style_line = f"{style_icon} {drink.typ}"
        rotation_line = f"最近 {RECENT_HISTORY_LIMIT} 杯低機率重複"

        result_embed = discord.Embed(
            title="🍹 Bartender’s Pick",
            description=(
                f"{header}\n\n"
                f"**品飲筆記**\n"
                f"➡️ {tasting_note}{limited_text}\n\n"
                f"**吧枱卡**\n"
                f"`{rarity_line}` ｜ `{style_line}` ｜ `{rotation_line}`"
            ),
            color=rarity_meta["color"],
            timestamp=discord.utils.utcnow(),
        )
        result_embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")

        send_kwargs = build_bartender_result_payload(
            interaction,
            result_embed,
            attachment_name=BARTENDER_ATTACHMENT_NAME,
        )

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self.do_drink(interaction, enforce_cooldown=True)

    async def gift_drink_entry(self, interaction: discord.Interaction) -> None:
        # Menu gift flow:
        # 1. Open prompt without consuming cooldown.
        # 2. Cancel / timeout / invalid tag does not consume cooldown.
        # 3. Gift cooldown is separate from self-drink cooldown.
        # 4. A valid target consumes gift cooldown only.
        # 5. do_drink(... enforce_cooldown=False) prevents self-drink cooldown from blocking gifts.
        target = await self._wait_for_gift_target(interaction)
        if target is None:
            return

        touch_gift_drink_cooldown(interaction.user.id)

        await self.do_drink(
            interaction,
            to=target,
            enforce_cooldown=False,
            feature="drink_gift",
        )

    async def stats_entry(self, interaction: discord.Interaction) -> None:
        embed = build_drink_stats_embed(interaction.guild, interaction.user)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    async def collection_entry(self, interaction: discord.Interaction) -> None:
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, interaction.user)
        view = DrinkCollectionView(owner_id=interaction.user.id, guild=interaction.guild, target_user=interaction.user)
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="由酒保為你或指定成員調一杯特選飲品")
    @app_commands.describe(to="收酒嘅人；留空即係自己叫酒")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None) -> None:
        if to is not None and to.id != interaction.user.id:
            ok = await self._enforce_gift_drink_cooldown(interaction)
            if not ok:
                return

            await self.do_drink(
                interaction,
                to,
                enforce_cooldown=False,
                feature="drink_gift",
            )
            return

        await self.do_drink(interaction, to, enforce_cooldown=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_stats", description="查看自己或指定成員的酒保紀錄")
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        embed = build_drink_stats_embed(interaction.guild, target)
        await send_or_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink_collection", description="查看自己或指定成員的酒單收藏")
    @app_commands.describe(user="要查看嘅成員；留空即係自己")
    async def drink_collection(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        await self._record_usage(interaction, feature="drink_collection")
        embed = build_drink_collection_embed(interaction.guild, target)
        view = DrinkCollectionView(owner_id=interaction.user.id, guild=interaction.guild, target_user=target)
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Drink(bot))
