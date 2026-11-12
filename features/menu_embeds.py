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
    return discord.Embed(title="ℹ️ 使用說明", description=(
        "使用 `/menu` 開啟酒吧選單，請選擇 **Con9sole-Bartender** 的指令。\n\n"
        "🍹 **喝一杯／請喝一杯**：享用飲品，或請其他成員喝一杯。\n"
        "👥 **找隊友**：發起組隊或招募隊友。\n"
        "🎧 **小隊語音／語音房設定**：建立及管理臨時語音房。\n"
        "🔔 **我的組隊通知**：查看或取消已訂閱的遊戲通知。\n"
        "🎖️ **我的會員卡／我的稱號**：查看等級、經驗值及稱號。\n"
        "📅 **今日小任務**：自由參與，完成後領取額外經驗值。\n"
        "🍾 **我的收藏／酒吧紀錄**：查看收藏及互動紀錄。\n"
        "🏆 **社群排行**：查看等級、每週參與、邀請及酒吧排行榜。\n"
        "🙌 **社群互動**：為成員打氣、匿名投稿，或探索綜合聊天區。\n"
        "🔗 **邀請朋友**：取得個人邀請連結。\n"
        "🌐 **資訊與設定 → 用語偏好**：選擇通用繁體中文、香港或台灣用語。\n\n"
        "成功喝酒或打氣可獲得互動經驗值，與文字訊息共用冷卻時間；查看資料不會增加經驗值。"
    ), color=MENU_COLOR)


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    from core.permissions import can_use_staff_tool
    entries = [
        ("stream_admin", "📺 直播名單 — 直播主、檢查頻率及通知設定"),
        ("permission_audit", "🔍 權限審核 — 查看權限差異及審核結果"),
        ("community_levels_admin", "🎖️ 等級管理 — 計分、角色及等級設定"),
        ("title_roles_admin", "🏅 稱號管理 — 綁定 Role 及全員同步"),
        ("bot_health", "🩺 系統狀態 — 查看計分循環及待查通知"),
        ("admin_stats", "📊 使用統計 — Bot 使用數據"),
        ("admin_reload", "🔄 重載模組 — 重載 Bot 模組"),
        ("admin_roles", "🎭 身分組工具 — 角色查閱及授權範圍內操作"),
        ("admin_game_tools", "🎮 遊戲專區管理 — 遊戲專區設定"),
        ("admin_update_publisher", "📣 公告發佈 — 草擬及發佈公告"),
        ("admin_ping", "🏓 連線延遲 — Bot 回應時間"),
        ("admin_vc_teardown", "🧹 清理語音房 — 管理 Bot 臨時語音房"),
    ]
    embed = discord.Embed(
        title="🛠️ 管理及協助工具",
        description="\n".join(text for key, text in entries if can_use_staff_tool(user, key))
        + "\n\n⬅️ 返回上一頁 — 更多玩法",
        color=MENU_COLOR,
    )
    embed.set_footer(text="管理工具僅限已授權成員使用。")
    return embed


def build_section_embed(section: str) -> discord.Embed:
    title, description = {
        "records": ("🎖️ 我的紀錄", "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏內可查看里程碑同主題酒單。"),
        "rankings": ("🏆 社群排行", "等級、每週參與、邀請朋友與酒吧收藏排行榜。"),
        "social": ("🙌 社群互動", "送句打氣，或者去公海傾下遊戲以外嘅話題。"),
        "info": ("ℹ️ 資訊與設定", "揀選想睇嘅內容、邀請朋友，或者查看社群資訊同使用說明。"),
    }[section]
    return discord.Embed(title=title, description=description, color=MENU_COLOR)
