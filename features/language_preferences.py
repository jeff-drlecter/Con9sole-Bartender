"""Deterministic, role-backed wording preferences; never infer location."""
from __future__ import annotations

import discord

ROLE_NAMES = {"hk": "語境偏好｜香港", "tw": "語境偏好｜台灣"}
from features.onboarding_wording import LANGUAGE_TITLE
PROMPT_TITLE = LANGUAGE_TITLE


def language(member) -> str:
    names = {r.name for r in getattr(member, "roles", []) if not r.managed and r.permissions.value == 0}
    # Ambiguous dual-role selections fail back to the server default.
    return "tw" if ROLE_NAMES["tw"] in names and ROLE_NAMES["hk"] not in names else "hk"


def preference_roles(roles, channels=()):
    result = {}
    for code, name in ROLE_NAMES.items():
        found = [r for r in roles if r.name == name]
        if len(found) != 1 or found[0].managed or found[0].permissions.value:
            raise ValueError("語境角色缺少、重複或含有權限；請管理員先檢查。")
        if any(found[0] in channel.overwrites for channel in channels):
            raise ValueError("語境角色含有頻道權限覆寫；請管理員檢查，未派發角色。")
        result[code] = found[0]
    return result


# Only translate known Bot-owned menu copy, never names, submissions or public cards.
TW = {
    "吧枱": "吧台", "Con9sole 吧枱": "Con9sole 吧台", "飲杯嘢，定搵人開局？": "喝一杯，還是找人一起玩？",
    "飲一杯": "喝一杯", "請人飲": "請客喝一杯", "搵人玩": "找人一起玩",
    "幫人打氣": "幫別人加油", "打氣": "加油", "小隊 call 控制": "小隊語音管理",
    "小隊 call": "小隊語音", "自選頻道與身份": "自選頻道與身分組",
    "揀一類玩法繼續。我的紀錄、社群排行、社群互動、資訊與設定。\n小任務隨心參與，唔做都唔影響吧枱功能。":
        "選擇一類功能繼續：我的紀錄、社群排行、社群互動、資訊與設定。\n每日任務自由參加，不完成也能使用吧台功能。",
    "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏內可查看里程碑同主題酒單。":
        "查看會員卡、收藏進度、酒吧紀錄及已解鎖稱號。\n收藏中可以查看里程碑與主題酒單。",
    "等級總榜、本週參與同酒吧收藏，各有一份紀錄。": "查看等級總榜、本週參與及酒吧收藏排名。",
    "送句打氣，或者去公海傾下遊戲以外嘅話題。": "幫大家加油，或到公海聊聊遊戲以外的話題。",
    "揀選想睇嘅內容、邀請朋友，或者查看社群資訊同使用說明。": "選擇想看的內容、邀請朋友，或查看社群資訊與使用說明。",
}


def menu_text(text: str, code: str) -> str:
    if code != "tw":
        return text
    if text in TW:
        return TW[text]
    # Labels/titles with emoji prefixes only; no general substring replacement.
    for hk, tw in TW.items():
        if text.endswith(hk) and len(text) - len(hk) <= 4:
            return text[:-len(hk)] + tw
    return text


def localize_menu(member, embed=None, view=None):
    code = language(member)
    if embed is not None:
        embed = embed.copy()
        if embed.title:
            embed.title = menu_text(embed.title, code)
        if embed.description:
            embed.description = menu_text(embed.description, code)
    if view is not None:
        for child in view.children:
            if isinstance(child, discord.ui.Button) and child.label:
                child.label = menu_text(child.label, code)
    return embed, view


def serialize_prompts(onboarding):
    """discord.py edit_onboarding renumbers prompts and omits option IDs: preserve both."""
    return [{**p.to_dict(id=p.id), "id": str(p.id),
             "options": [{**o.to_dict(), "id": str(o.id), "role_ids": list(map(str, o.role_ids)), "channel_ids": list(map(str, o.channel_ids))} for o in p.options]}
            for p in onboarding.prompts]


NEWS_PROMPT_ID = "1426676369567387826"


def make_room_for_language(prompts):
    """Keep four pre-join questions; move only the known news preference post-join."""
    import copy
    result = copy.deepcopy(prompts)
    if sum(bool(p.get("in_onboarding")) for p in result) >= 4:
        news = next((p for p in result if p["id"] == NEWS_PROMPT_ID and p.get("in_onboarding")), None)
        if news is None or sum(bool(p.get("in_onboarding")) for p in result) != 4:
            raise ValueError("入服前問題已滿，未找到可移到入服後的原有新聞選項；未覆寫。")
        news["in_onboarding"] = False
    return result


class LanguageView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        for code, label in (("hk", "香港語境"), ("tw", "台灣語境")):
            button = discord.ui.Button(label=label, custom_id=f"language:{code}")
            async def callback(interaction, selected=code):
                await self.choose(interaction, selected)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("請開啟自己的 /menu。", ephemeral=True)
        return False

    async def choose(self, interaction, code):
        if interaction.user.id != self.owner_id or interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.get_cog("LanguagePreferences")
        async with cog.lock:
            try:
                import config
                if interaction.guild_id != config.GUILD_ID:
                    raise ValueError("只限指定社群使用。")
                roles = preference_roles(await interaction.guild.fetch_roles(), await interaction.guild.fetch_channels())
                member = await interaction.guild.fetch_member(interaction.user.id)
                me = await interaction.guild.fetch_member(interaction.client.user.id)
                if any(r >= me.top_role for r in roles.values()):
                    raise ValueError("Bot 無法管理語境角色，請管理員檢查角色排序。")
                # Per-role endpoints preserve concurrent unrelated role assignments.
                await member.add_roles(roles[code], reason="Member wording preference")
                await member.remove_roles(roles["hk" if code == "tw" else "tw"], reason="Member wording preference")
                fresh = await interaction.guild.fetch_member(member.id)
                selected = {r.id for r in fresh.roles} & {r.id for r in roles.values()}
                if selected != {roles[code].id}:
                    raise ValueError("未能確認設定，請重新開啟語境選單再試。")
                from features.menu_embeds import build_quick_bar_embed
                from features.menu_views import QuickBarView
                embed, view = localize_menu(fresh, build_quick_bar_embed(fresh), QuickBarView(interaction.client.get_cog("Menu")))
                await interaction.followup.send("已切換香港語境。" if code == "hk" else "已切換為台灣用語。", embed=embed, view=view, ephemeral=True)
            except (ValueError, discord.HTTPException) as exc:
                await interaction.followup.send(f"設定未完成：{exc}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
