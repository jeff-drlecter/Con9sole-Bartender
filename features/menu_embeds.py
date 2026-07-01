from __future__ import annotations

import random

import discord

import config
from features.menu_helpers import MENU_COLOR, apply_bartender_thumbnail

COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")

PUBLIC_DISCUSSION_TIPS = (
    "想關注或分享寵物大小事？",
    "想分享最近聽到的音樂？",
    "想討論正在追看的電視劇？",
    "想分享電影、飲食或生活話題？",
)


def _public_discussion_tip() -> str:
    return random.choice(PUBLIC_DISCUSSION_TIPS)


def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            f"歡迎回來，{user.mention}。\n\n"
            "**想快速做些甚麼？**"
        ),
        color=MENU_COLOR,
    )
    embed.add_field(
        name="⚡ Quick Bar",
        value="常用功能已放在下面。想查看完整入口，可以按「Menu」。",
        inline=False,
    )
    embed.add_field(
        name="🌊 探索公海區",
        value="進入「Menu」後按「探索公海」，即可了解如何瀏覽及參與遊戲以外的話題。",
        inline=False,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text=f"💡 {_public_discussion_tip()} 前往 Menu → 探索公海看看吧。")
    return embed


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_home_menu_embed(user: discord.abc.User, *, include_thumbnail: bool = True) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            f"歡迎回來，{user.mention}。\n\n"
            "完整餐牌已打開。\n"
            "**你想由哪裏開始？**"
        ),
        color=MENU_COLOR,
    )
    embed.add_field(
        name="🥃 吧枱服務",
        value="組隊、開 call、打氣、調酒、匿名投稿，都可以在下面使用。",
        inline=False,
    )
    embed.add_field(
        name="🌊 探索公海區",
        value="按「探索公海」瀏覽遊戲以外的公開話題，或了解如何開放相關討論區。",
        inline=False,
    )
    embed.add_field(
        name="📖 不確定應按哪一個？",
        value="按「幫助」查看完整用法。",
        inline=False,
    )
    if include_thumbnail:
        apply_bartender_thumbnail(embed)
    embed.set_footer(text=f"💡 {_public_discussion_tip()} 可由「探索公海」開始。")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description=(
            "**Bartender 使用說明**\n\n"
            "👥 **組隊**｜發起組隊 / 招募隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **小隊 call 控制**｜改人數上限 / 刪除自己的小隊 call\n\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🙌 **幫人打氣**｜tag 一位成員，送一句打氣給對方\n"
            "🕯️ **無名告白**｜匿名投稿\n\n"
            "🍹 **調酒**｜抽一杯酒保特選飲品\n"
            "🥂 **賜酒**｜tag 一位成員，賜一杯酒給對方\n"
            "📊 **酒保紀錄**｜查看自己叫酒 / 賜酒 / 收到賜酒紀錄\n"
            "🍾 **酒單收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n"
            "🏆 **酒保排行榜**｜查看叫酒 / 賜酒 / 收酒 / 收藏榜\n"
            "📅 **今日任務**｜查看每日吧枱任務\n\n"
            "🌊 **探索公海**｜瀏覽遊戲以外的公開話題，或前往身份設定開放公海區\n"
            "🔗 **邀請**｜取得社群邀請碼\n"
            "📸 **IG**｜查看官方 Instagram\n"
            "🧵 **Threads**｜查看官方 Threads\n\n"
            "ℹ️ **幫助**｜查看這份使用說明\n"
            "🛠️ **Admin Tool**｜Admin / helpers 專用管理工具"
        ),
        color=MENU_COLOR,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text="⬅️ Menu 返回吧枱主頁")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Admin Tool",
        description=(
            "**管理工具**\n\n"
            "📊 **Stats** — Community Bot 使用數據\n"
            "🔄 **Reload** — 直接重載所有 cogs\n"
            "🎭 **Role Tools** — Select Menu 角色管理工具\n"
            "🏓 **Ping** — Bot latency\n"
            "🧹 **VC Teardown** — 列出並刪除 Bot Temp VC\n\n"
            "⬅️ **Menu** — 返回吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed
