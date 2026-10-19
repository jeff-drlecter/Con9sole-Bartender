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
from features.drink_constants import COLLECTION_PAGE_LIMIT
from features.drink_storage import (
    count_given_drinks,
    count_received_drinks,
    count_self_drinks,
    fetch_collection_rows,
    format_member_ref,
    format_recent_event,
    recent_given_drink,
    recent_received_drink,
    recent_self_drink,
    top_given_target,
    top_received_actor,
)


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


def build_drink_stats_embed(
    guild: discord.Guild | None, user: discord.Member | discord.User
) -> discord.Embed:
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
        top_given_text = (
            f"{format_member_ref(guild, top_given[0])}｜`{top_given[1]}` 次"
        )

    top_received_text = "暫時未有紀錄"
    if top_received is not None:
        top_received_text = (
            f"{format_member_ref(guild, top_received[0])}｜`{top_received[1]}` 次"
        )

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
    embed.add_field(
        name="最近自己叫酒",
        value=format_recent_event(guild, recent_self, user_id=user_id, kind="self"),
        inline=False,
    )
    embed.add_field(
        name="最近賜酒",
        value=format_recent_event(guild, recent_given, user_id=user_id, kind="given"),
        inline=False,
    )
    embed.add_field(
        name="最近收到賜酒",
        value=format_recent_event(
            guild, recent_received, user_id=user_id, kind="received"
        ),
        inline=False,
    )
    embed.set_footer(text="Con9sole Bartender｜酒保紀錄 v1")
    return embed


def build_drink_collection_embed(
    guild: discord.Guild | None, user: discord.Member | discord.User
) -> discord.Embed:
    guild_id = guild.id if guild else None
    user_id = user.id

    from features.collection_milestones import collection_snapshot, milestones

    snapshot = collection_snapshot(guild_id, user_id)
    catalog = drink_catalog()
    names = snapshot["names"]
    current = len(names & catalog.keys())
    awards = {award["milestone_id"]: award for award in snapshot["awards"]}
    next_goal = next(
        (
            goal
            for goal in sorted(milestones(), key=lambda g: g.target)
            if goal.key not in awards
        ),
        None,
    )
    title = awards.get(snapshot["selected"])
    description = f"已收藏 **{len(names):,} 款**不同酒\n目前酒譜：**{current:,}／{len(catalog):,}**（{current / max(1, len(catalog)):.1%}）"
    if title:
        description += f"\n🏅 {title['label']}"
    embed = discord.Embed(
        title=f"🍹 {user.display_name} 嘅酒譜", description=description, color=0x2B2D31
    )
    if next_goal:
        count = len(
            names
            if next_goal.catalog_names is None
            else names & next_goal.catalog_names
        )
        embed.add_field(
            name=f"下一站：{next_goal.label}",
            value=f"再收藏 **{max(0, next_goal.target - count):,} 款**新酒\n{progress_bar(count, next_goal.target)} {count:,}／{next_goal.target:,}",
            inline=False,
        )
    else:
        embed.add_field(
            name="🏆 今版里程碑全部達成！",
            value="新酒款加入後，仍然可以繼續探索。",
            inline=False,
        )
    rows = fetch_collection_rows(guild_id, user_id, limit=3)
    embed.add_field(
        name="最近收藏",
        value="\n".join(format_collection_row(row) for row in rows)
        or "飲一杯，或者收朋友請你飲嘅酒，就可以開始。",
        inline=False,
    )
    embed.add_field(
        name="🏅 收藏徽章",
        value=f"已解鎖 **{len(awards)} 個**，按「里程碑」睇詳情同揀展示稱號。",
        inline=False,
    )
    embed.set_footer(text="同款唔重複計｜舊收藏照計｜新送酒只計收酒者｜季節酒輪流供應")
    return embed


def build_drink_milestones_embed(
    guild: discord.Guild | None, user: discord.Member | discord.User
) -> discord.Embed:
    from features.collection_milestones import collection_snapshot, milestones

    snapshot = collection_snapshot(guild.id if guild else None, user.id)
    awards = {a["milestone_id"]: a for a in snapshot["awards"]}
    goals = milestones()
    lines = []
    for goal in goals:
        award = awards.get(goal.key)
        count = len(
            snapshot["names"]
            if goal.catalog_names is None
            else snapshot["names"] & goal.catalog_names
        )
        suffix = (
            f"達成於 {award['unlocked_at'][:10]}"
            if award
            else f"{min(count, goal.target):,}／{goal.target:,} 款"
        )
        lines.append(f"{'🏅' if award else '▫️'} **{goal.label}** · {suffix}")
    embed = discord.Embed(
        title=f"🏅 {user.display_name} 嘅收藏里程碑",
        description="\n".join(lines),
        color=0xD4AF37,
    )
    archived = [
        a for a in snapshot["awards"] if a["milestone_id"] not in {g.key for g in goals}
    ]
    if archived:
        embed.add_field(
            name="歷代酒譜紀念",
            value="\n".join(
                f"🏅 {a['label']} · 當時共 {a['catalog_total']:,} 款 · {a['unlocked_at'][:10]}"
                for a in archived[-6:]
            ),
            inline=False,
        )
    embed.set_footer(
        text="自動解鎖，唔使領獎｜舊紀錄補計，唔會補發通知｜紀念日期以 UTC 記錄"
    )
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
            list_text += (
                f"\n…仲有 `{unlocked - COLLECTION_PAGE_LIMIT}` 款已解鎖未顯示。"
            )
    else:
        list_text = "暫時未解鎖呢個稀有度嘅酒款。"

    hidden_text = (
        f"❔ `{locked}` 款仍藏喺吧枱深處。" if locked else "✅ 呢個稀有度已全部解鎖。"
    )

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


def build_drink_collection_recent_embed(
    guild: discord.Guild | None, user: discord.Member | discord.User
) -> discord.Embed:
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
    embed.set_footer(text="Con9sole Bartender｜最近收藏按首次解鎖時間排序。")
    return embed
