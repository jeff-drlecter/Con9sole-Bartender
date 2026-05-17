# Replace ONLY the reload_button() inside cogs/menu.py -> class AdminToolView
# This calls your existing cogs.reload.Reload._reload_one() safely.
# It keeps the previous protections against NoneType.to_dict / NoneType.is_finished.

    @discord.ui.button(
        label="Reload",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:admin:reload",
        row=0,
    )
    async def reload_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await safe_defer(interaction, ephemeral=True)

        if not await self._require_admin(interaction):
            return

        await self._record(interaction, "admin_reload")

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
