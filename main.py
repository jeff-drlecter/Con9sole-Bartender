import os
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List

TOKEN = os.getenv("DISCORD_TOKEN")

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731   # 伺服器 ID
TEMPLATE_CATEGORY_ID: int = 1417446665626849343  # 模板分區 ID
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # 模板 Forum 頻道 ID (可選)

CATEGORY_NAME_PATTERN = "{game}"
ROLE_NAME_PATTERN = "{game}"
ADMIN_ROLE_IDS: List[int] = []  # 如有特定 Admin 角色可放入
HELPER_ROLE_IDS: List[int] = [1279071042249162856]  # ✅ Helper 角色 ID
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],
    "forum": "分區討論區",
    "voice": ["小隊Call 1", "小隊Call 2"]
}
# =================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ========= 權限檢查 =========
def user_is_admin_or_helper(inter: discord.Interaction) -> bool:
    """允許：Admin／擁有 Manage Channels ／擁有 Helper 角色"""
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False

    m: discord.Member = inter.user
    perms = m.guild_permissions

    # ① Admin 或 Manage Channels
    if perms.administrator or perms.manage_channels:
        return True

    # ② 擁有 Helper role ID
    if HELPER_ROLE_IDS:
        if any(r.id in HELPER_ROLE_IDS for r in m.roles):
            return True

    return False


# ========= Bot Ready =========
@bot.event
async def on_ready():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            # 清空 Global commands，避免出現兩個 duplicate
            await bot.tree.sync(guild=None)
            await bot.tree.sync(guild=guild)
            print(f"🚀 Bot 啟動，開始同步指令（Guild-only）…")
            print(f"🏠 Guild({guild.id}) sync 完成：{len(bot.tree.get_commands())} commands -> {[c.name for c in bot.tree.get_commands()]}")
        except Exception as e:
            print(f"❌ 指令同步失敗: {e}")
    print(f"✅ Logged in as {bot.user}")


# ========= Ping =========
@bot.tree.command(name="ping", description="測試 bot 延遲")
async def ping_cmd(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🔍 {latency_ms}ms", ephemeral=True)


# ========= Duplicate =========
@bot.tree.command(
    name="duplicate",
    description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）",
    default_member_permissions=discord.Permissions(manage_channels=True)
)
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.check(user_is_admin_or_helper)
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)

    guild = interaction.guild
    template_cat = guild.get_channel(TEMPLATE_CATEGORY_ID)
    if not template_cat or not isinstance(template_cat, discord.CategoryChannel):
        return await interaction.response.send_message("❌ 找不到模板分區。", ephemeral=True)

    # 建立新角色
    new_role = await guild.create_role(name=ROLE_NAME_PATTERN.format(game=gamename))
    print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")

    # 建立新分區
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        new_role: discord.PermissionOverwrite(view_channel=True)
    }
    new_cat = await guild.create_category(
        CATEGORY_NAME_PATTERN.format(game=gamename),
        overwrites=overwrites
    )
    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

    # 複製子頻道
    for ch in template_cat.channels:
        try:
            if isinstance(ch, discord.ForumChannel):
                forum = await guild.create_forum(
                    name=ch.name,
                    category=new_cat,
                    topic=ch.topic,
                    reason="Duplicate template forum"
                )
                print(f"🗂️ Forum：#{forum.name} ✅")
            elif isinstance(ch, discord.TextChannel):
                text = await guild.create_text_channel(name=ch.name, category=new_cat)
                print(f"📝 Text：#{text.name} ✅")
            elif isinstance(ch, discord.VoiceChannel):
                vc = await guild.create_voice_channel(name=ch.name, category=new_cat)
                print(f"🔊 Voice：{vc.name} ✅")
            elif isinstance(ch, discord.StageChannel):
                stage = await guild.create_stage_channel(name=ch.name, category=new_cat)
                print(f"🎤 Stage：{stage.name} ✅")
        except Exception as e:
            print(f"❌ 建立子頻道失敗：{ch.name} - {e}")

    await interaction.response.send_message(f"✅ 新分區：#{new_cat.name}；新角色：{new_role.name}（{new_role.id}）", ephemeral=True)


# ========= 錯誤處理 =========
@duplicate_cmd.error
async def duplicate_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ 你沒有權限使用此指令。", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 發生錯誤，請稍後再試。", ephemeral=True)
        raise error


# ========= Run =========
if __name__ == "__main__":
    bot.run(TOKEN)
