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
    return discord.Embed(
        title="🍸 Con9sole 吧枱",
        description="飲杯嘢，定搵人開局？",
        color=MENU_COLOR,
    )


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_home_menu_embed(user: discord.abc.User, *, include_thumbnail: bool = True) -> discord.Embed:
    return discord.Embed(
        title="🍸 更多玩法",
        description="睇收藏、送句打氣，或者探索社群。\n小任務隨心參與，唔做都唔影響吧枱功能。",
        color=MENU_COLOR,
    )


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description=(
            "**Bartender 使用說明**\n\n"
            "👥 **組隊**｜發起組隊 / 招募隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **小隊 call 控制**｜改人數上限 / 刪除自己的小隊 call\n\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🙌 **幫人打氣**｜揀一位成員，送一句打氣給對方\n"
            "🕯️ **無名告白**｜匿名投稿\n\n"
            "🍹 **調酒**｜抽一杯酒保特選飲品\n"
            "🥂 **賜酒**｜揀一位成員，請佢飲一杯\n"
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
    embed.set_footer(text="🍸 吧枱返回快捷入口")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Admin Tool",
        description=(
            "**管理工具**\n\n"
            "📊 **Stats** — Community Bot 使用數據\n"
            "🔄 **Reload** — 重載 Bot cogs\n"
            "🎭 **Role Tools** — 成員角色管理\n"
            "🎮 **Game Tools** — `/add_new_game` / `/add_game_version` 使用說明\n"
            "📣 **Update Publisher** — 草擬、預覽及手動發佈更新公告\n"
            "🏓 **Ping** — Bot latency\n"
            "🧹 **VC Teardown** — 列出並刪除 Bot 建立的臨時語音房\n\n"
            "⬅️ **Menu** — 返回吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed
