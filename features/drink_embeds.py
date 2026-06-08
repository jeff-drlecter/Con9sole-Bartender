from __future__ import annotations

import discord

from features.drink_catalog import (
    catalog_by_rarity,
    drink_catalog,
    format_collection_row,
    progress_bar,
    rarity_color,
    rarity_label,
)
from features.drink_storage import (
    count_given_drinks,
    count_given_unique_drinks,
    count_received_drinks,
    count_received_unique_drinks,
    count_self_drinks,
    count_self_unique_drinks,
    fetch_collection_rarity_counts,
    fetch_collection_rows,
    format_member_ref,
    format_recent_event,
    recent_given_drink,
    recent_received_drink,
    recent_self_drink,
    top_given_target,
    top_received_actor,
)

COLLECTION_PAGE_LIMIT = 12


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

    self_count = count_self_drinks(guild_id, user_id)
    given_count = count_given_drinks(guild_id, user_id)
    received_count = count_received_drinks(guild_id, user_id)
    total_count = self_count + given_count + received_count

    top_given = top_given_target(guild_id, user_id)
    top_received = top_received_actor(guild_id, user_id)

    recent_self = recent_self_drink(guild_id, user_id)
    recent_given = recent_given_drink(guild_id, user_id)
    recent_received = recent_received_drink(guild_id, user_id)

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

    self_unique = count_self_unique_drinks(guild_id, user_id)
    given_unique = count_given_unique_drinks(guild_id, user_id)
    received_unique = count_received_unique_drinks(guild_id, user_id)

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
