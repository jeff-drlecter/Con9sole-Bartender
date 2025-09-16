# Con9sole-Bartender — Fly.io 版（含 /duplicate，同步指令）
import os
from typing import Dict, Optional, List

import discord
from discord.ext import commands
from discord import app_commands

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731                  # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343     # 模板 Category
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # （可選）模板 Forum（複製 tags），不想複製可設 None

CATEGORY_NAME_PATTERN = "{game}"    # 分區命名規則（要前綴可改 "EA {game}"）
ROLE_NAME_PATTERN = "{game}"        # 角色命名規則
ADMIN_ROLE_IDS: List[int] = []      # 固定管理角色（可留空）
FALLBACK_CHANNELS = {"text": ["read-me"], "forum": "遊戲專屬討論區", "voice": ["📣5️⃣ Lobby（夠5個開波）"]}
# =================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=GUILD_ID)  # Guild-scope 同步，秒生效

# ---------- Helpers ----------
def make_private_overwrites(
    guild: discord.Guild, allow_roles: List[discord.Role], manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for r in allow_roles:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            create_public_threads=True, create_private_threads=True, send_messages_in_threads=True,
            connect=True, speak=True
        )
    for r in manage_roles:
        curr = ow.get(r, discord.PermissionOverwrite())
        curr.manage_channels = True
        curr.manage_messages = True
        curr.manage_threads = True
        curr.move_members = True
        curr.mute_members = True
        ow[r] = curr
    return ow

async def copy_forum_tags(src_forum: discord.ForumChannel, dst_forum: discord.ForumChannel):
    tags = src_forum.available_tags
    if not tags:
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")

async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    template_cat = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        raise RuntimeError(f"TEMPLATE_CATEGORY_ID 不是 Category，而是 {type(template_cat).__name__}")
    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]

    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(name=role_name, hoist=False, mentionable=True, reason="Create game role")
    admin_roles = [guild.get_role(rid) for rid in ADMIN_ROLE_IDS if guild.get_role(rid)]

    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))

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

    if not created_forum and FALLBACK_CHANNELS.get("forum"):
        created_forum = await guild.create_forum(
            FALLBACK_CHANNELS["forum"], category=new_cat,
            overwrites=make_private_overwrites(guild, [new_role], admin_roles)
        )

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

# ---------- Slash 指令 ----------
@bot.tree.command(name="duplicate", description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）")
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.checks.has_permissions(manage_channels=True)  # 只允許有 Manage Channels 嘅人用
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    try:
        msg = await duplicate_section(interaction.client, interaction.guild, gamename)
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 出錯：{e}", ephemeral=True)

@bot.event
async def on_ready():
    # 先做 guild-scope sync（秒生效），再備援 global sync（首次可能要幾分鐘）
    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🔁 Guild sync 完成：{len(synced)} commands")
    except Exception as e:
        print("Guild sync 失敗：", e)

    try:
        await bot.tree.sync()
        print("🌍 Global sync 提交完成")
    except Exception as e:
        print("Global sync 失敗：", e)

    print(f"✅ Logged in as {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    bot.run(TOKEN)
