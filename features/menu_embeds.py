from __future__ import annotations

import discord

import config
from features.menu_helpers import MENU_COLOR, apply_bartender_thumbnail

COMMUNITY_NAME = getattr(config, "COMMUNITY_NAME", "Con9sole Community")


def build_quick_bar_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Con9sole Bartender",
        description=(
            "**「歡迎光臨，要點什麼？」**\n\n"
            "👥 **組隊**｜召集隊友\n"
            "🎧 **小隊 call**｜建立臨時語音房\n"
            "🎛️ **控制**｜管理目前小隊 call\n\n"
            "🎉 **打氣**｜為大家補充能量\n"
            "🙌 **幫人打氣**｜送一句打氣給其他成員\n"
            "🍹 **調酒**｜酒保特選\n"
            "🥂 **賜酒**｜賜一杯酒給其他成員\n\n"
            "⬅️ **Menu**｜進入吧枱主頁"
        ),
        color=MENU_COLOR,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text=f"Con9sole Bartender｜{user.display_name}，今晚由我為你服務。")
    return embed


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    return build_quick_bar_embed(user)


def build_home_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍸 Bartender Home",
        description=(
            f"**{COMMUNITY_NAME} 吧枱主頁**\n\n"
            "👥 **組隊** — 召集隊友\n"
            "🎧 **小隊 call** — 建立臨時語音房\n"
            "🎛️ **小隊 call 控制** — 管理目前身處的小隊 call\n\n"
            "🎉 **打氣** — 為大家補充能量\n"
            "🙌 **幫人打氣** — 送一句打氣給其他成員\n"
            "🕯️ **無名告白** — 匿名投稿\n\n"
            "🍹 **調酒** — 酒保特選\n"
            "🥂 **賜酒** — 賜一杯酒給其他成員\n"
            "📊 **酒保紀錄** — 查看自己的酒保互動\n"
            "🍾 **酒單收藏** — 查看酒款收藏進度\n\n"
            "🔗 **生成邀請碼** — 7 日 / 10 次公開邀請連結\n"
            "📸 **IG Page** — 官方 Instagram\n"
            "🧵 **Threads Page** — 官方 Threads\n\n"
            "ℹ️ **幫助** — 使用說明\n"
            "🛠️ **Admin Tool** — 管理工具"
        ),
        color=MENU_COLOR,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜選好服務後，直接撳下面按鈕。")
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
            "🍾 **酒單收藏**｜查看已解鎖酒款、稀有度進度與最近解鎖\n\n"
            "🔗 **生成邀請碼**｜7 日有效、最多 10 次使用，每人 10 分鐘一次\n"
            "📸 **IG Page**｜查看官方 Instagram\n"
            "🧵 **Threads Page**｜查看官方 Threads\n\n"
            "ℹ️ **幫助**｜查看呢份使用說明\n"
            "🛠️ **Admin Tool**｜Admin / helpers 專用管理工具"
        ),
        color=MENU_COLOR,
    )
    apply_bartender_thumbnail(embed)
    embed.set_footer(text="Con9sole Bartender｜⬅️ Menu 返回吧枱主頁")
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
    embed.set_footer(text="Con9sole Bartender｜Admin 工具只限授權成員使用。")
    return embed
