# main.py — Con9sole-Bartender (Render 版)
import os
import discord
from discord.ext import commands
from discord import app_commands
from typing import Dict, Optional, List

# ====== 你的伺服器/模板設定（用你提供的 ID）======
GUILD_ID: int = 626378673523785731                  # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343     # 模板分區（Category）
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # （可選）模板 Forum（用來複製 tags）；不想複製就設 None

# 命名規則（想要前綴可把 CATEGORY_NAME_PATTERN 改為 "EA {game}"）
CATEGORY_NAME_PATTERN = "{game}"
ROLE_NAME_PATTERN = "{game}"

# 一些固定管理角色（既有角色 ID），永遠可以看/管理新分區（可留空）
ADMIN_ROLE_IDS: List[int] = []

# 模板欠缺時的補位頻道
FALLBACK_CHANNELS = {"text": ["read-me"], "forum": "遊戲專屬討論區", "voice": ["📣5️⃣ Lobby（夠5個開波）"]}
# ==================================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # 在 Render 的 Environment 設定
intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Helpers ----------
def make_private_overwrites(
    guild: discord.Guild, allow_roles: List[discord.Role], manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """@everyone 看不到；allow_roles 可見／發言；manage_roles 另給管理權限"""
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for r in allow_roles:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            create_public_threads=True, create_private_threads=True, send_messages_in_threads=True,
            connect=True, speak=True
        )
    for r in manage_roles:
        current = ow.get(r, discord.PermissionOverwrite())
        current.manage_channels = True
        current.manage_messages = True
        current.manage_threads = True
        current.move_members = True
        current.mute_members = True
        ow[r] = current
    return ow

async def copy_forum_tags(src_forum: discord.ForumChannel, dst_forum: discord.ForumChannel):
    tags = src_forum.available_tags
    if not tags:
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")

async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    """按模板分區建立一個新的遊戲分區（含 Text/Voice/Forum/Stage + Forum Tags）"""
    # 1) 模板分區 + 子頻道
    template_cat = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        raise RuntimeError(f"TEMPLATE_CATEGORY_ID 不是 Category，而是 {type(template_cat).__name__}")
    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]

    # 2) 新角色
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(
            name=role_name, hoist=False, mentionable=True, reason="Create role for new game section"
        )
    admin_roles = [guild.get_role(rid) for rid in ADMIN_ROLE_IDS if guild.get_role(rid)]

    # 3) 新分區 + 鎖權限
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))

    # 4) 依模板建頻道
    created_forum: Optional[discord.ForumChannel] = None
    for ch in template_children:
        ow = make_private_overwrites(guild, [new_role], admin_roles)

        if isinstance(ch, discord.TextChannel):
            await guild.create_text_channel(ch.name, category=new_cat, overwrites=ow)

        elif isinstance(ch, discord.VoiceChannel):
            kwargs = {}
            if ch.bitrate is not None: kwargs["bitrate"] = ch.bitrate
            if ch.user_limit is not None: kwargs["user_limit"] = ch.user_limit
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_voice_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)

        elif isinstance(ch, discord.StageChannel):
            kwargs = {}
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_stage_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)

        elif isinstance(ch, discord.ForumChannel):
            created_forum = await guild.create_forum(ch.name, category=new_cat, overwrites=ow)

    # 5) 補 Forum（如模板沒有）
    if not created_forum and FALLBACK_CHANNELS.get("forum"):
        created_forum = await guild.create_forum(
            FALLBACK_CHANNELS["forum"], category=new_cat,
            overwrites=make_private_overwrites(guild, [new_role], admin_roles)
        )

    # 6) 複製 Forum Tags
    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if TEMPLATE_FORUM_ID:
            c = await client.fetch_channel(TEMPLATE_FORUM_ID)
            if isinstance(c, discord.ForumChannel): tag_src = c
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"

# ---------- Slash 指令：/duplicate ----------
TARGET_GUILD = discord.Object(id=GUILD_ID)

@bot.tree.command(name="duplicate", description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）")
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.manage_channels or perms.administrator):
        return await interaction.response.send_message("需要 Manage Channels 權限。", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    try:
        msg = await duplicate_section(interaction.client, interaction.guild, gamename)
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 出錯：{e}", ephemeral=True)

@bot.event
async def on_ready():
    try:
        await bot.tree.sync(guild=TARGET_GUILD)  # Guild 指令 → 幾秒生效
    except Exception as e:
        print("Sync failed:", e)
    print(f"Logged in as {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    bot.run(TOKEN)
