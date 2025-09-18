import asyncio
import pkgutil
import traceback
import discord
from discord.ext import commands
import config
import os

intents = discord.Intents(
    guilds=True, members=True, voice_states=True,
    messages=True, message_content=True
)
bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=config.GUILD_ID)


@bot.event
async def on_ready():
    print("🚀 Bot 啟動，開始同步指令（Guild-only）…")
    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🏠 Guild({config.GUILD_ID}) sync 完成：{len(synced)} commands -> {[c.name for c in synced]}")
    except Exception as e:
        print("Guild sync 失敗：", e)
    print(f"✅ Logged in as {bot.user}")


async def setup_cogs():
    import cogs  # 確保 cogs 係一個 package

    # 用 cogs.__path__ 掃描，比傳入 'cogs' 更穩陣
    found = list(pkgutil.iter_modules(cogs.__path__))

    print("📁 cogs/ 目錄實際檔案：", os.listdir("cogs"))
    print("🔎 掃到模組：", [name for _, name, _ in found])

    loaded_any = False
    for _, name, ispkg in found:
        if name.startswith("_"):
            continue
        mod = f"cogs.{name}"
        try:
            await bot.load_extension(mod)
            print(f"🔌 Loaded {mod}")
            loaded_any = True
        except Exception:
            print(f"❌ Load {mod} 失敗：")
            traceback.print_exc()

    if not loaded_any:
        print("⚠️ 未載入到任何 cog，請檢查 .dockerignore / 路徑 / 語法。")


# ---------- Admin-only /reload ----------
from discord import app_commands
import importlib

def _is_admin(interaction: discord.Interaction) -> bool:
    # 伺服器管理員才可用
    return bool(interaction.user and interaction.user.guild_permissions.administrator)

@app_commands.guilds(config.GUILD_ID)             # 👈 新增：Guild-scoped
@app_commands.check(_is_admin)
@app_commands.describe(cog="可選，指定某個 cog 名稱（例如：drink）")
@bot.tree.command(name="reload", description="重載所有 / 指定的 cogs（只有管理員可用）")
async def reload_cogs(interaction: discord.Interaction, cog: str | None = None):
    await interaction.response.defer(ephemeral=True)

    import cogs  # 確保是 package
    found = {name: ispkg for _, name, ispkg in pkgutil.iter_modules(cogs.__path__)}
    targets = []

    if cog:
        if cog in found:
            targets = [cog]
        else:
            await interaction.followup.send(f"找不到 cog：`{cog}`。可用：`{', '.join(sorted(found))}`", ephemeral=True)
            return
    else:
        targets = sorted(n for n in found.keys() if not n.startswith("_"))

    ok, fail = [], []
    for name in targets:
        mod = f"cogs.{name}"
        try:
            # 先卸載（如果已載）
            try:
                await bot.unload_extension(mod)
            except commands.ExtensionNotLoaded:
                pass
            # 再載入
            await bot.load_extension(mod)
            ok.append(name)
            print(f"🔁 Reloaded {mod}")
        except Exception as e:
            fail.append((name, repr(e)))
            print(f"❌ Reload {mod} 失敗：{e}")
            traceback.print_exc()

    # 重新同步 guild commands（即時生效）
    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🔄 Resynced commands: {len(synced)}")
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

@reload_cogs.error
async def reload_cogs_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("此指令只限 **管理員** 使用。", ephemeral=True)
    else:
        await interaction.response.send_message(f"出錯了：{error}", ephemeral=True)

async def main():
    if not config.TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    async with bot:
        await setup_cogs()
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
