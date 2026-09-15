from __future__ import annotations

import inspect

import discord

from core.safe_send import send_or_followup
from features.menu_helpers import MENU_COLOR, can_use_admin
from features.menu_stats import build_admin_stats_embed, record_usage_sync
from features.menu_views import AdminToolView
from features.role_tools import RoleToolsView, build_role_tools_embed


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


async def admin_stats_from_button(menu_cog: object, interaction: discord.Interaction) -> None:
    await safe_defer(interaction, ephemeral=True)
    record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)
    embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=7, title_scope="本週")
    await send_or_followup(interaction, embed=embed, view=AdminToolView(menu_cog), ephemeral=True)


async def admin_stats_command(interaction: discord.Interaction, *, scope_value: str) -> None:
    if not can_use_admin(interaction.user):
        await send_or_followup(
            interaction,
            content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
            ephemeral=True,
        )
        return

    record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)

    if scope_value == "today":
        days: int | None = 1
        title_scope = "今日"
    elif scope_value == "week":
        days = 7
        title_scope = "本週"
    else:
        days = None
        title_scope = "全部"

    embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=days, title_scope=title_scope)
    await send_or_followup(interaction, embed=embed, ephemeral=False)


async def admin_reload_from_button(interaction: discord.Interaction) -> None:
    await safe_defer(interaction, ephemeral=True)
    record_usage_sync("admin_reload", interaction.user.id, interaction.guild_id)

    reload_cog = interaction.client.get_cog("Reload")
    if reload_cog is None or not hasattr(reload_cog, "_reload_many"):
        await send_or_followup(
            interaction,
            content="❌ Reload 模組未載入，無法由 Bot 內自行修復。請重新啟動 Bot。",
            ephemeral=True,
        )
        return

    try:
        result = reload_cog._reload_many(None)  # type: ignore[attr-defined]
        if inspect.isawaitable(result):
            ok_list, fail_list = await result
        else:
            ok_list, fail_list = result

        parts: list[str] = []
        if ok_list:
            parts.append("✅ 已重載： " + ", ".join(ok_list))
        if fail_list:
            parts.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

        await send_or_followup(
            interaction,
            content="\n".join(parts) if parts else "⚠️ 無可重載的 cogs。",
            ephemeral=True,
        )
    except Exception as exc:
        await send_or_followup(
            interaction,
            content=f"❌ Reload button 執行失敗：`{type(exc).__name__}`：{exc}",
            ephemeral=True,
        )


async def admin_role_tools_from_button(menu_cog: object, interaction: discord.Interaction) -> None:
    record_usage_sync("admin_role", interaction.user.id, interaction.guild_id)
    await send_or_followup(
        interaction,
        embed=build_role_tools_embed(interaction.user),
        view=RoleToolsView(menu_cog),
        ephemeral=True,
    )


async def admin_game_tools_from_button(menu_cog: object, interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await send_or_followup(
            interaction,
            content="❌ Game Tools 與 `/add_new_game`、`/add_game_version` 一樣，只限 Administrator 使用。",
            ephemeral=True,
        )
        return

    record_usage_sync("admin_game_tools", interaction.user.id, interaction.guild_id)
    embed = discord.Embed(
        title="🎮 Game Tools",
        description=(
            "**遊戲專區管理**\n\n"
            "🆕 **建立全新遊戲**\n"
            "使用 `/add_new_game`，建立新的 Category、角色及模板頻道。\n\n"
            "🔄 **新增遊戲版本**\n"
            "使用 `/add_game_version`，選擇現有 Forum 及來源角色後，只需填寫新版本名稱。\n"
            "Bot 會自動建立 `<新版本>-專區` 及 `<新版本> Player`，並把新 Forum 放在來源 Forum 之前。\n\n"
            "舊 `/role_channel_new` 已停用，避免與現行遊戲建立流程重疊。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Game Tools｜只限 Administrator 使用。")
    await send_or_followup(
        interaction,
        embed=embed,
        view=AdminToolView(menu_cog),
        ephemeral=True,
    )


async def admin_ping_from_button(interaction: discord.Interaction) -> None:
    await safe_defer(interaction, ephemeral=True)
    record_usage_sync("admin_ping", interaction.user.id, interaction.guild_id)
    latency_ms = round(interaction.client.latency * 1000)
    await send_or_followup(interaction, content=f"🏓 Pong! `{latency_ms} ms`", ephemeral=True)


async def admin_vc_teardown_from_button(interaction: discord.Interaction) -> None:
    record_usage_sync("admin_vc_teardown", interaction.user.id, interaction.guild_id)
    tempvc_cog = interaction.client.get_cog("TempVC")
    if tempvc_cog and hasattr(tempvc_cog, "teardown_temp_vc_from_menu"):
        try:
            result = tempvc_cog.teardown_temp_vc_from_menu(interaction)  # type: ignore[attr-defined]
            if inspect.isawaitable(result):
                await result
            return
        except discord.InteractionResponded:
            return
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ VC Teardown 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )
            return

    await send_or_followup(
        interaction,
        content="🧹 **VC Teardown 指令入口**\n\n請使用 slash command：`/vc_teardown`。",
        ephemeral=True,
    )
