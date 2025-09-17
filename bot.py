import discord
from discord.ext import commands
import config

intents = discord.Intents(
    guilds=True, members=True, voice_states=True,
    messages=True, message_content=True
)

bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=config.GUILD_ID)

initial_cogs = [
    "cogs.duplicate",
    "cogs.tempvc",
    "cogs.teams",
    "cogs.welcome_log",
    "cogs.message_audit",
    "cogs.role_channel_emoji_log",
]

@bot.event
async def on_ready():
    print("🚀 Bot 啟動，開始同步指令（Guild-only）…")
    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🏠 Guild({config.GUILD_ID}) sync 完成：{len(synced)} commands -> {[c.name for c in synced]}")
    except Exception as e:
        print("Guild sync 失敗：", e)
    print(f"✅ Logged in as {bot.user}")

if __name__ == "__main__":
    for ext in initial_cogs:
        try:
            bot.load_extension(ext)
            print(f"🔌 Loaded {ext}")
        except Exception as e:
            print(f"❌ Load {ext} 失敗：{e}")

    if not config.TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    bot.run(config.TOKEN)
