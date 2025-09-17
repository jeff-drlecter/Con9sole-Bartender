import asyncio
import pkgutil
import traceback
import discord
from discord.ext import commands
import config

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
    for m in pkgutil.iter_modules(['cogs']):
        name = m.name
        if name.startswith('_'):
            continue
        ext = f"cogs.{name}"
        try:
            await bot.load_extension(ext)
            print(f"🔌 Loaded {ext}")
        except Exception:
            print(f"❌ Load {ext} 失敗：")
            traceback.print_exc()

async def main():
    if not config.TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    async with bot:
        await setup_cogs()
        await bot.start(config.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
