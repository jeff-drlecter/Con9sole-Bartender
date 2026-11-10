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
        description="揀一類玩法繼續。我的紀錄、社群排行、社群互動、資訊與設定。\n小任務隨心參與，唔做都唔影響吧枱功能。",
        color=MENU_COLOR,
    )


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    from features.language_preferences import wording
    intro = wording(user, "用 `/menu` 開啟吧枱。", "使用 `/menu` 開啟吧台。")
    play = wording(user,
        "🍹 **飲一杯／請人飲**：享用飲品，或者請朋友飲一杯。\n👥 **搵人玩／小隊 call**：招募隊友、建立及管理臨時語音房。",
        "🍹 **喝一杯／請客喝一杯**：享用飲品或邀請朋友喝一杯。\n👥 **找人一起玩／小隊語音**：招募隊友、建立及管理臨時語音房。")
    social = wording(user, "🙌 **社群互動**：幫人打氣、匿名投稿，或者去公海傾下其他話題。",
                     "🙌 **社群互動**：幫別人加油、匿名投稿，或到公海聊聊其他話題。")
    rewards = wording(user, "成功飲酒或打氣可獲互動 XP，與文字共用冷卻；查看資料唔加 XP。",
                      "成功喝酒或加油可獲得互動 XP，與文字訊息共用冷卻時間；查看資料不會增加 XP。")
    return discord.Embed(title="ℹ️ 使用說明", description=(intro + "\n\n" + play + "\n"
        "🎖️ **我的會員卡／我的稱號**：查看等級、經驗值與排名，管理已解鎖稱號。\n"
        "🍾 **我的收藏／酒吧紀錄**：查看收藏、里程碑、主題酒單與互動紀錄。\n"
        "🏆 **社群排行**：查看等級總榜、本週參與及酒吧收藏排名。\n"
        "📅 **今日小任務**：自由參加，完成後領取額外 XP。\n" + social + "\n"
        "🌐 **資訊與設定**：選擇頻道內容、取得邀請連結及查看社群資訊。\n"
        "🛠️ **管理工具**：按 Admin／Mod／Helpers 職責顯示可用工具。\n\n"
        "🌐 **資訊與設定 → 語境設定**：隨時切換香港／台灣用語。\n\n" + rewards), color=MENU_COLOR)


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    from core.permissions import can_use_staff_tool
    entries = [
        ("community_levels_admin", "🎖️ 等級管理 — 計分、角色及等級設定"),
        ("title_roles_admin", "🏅 稱號管理 — 綁定 Role 及全員同步"),
        ("bot_health", "🩺 系統狀態 — 查看計分循環及待查通知"),
        ("admin_stats", "📊 使用統計 — Bot 使用數據"),
        ("admin_reload", "🔄 重新載入 — Bot 模組"),
        ("admin_roles", "🎭 角色工具 — 查閱及授權範圍內操作"),
        ("admin_game_tools", "🎮 遊戲工具 — 遊戲專區設定"),
        ("admin_update_publisher", "📣 公告發佈 — 草擬及發佈公告"),
        ("admin_ping", "🏓 延遲測試 — Bot 回應時間"),
        ("admin_vc_teardown", "🧹 語音房清理 — 管理 Bot 臨時語音房"),
    ]
    embed = discord.Embed(
        title="🛠️ 管理及協助工具",
        description="\n".join(text for key, text in entries if can_use_staff_tool(user, key))
        + "\n\n⬅️ 返回上一頁 — 更多玩法",
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed


def build_section_embed(section: str) -> discord.Embed:
    title, description = {
        "records": ("🎖️ 我的紀錄", "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏內可查看里程碑同主題酒單。"),
        "rankings": ("🏆 社群排行", "等級總榜、本週參與同酒吧收藏，各有一份紀錄。"),
        "social": ("🙌 社群互動", "送句打氣，或者去公海傾下遊戲以外嘅話題。"),
        "info": ("ℹ️ 資訊與設定", "揀選想睇嘅內容、邀請朋友，或者查看社群資訊同使用說明。"),
    }[section]
    return discord.Embed(title=title, description=description, color=MENU_COLOR)
