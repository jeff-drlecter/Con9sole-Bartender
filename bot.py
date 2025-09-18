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
    try:
        bot.tree.add_command(reload_cogs, guild=TARGET_GUILD)
    except app_commands.CommandAlreadyRegistered:
        pass
    
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

async def main():
    if not config.TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    async with bot:
        await setup_cogs()
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
