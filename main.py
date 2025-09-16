# Con9sole-Bartender — Fly.io 版（Global sync, Duplicate + Ping + Error handler）
import os
import traceback
from typing import Dict, Optional, List

import discord
from discord.ext import commands
from discord import app_commands

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731                  # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343     # 模板 Category
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # （可選）模板 Forum（複製 tags）；不想複製可設 None

CATEGORY_NAME_PATTERN = "{game}"    # 分區命名規則
ROLE_NAME_PATTERN = "{game}"        # 角色命名規則
ADMIN_ROLE_IDS: List[int] = []      # 固定管理角色（可留空）

FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],  # 文字頻道（模板冇先補）
    "forum": "分區討論區",                # 後備 Forum 名稱（如模板無）
    "voice": ["小隊Call 1", "小隊Call 2"]
}
# =================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")

# slash 指令唔需要 message content intent；guilds 就夠
intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)

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
        print("ℹ️ 模板 Forum 無可用標籤，略過複製。")
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    print(f"✅ 已複製 Forum Tags：{len(new_tags)}")

async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    print(f"▶️ duplicate_section: template_cat={TEMPLATE_CATEGORY_ID}, template_forum={TEMPLATE_FORUM_ID}, game={game_name}")
    template_cat = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（實際：{type(template_cat).__name__}）")

    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, 'category_id', None) == template_cat.id]
    print(f"📦 模板子頻道數：{len(template_children)}")

    # 1) 新角色
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(name=role_name, hoist=False, mentionable=True, reason="Create game role")
        print(f"✅ 新角色：{new_role.name}（{new_role.id}）")
    admin_roles = [guild.get_role(rid) for rid in ADMIN_ROLE_IDS if guild.get_role(rid)]

    # 2) 新分區 + 權限
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 新分區：#{new_cat.name}（{new_cat.id}）")

    # 3) 依模板建頻道
    created_forum: Optional[discord.ForumChannel] = None
    existing_names = set()
    for ch in template_children:
        existing_names.add(ch.name)
        ow = make_private_overwrites(guild, [new_role], admin_roles)

        if isinstance(ch, discord.TextChannel):
            await guild.create_text_channel(ch.name, category=new_cat, overwrites=ow)
            print(f"   📝 Text：#{ch.name} ✅")
        elif isinstance(ch, discord.VoiceChannel):
            kwargs = {}
            if ch.bitrate is not None: kwargs['bitrate'] = ch.bitrate
            if ch.user_limit is not None: kwargs['user_limit'] = ch.user_limit
            if ch.rtc_region is not None: kwargs['rtc_region'] = ch.rtc_region
            await guild.create_voice_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"   🔊 Voice：{ch.name} ✅")
        elif isinstance(ch, discord.StageChannel):
            kwargs = {}
            if ch.rtc_region is not None: kwargs['rtc_region'] = ch.rtc_region
            await guild.create_stage_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"   🎤 Stage：{ch.name} ✅")
        elif isinstance(ch, discord.ForumChannel):
            created_forum = await guild.create_forum(ch.name, category=new_cat, overwrites=ow)
            print(f"   🗂️ Forum：#{ch.name} ✅")

    # 4) 後備頻道補上
    for t in FALLBACK_CHANNELS.get("text", []) or []:
        if t not in existing_names:
            await guild.create_text_channel(t, category=new_cat, overwrites=make_private_overwrites(guild, [new_role], admin_roles))
            print(f"   📝 Text（fallback）：#{t} ✅")
    for v in FALLBACK_CHANNELS.get("voice", []) or []:
        if v not in existing_names:
            await guild.create_voice_channel(v, category=new_cat, overwrites=make_private_overwrites(guild, [new_role], admin_roles))
            print(f"   🔊 Voice（fallback）：{v} ✅")
    if not created_forum and (fname := FALLBACK_CHANNELS.get("forum")):
        created_forum = await guild.create_forum(fname, category=new_cat, overwrites=make_private_overwrites(guild, [new_role], admin_roles))
        print(f"   🗂️ Forum（fallback）：#{fname} ✅")

    # 5) 複製 Forum Tags
    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if TEMPLATE_FORUM_ID:
            c = await client.fetch_channel(TEMPLATE_FORUM_ID)
            if isinstance(c, discord.ForumChannel):
                tag_src = c
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"

# ---------- Global error handler ----------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print("Slash command error:")
    traceback.print_exception(type(error), error, error.__traceback__)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ 出錯：{error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ 出錯：{error}", ephemeral=True)
    except Exception as e:
        print("Failed to send error message:", e)

# ---------- Slash 指令 ----------
@bot.tree.command(name="ping", description="healthcheck")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("pong", ephemeral=True)

@bot.tree.command(name="duplicate", description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）")
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        msg = await duplicate_section(interaction.client, interaction.guild, gamename)
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)
    except Exception as e:
        traceback.print_exception(type(e), e, e.__traceback__)
        await interaction.followup.send(f"❌ 出錯：{e}", ephemeral=True)

# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()   # 只做 Global，同步 1 次
        print(f"🌍 Global sync 完成：{len(synced)} commands")
    except Exception as e:
        print("Global sync 失敗：", e)

# ---------- Main ----------
if __name__ == "__main__":
    bot.run(TOKEN)
