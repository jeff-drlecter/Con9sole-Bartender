import pkgutil
import traceback
import discord
from discord import app_commands
from discord.ext import commands
import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)

def _is_admin(inter: discord.Interaction) -> bool:
    return bool(inter.user and inter.user.guild_permissions.administrator)


class Reload(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(config.GUILD_ID)
    @app_commands.check(_is_admin)  # 只保留 runtime check
    @app_commands.command(
        name="reload",
        description="重載所有 / 指定的 cogs（只有管理員可用）"
    )
    @app_commands.describe(cog="可選，指定某個 cog 名稱（例如：drink）")
    async def reload_cogs(self, interaction: discord.Interaction, cog: str | None = None):
        await interaction.response.defer(ephemeral=True)

        import cogs
        found = {name for _, name, _ in pkgutil.iter_modules(cogs.__path__)}
        if cog:
            if cog not in found:
                await interaction.followup.send(
                    f"找不到 cog：`{cog}`。可用：`{', '.join(sorted(n for n in found if not n.startswith('_')))}`",
                    ephemeral=True,
                )
                return
            targets = [cog]
        else:
            targets = sorted(n for n in found if not n.startswith('_'))

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

        # Resync guild commands
        try:
            synced = await self.bot.tree.sync(guild=TARGET_GUILD)
            print(f"🔄 Resynced {len(synced)} commands: {[c.name for c in synced]}")
        except Exception as e:
            print("Resync 失敗：", e)

        msg = []
        if ok:
            msg.append(f"✅ 已重載：`{', '.join(ok)}`")
        if fail:
            msg.append("❌ 失敗：\n" + "\n".join(f"- `{n}` → {err}" for n, err in fail))
        if not msg:
            msg.append("沒有可重載的 cogs。")
        await interaction.followup.send("\n".join(msg), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reload(bot))
