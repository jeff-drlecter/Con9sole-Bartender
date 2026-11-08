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
            "📊 **酒吧紀錄**｜查看自己叫酒 / 賜酒 / 收到賜酒紀錄\n"
            "🍾 **酒單收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n"
            "🏆 **酒吧排行榜**｜查看叫酒 / 賜酒 / 收酒 / 收藏榜\n"
            "📅 **今日任務**｜查看每日吧枱任務\n\n"
            "🎖️ **我的會員卡**｜等級進度、酒吧收藏及等級總榜／本週排名\n"
            "🏅 **管理稱號**｜預覽選用已解鎖稱號，並同步已綁定嘅 Discord Role\n"
            "成功飲酒或打氣可獲互動 XP，與文字共用冷卻；查看資料唔加 XP。\n\n"
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
    from core.permissions import can_use_staff_tool
    entries = [
        ("community_levels_admin", "🎖️ 等級管理 — 計分、角色及等級設定"),
        ("title_roles_admin", "🏅 稱號管理 — 綁定 Role 及全員同步"),
        ("bot_health", "🩺 系統狀態 — 查看計分循環及待查通知"),
        ("admin_stats", "📊 Stats — Bot 使用數據"),
        ("admin_reload", "🔄 Reload — 重載 Bot 模組"),
        ("admin_roles", "🎭 Role Tools — 角色查閱及授權範圍內操作"),
        ("admin_game_tools", "🎮 Game Tools — 遊戲專區設定"),
        ("admin_update_publisher", "📣 Update Publisher — 草擬及發佈公告"),
        ("admin_ping", "🏓 Ping — Bot 回應時間"),
        ("admin_vc_teardown", "🧹 VC Teardown — 管理 Bot 臨時語音房"),
    ]
    embed = discord.Embed(
        title="🛠️ 管理及協助工具",
        description="\n".join(text for key, text in entries if can_use_staff_tool(user, key))
        + "\n\n⬅️ Menu — 返回吧枱主頁",
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed
