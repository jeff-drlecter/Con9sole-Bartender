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
        description="找隊友、開語音房或查看公會卡。組隊通知、語言及頻道偏好可在「偏好與設定」調整。",
        color=MENU_COLOR,
    )


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    from features.language_preferences import language
    if language(user) == "hk":
        description = (
            "🎮 **搵隊友／約局**　即玩、預約或睇現有約局。開房同房控用「開房／房控」。\n"
            "🪪 **公會卡**　揀公會睇聯絡人；Helper 可以建立或修改有效卡。\n"
            "🎖️ **我的會員卡**　睇等級、酒吧紀錄、收藏同稱號。\n"
            "🙌 **社群互動**　邀請朋友、打氣、匿名投稿、公海同官方社交連結。\n"
            "⚙️ **偏好同設定**　入「我的組隊通知」管理本局提醒同遊戲訂閱，亦可改語言、遊戲身份同情報偏好。\n"
            "🛟 **搵 Helper**　取得你可以留言嘅求助頻道連結。"
        )
    else:
        description = (
            "🎮 **找隊友／約局**　現在玩、預約或瀏覽現有約局。「開房／房控」可建立或管理語音房。\n"
            "🪪 **公會卡**　選擇公會查看聯絡人；Helper 可以建立或修改有效卡。\n"
            "🎖️ **我的會員卡**　查看等級、酒吧紀錄、收藏與稱號。\n"
            "🙌 **社群互動**　邀請朋友、加油、匿名投稿、公開討論區與官方社群連結。\n"
            "⚙️ **偏好與設定**　在「我的組隊通知」管理本局提醒與遊戲訂閱，亦可調整語言、遊戲身分組與情報偏好。\n"
            "🛟 **聯絡 Helper**　取得可留言的求助頻道連結。"
        )
    return discord.Embed(title="ℹ️ 使用說明", description=description, color=MENU_COLOR)


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    from core.permissions import can_use_staff_tool
    entries = [
        ("community_outcomes", "📈 社群成效 — 約局開局、觀測參與及資料缺漏"),
        ("squad_test", "🧪 組隊卡測試 — 只在功能測試區執行"),
        ("stream_admin", "📺 直播名單 — 直播主、檢查頻率及通知設定"),
        ("permission_audit", "🔍 權限審核 — 查看權限差異及審核結果"),
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
        + "\n\n⬅️ 返回主選單",
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed


def build_section_embed(section: str) -> discord.Embed:
    title, description = {
        "records": ("🎖️ 我的紀錄", "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏內可查看里程碑同主題酒單。"),
        "rankings": ("🏆 排行榜", "等級、每週參與、邀請朋友同酒吧收藏排行榜。"),
        "social": ("🙌 社群互動", "邀請朋友、打氣、匿名投稿，或瀏覽公海與官方社群。"),
        "info": ("⚙️ 偏好同設定", "語言、遊戲身份與頻道、組隊通知及新聞偏好。"),
    }[section]
    return discord.Embed(title=title, description=description, color=MENU_COLOR)
