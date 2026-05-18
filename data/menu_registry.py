from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ButtonStyleName = Literal["primary", "secondary", "success", "danger", "link"]
MenuLayer = Literal["quick", "home", "admin"]


@dataclass(frozen=True)
class MenuItem:
    id: str
    label: str
    emoji: str
    style: ButtonStyleName
    layer: MenuLayer
    row: int
    cog: str | None = None
    method: str = "menu_entry"
    admin_only: bool = False
    url: str | None = None
    description: str = ""


# Button colour rule:
# - secondary: navigation / previous page only
# - primary: normal functional action
# - success: positive / fun / social action
# - danger: admin-restricted or destructive/high-impact action
# - link: external URL, added dynamically in menu.py


# Layer 1：公開 / 快捷吧枱
# Quick Bar 會出喺 drink / cheers / main menu 下方。
# 原則：第一格進入主頁，其後係主要即用功能。
QUICK_MENU_ITEMS: list[MenuItem] = [
    MenuItem(
        id="home_menu",
        label="Menu",
        emoji="⬅️",
        style="secondary",
        layer="quick",
        row=0,
        cog="Menu",
        method="open_home_menu_from_button",
        description="進入吧枱主頁",
    ),
    MenuItem(
        id="team",
        label="組隊",
        emoji="👥",
        style="primary",
        layer="quick",
        row=0,
        cog="Teams",
        method="menu_entry",
        description="召集隊友",
    ),
    MenuItem(
        id="tempvc",
        label="小隊 call",
        emoji="🎧",
        style="primary",
        layer="quick",
        row=0,
        cog="TempVC",
        method="menu_entry",
        description="建立臨時語音房",
    ),
    MenuItem(
        id="tempvc_control",
        label="控制",
        emoji="🎛️",
        style="primary",
        layer="quick",
        row=1,
        cog="TempVC",
        method="open_control_panel_from_menu",
        description="管理目前身處的小隊 call",
    ),
    MenuItem(
        id="cheers",
        label="",
        emoji="🎉",
        style="success",
        layer="quick",
        row=1,
        cog="Cheers",
        method="menu_entry",
        description="打氣時間",
    ),
    MenuItem(
        id="drink",
        label="",
        emoji="🍹",
        style="success",
        layer="quick",
        row=1,
        cog="Drink",
        method="menu_entry",
        description="調酒",
    ),
]


# Layer 2：私人主頁 / 功能總覽
# Social link buttons are added dynamically in menu.py.
# Desired Home layout:
# row 0: core community tools
# row 1: cheers + drink quick actions
# row 2: drink social/stats + confession
# row 3: invite + IG Page + Threads Page
# row 4: help + admin
HOME_MENU_ITEMS: list[MenuItem] = [
    MenuItem(
        id="team",
        label="組隊",
        emoji="👥",
        style="primary",
        layer="home",
        row=0,
        cog="Teams",
        method="menu_entry",
        description="召集隊友",
    ),
    MenuItem(
        id="tempvc",
        label="小隊 call",
        emoji="🎧",
        style="primary",
        layer="home",
        row=0,
        cog="TempVC",
        method="menu_entry",
        description="建立臨時語音房",
    ),
    MenuItem(
        id="tempvc_control",
        label="小隊 call 控制",
        emoji="🎛️",
        style="primary",
        layer="home",
        row=0,
        cog="TempVC",
        method="open_control_panel_from_menu",
        description="管理目前身處的小隊 call",
    ),
    MenuItem(
        id="cheers",
        label="打氣",
        emoji="🎉",
        style="success",
        layer="home",
        row=1,
        cog="Cheers",
        method="menu_entry",
        description="送出一句打氣說話",
    ),
    MenuItem(
        id="cheers_target",
        label="幫人打氣",
        emoji="🙌",
        style="success",
        layer="home",
        row=1,
        cog="Cheers",
        method="cheer_for_member_entry",
        description="送一句打氣給其他成員",
    ),
    MenuItem(
        id="confession",
        label="無名告白",
        emoji="🕯️",
        style="success",
        layer="home",
        row=1,
        cog="Confession",
        method="menu_entry",
        description="匿名投稿",
    ),    
    MenuItem(
        id="drink",
        label="調酒",
        emoji="🍹",
        style="success",
        layer="home",
        row=2,
        cog="Drink",
        method="menu_entry",
        description="酒保特選飲品",
    ),
    MenuItem(
        id="drink_gift",
        label="賜酒",
        emoji="🥂",
        style="success",
        layer="home",
        row=2,
        cog="Drink",
        method="gift_drink_entry",
        description="賜一杯酒給其他成員",
    ),
    MenuItem(
        id="drink_stats",
        label="酒保紀錄",
        emoji="📊",
        style="primary",
        layer="home",
        row=2,
        cog="Drink",
        method="stats_entry",
        description="查看自己的酒保紀錄",
    ),

    MenuItem(
        id="invite",
        label="生成邀請碼",
        emoji="🔗",
        style="primary",
        layer="home",
        row=3,
        cog="Menu",
        method="create_invite_link_from_button",
        description="7 日 / 10 次公開邀請連結",
    ),
    MenuItem(
        id="help",
        label="幫助",
        emoji="ℹ️",
        style="primary",
        layer="home",
        row=4,
        cog="Menu",
        method="open_help_from_button",
        description="使用說明",
    ),
    MenuItem(
        id="admin_tool",
        label="Admin Tool",
        emoji="🛠️",
        style="danger",
        layer="home",
        row=4,
        cog="Menu",
        method="open_admin_tool_from_button",
        admin_only=True,
        description="管理工具",
    ),
]


# Admin Tool：精簡管理工具
# 原則：第一格係返回上一層 / 主頁，其後先係管理操作。
ADMIN_MENU_ITEMS: list[MenuItem] = [
    MenuItem(
        id="home_menu",
        label="Menu",
        emoji="⬅️",
        style="secondary",
        layer="admin",
        row=0,
        cog="Menu",
        method="open_home_menu_from_button",
        admin_only=True,
        description="返回吧枱主頁",
    ),
    MenuItem(
        id="admin_stats",
        label="Stats",
        emoji="📊",
        style="primary",
        layer="admin",
        row=0,
        cog="Menu",
        method="admin_stats_from_button",
        admin_only=True,
        description="Community Bot 使用數據",
    ),
    MenuItem(
        id="admin_reload",
        label="Reload",
        emoji="🔄",
        style="primary",
        layer="admin",
        row=0,
        cog="Menu",
        method="admin_reload_from_button",
        admin_only=True,
        description="重載所有 cogs",
    ),
    MenuItem(
        id="admin_role",
        label="Role Tools",
        emoji="🎭",
        style="primary",
        layer="admin",
        row=1,
        cog="Menu",
        method="admin_role_tools_from_button",
        admin_only=True,
        description="角色管理入口",
    ),
    MenuItem(
        id="admin_ping",
        label="Ping",
        emoji="🏓",
        style="primary",
        layer="admin",
        row=1,
        cog="Menu",
        method="admin_ping_from_button",
        admin_only=True,
        description="Bot latency",
    ),
    MenuItem(
        id="admin_vc_teardown",
        label="VC Teardown",
        emoji="🧹",
        style="danger",
        layer="admin",
        row=1,
        cog="Menu",
        method="admin_vc_teardown_from_button",
        admin_only=True,
        description="列出並刪除 Bot Temp VC",
    ),
]


MENU_ITEMS_BY_LAYER: dict[MenuLayer, list[MenuItem]] = {
    "quick": QUICK_MENU_ITEMS,
    "home": HOME_MENU_ITEMS,
    "admin": ADMIN_MENU_ITEMS,
}


def get_menu_items(layer: MenuLayer) -> list[MenuItem]:
    return list(MENU_ITEMS_BY_LAYER[layer])
