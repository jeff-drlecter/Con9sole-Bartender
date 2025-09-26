import pkgutil
import time
import traceback
import importlib
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)


def _is_admin(inter: discord.Interaction) -> bool:
    # 允許 Admin；另外容許 Bot Owner 後門（避免鎖死）
    if inter.user and getattr(inter.user, "guild_permissions", None):
        if inter.user.guild_permissions.administrator:
            return True
    app = inter.client  # commands.Bot
    try:
        return app.is_owner(inter.user)  # type: ignore[attr-defined]
    except Exception:
        return False


class Reload(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Autocomplete ----------
    async def _cog_autocomplete(
        self, inter: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        import cogs
        found = sorted({name for _, name, _ in pkgutil.iter_modules(cogs.__path__) if not name.startswith("_")})
        # 另外支援 "utils"（非 extension，但常用）
        choices = [*found, "utils"]
        return [app_commands.Choice(name=n, value=n) for n in choices if current.lower() in n.lower()][:25]

    @app_commands.guilds(config.GUILD_ID)
    @app_commands.check(_is_admin)  # 只保留 runtime check
    @app_commands.command(name="reload", description="重載所有 / 指定的 cogs（只有管理員可用）")
    @app_commands.describe(
        cog="可選，指定某個 cog 名稱（例如：drink / message_audit / utils）",
        global_sync="是否把斜線指令同步到所有伺服器（預設只同步本伺服器）",
        hard_reload="強制重載 utils 並重載所有 cogs（當 utils 變更時建議使用）",
    )
    @app_commands.autocomplete(cog=_cog_autocomplete)
    async def reload_cogs(
        self,
        interaction: discord.Interaction,
        cog: str | None = None,
        global_sync: bool = False,
        hard_reload: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        t0 = time.perf_counter()

        # Handle utils 專案模組（非 extension）
        if cog == "utils" or hard_reload:
            try:
                import utils  # type: ignore
                importlib.reload(utils)
            except Exception:
                traceback.print_exc()
                await interaction.followup.send("`utils` 重新載入失敗（請查 Console）", ephemeral=True)
                # 繼續做其餘 reload

        import cogs
        found = {name for _, name, _ in pkgutil.iter_modules(cogs.__path__)}

        if cog and cog != "utils":
            if cog not in found:
                await interaction.followup.send(
                    f"找不到 cog：`{cog}`。可用：`{', '.join(sorted(n for n in found if not n.startswith('_')))}`",
                    ephemeral=True,
                )
                return
            targets = [cog]
        else:
            targets = sorted(n for n in found if not n.startswith("_"))

        # 如果選擇 hard_reload，當 utils 變更後，最好把所有 cogs 都 reload
        if hard_reload and cog and cog != "utils":
            # 擴充為全部重載
            targets = sorted(n for n in found if not n.startswith("_"))

        ok, fail = [], []
        for name in targets:
            mod = f"cogs.{name}"
            try:
                try:
                    await self.bot.unload_extension(mod)
                except commands.ExtensionNotLoaded:
                    pass
                await self.bot.load_extension(mod)
                ok.append(name)
                print(f"🔁 Reloaded {mod}")
            except Exception as e:
                fail.append((name, repr(e)))
                print(f"❌ Reload {mod} 失敗：{e}")
                traceback.print_exc()

        # Resync commands
        try:
            if global_sync:
                synced = await self.bot.tree.sync()  # 全域
            else:
                synced = await self.bot.tree.sync(guild=TARGET_GUILD)  # 只此 guild
            print(f"🔄 Resynced {len(synced)} commands: {[c.name for c in synced]}")
        except Exception as e:
            print("Resync 失敗：", e)

        dt = (time.perf_counter() - t0) * 1000
        msg = []
        if ok:
            msg.append(f"✅ 已重載：`{', '.join(ok)}`")
        if fail:
            msg.append("❌ 失敗：\n" + "\n".join(f"- `{n}` → {err}" for n, err in fail))
        if not msg:
            msg.append("沒有可重載的 cogs。")
        msg.append(f"⏱️ 用時：{dt:.0f} ms  | 同步範圍：{'Global' if global_sync else 'Guild-only'}")

        await interaction.followup.send("\n".join(msg), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reload(bot))
