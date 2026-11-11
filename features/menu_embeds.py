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
    from features.language_preferences import language
    if language(user) == "tw":
        return discord.Embed(title="ℹ️ 使用說明", description=(
            "使用 `/menu` 開啟吧台；請選擇 **Con9sole-Bartender** 的指令。\n\n"
            "🍹 **喝一杯／請客喝一杯**：享用飲品或邀請朋友喝一杯。\n"
            "👥 **組隊／小隊語音**：找隊友、建立及管理臨時語音房。\n"
            "🔔 **我的組隊通知**：在吧台查看及管理已訂閱的遊戲通知。\n"
            "🎖️ **我的會員卡**：查看等級、經驗值、稱號與排名。\n"
            "📅 **今日小任務**：自由參加，完成後領取額外經驗值。\n"
            "🍾 **我的收藏／酒吧紀錄**：查看收藏與互動紀錄。\n"
            "🙌 **社群互動**：幫大家加油、匿名投稿，或探索公海話題。\n"
            "🌐 **資訊與設定 → 語境設定**：隨時切換香港或台灣用語。\n\n"
            "成功喝酒或加油可獲得互動經驗值，與文字訊息共用冷卻時間；查看資料不會獲得經驗值。"
        ), color=MENU_COLOR)
    embed = discord.Embed(
        title="ℹ️ 幫助",
        description=(
            "**Bartender 使用說明**\n\n🍸 `/menu` 請揀 **Con9sole-Bartender**，開啟吧枱；「更多玩法」分為我的紀錄、社群排行、社群互動、資訊與設定。\n\n"
            "👥 **搵人玩**｜發起組隊 / 招募隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **小隊 call 控制**｜改人數上限 / 刪除自己的小隊 call\n"
            "🔔 **我的組隊通知**｜喺吧枱查看及管理已訂閱嘅遊戲通知\n\n"
            "🎉 **打氣**｜送出隨機打氣內容\n"
            "🙌 **幫人打氣**｜揀一位成員，送一句打氣給對方\n"
            "🕯️ **無名告白**｜匿名投稿\n\n"
            "🍹 **飲一杯**｜抽一杯酒保特選飲品\n"
            "🥂 **請人飲**｜揀一位成員，請佢飲一杯\n"
            "📊 **酒吧紀錄**｜查看自己叫酒 / 賜酒 / 收到賜酒紀錄\n"
            "🍾 **我的收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n"
            "🏆 **酒吧排行榜**｜查看叫酒 / 賜酒 / 收酒 / 收藏榜\n"
            "📅 **今日小任務**｜查看每日吧枱任務\n\n"
            "🎖️ **我的會員卡**｜等級進度、酒吧收藏及等級總榜／本週排名\n"
            "🏅 **我的稱號**｜預覽選用已解鎖稱號，並同步已綁定嘅 Discord Role\n"
            "成功飲酒或打氣可獲互動 XP，與文字共用冷卻；查看資料唔加 XP。\n\n"
            "🌊 **探索公海**｜瀏覽遊戲以外的公開話題，或前往身份設定開放公海區\n"
            "🔗 **邀請朋友**｜取得社群邀請碼\n"
            "📸 **IG**｜查看官方 Instagram\n"
            "🧵 **Threads**｜查看官方 Threads\n\n"
            "ℹ️ **使用說明**｜查看這份使用說明\n"
            "🛠️ **管理工具**｜按 Admin／Mod／Helpers 職責提供可用工具"
        ),
        color=MENU_COLOR,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text="🍸 吧枱返回快捷入口")
    return embed


def build_admin_tool_embed(user: discord.abc.User) -> discord.Embed:
    from core.permissions import can_use_staff_tool
    entries = [
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
        + "\n\n⬅️ 返回上一頁 — 更多玩法",
        color=MENU_COLOR,
    )
    embed.set_footer(text="Admin 工具只限授權成員使用。")
    return embed


def build_section_embed(section: str) -> discord.Embed:
    title, description = {
        "records": ("🎖️ 我的紀錄", "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏內可查看里程碑同主題酒單。"),
        "rankings": ("🏆 社群排行", "等級、每週參與、邀請朋友同酒吧收藏排行榜。"),
        "social": ("🙌 社群互動", "送句打氣，或者去公海傾下遊戲以外嘅話題。"),
        "info": ("ℹ️ 資訊與設定", "揀選想睇嘅內容、邀請朋友，或者查看社群資訊同使用說明。"),
    }[section]
    return discord.Embed(title=title, description=description, color=MENU_COLOR)
