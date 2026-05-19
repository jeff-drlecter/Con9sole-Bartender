from __future__ import annotations

import inspect

import discord

from core.safe_send import send_or_followup
from features.menu_stats import record_usage_sync


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


async def admin_reload_from_button(interaction: discord.Interaction) -> None:
    await safe_defer(interaction, ephemeral=True)
    record_usage_sync("admin_reload", interaction.user.id, interaction.guild_id)

    reload_cog = interaction.client.get_cog("Reload")
    if reload_cog is None or not hasattr(reload_cog, "_reload_one"):
        await send_or_followup(
            interaction,
            content="❌ Reload cog 未載入，請先用 `/reload reload` 或重啟 Bot。",
            ephemeral=True,
        )
        return

    try:
        from cogs.reload import _list_cogs_package  # type: ignore

        ok_list: list[str] = []
        fail_list: list[str] = []
        for name in _list_cogs_package():
            ext = f"cogs.{name}"
            try:
                result = reload_cog._reload_one(ext)  # type: ignore[attr-defined]
                if inspect.isawaitable(result):
                    ok, fail = await result
                else:
                    ok, fail = result
            except Exception as exc:
                ok = False
                fail = f"`{type(exc).__name__}`: {exc}"
            if ok:
                ok_list.append(name)
            else:
                fail_list.append(f"{name} -> {fail}")

        msg: list[str] = []
        if ok_list:
            msg.append("✅ 已重載： " + ", ".join(ok_list))
        if fail_list:
            msg.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

        await send_or_followup(
            interaction,
            content="\n".join(msg) if msg else "⚠️ 無可重載的 cogs。",
            ephemeral=True,
        )
    except Exception as exc:
        await send_or_followup(
            interaction,
            content=f"❌ Reload button 執行失敗：`{type(exc).__name__}`：{exc}",
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
