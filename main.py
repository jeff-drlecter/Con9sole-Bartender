# Con9sole-Bartender — Fly.io 版
# 功能：/duplicate 依照模板分區複製出新遊戲分區（含 Text/Voice/Stage/Forum、可複製 Forum Tags）
# 同步：啟動時 Global sync + 嘗試 Guild sync（秒生效），並輸出詳細 log 方便排錯

import os
from typing import Dict, Optional, List

import discord
from discord.ext import commands
from discord import app_commands


# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731                  # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343     # 「模板分區」Category ID
# 👉 如果要從某個 Forum 複製 Tag，填該 Forum Channel 的 ID；不需要就設 None
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519

# 新建分區與角色的命名規則
CATEGORY_NAME_PATTERN = "{game}"        # 例："EA {game}" -> "EA Delta Force"
ROLE_NAME_PATTERN = "{game}"            # 例："FC26"

# 新分區可同時開放俾以下固定管理角色（現有角色 ID，非新建）
ADMIN_ROLE_IDS: List[int] = []          # 例如 [123456789012345678]

# ⚠️ 後備頻道（只在「模板缺少某類頻道」時才會補上）
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],  # 文字頻道（模板冇先補）
    "forum": None,                       # 不用後備 Forum；如要強制有一個 forum，可填入名字，例如 "分區討論區"
    "voice": ["小隊Call 1", "小隊Call 2"]
}
# =================================


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")

# Slash 指令唔需要 message content intent；guilds 就夠
intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Helper：權限覆寫 ----------
def make_private_overwrites(
    guild: discord.Guild,
    allow_roles: List[discord.Role],
    manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """@everyone 看不到；allow_roles 可見/發言/加入語音；manage_roles 另給管理權限"""
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for r in allow_roles:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
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


# ---------- 核心：複製整個分區 ----------
async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    print(f"▶️ 開始複製分區，模板 Category={TEMPLATE_CATEGORY_ID}，模板 Forum={TEMPLATE_FORUM_ID}")
    template_cat = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（實際：{type(template_cat).__name__}）")

    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]
    print(f"📦 模板下子頻道數：{len(template_children)}")

    # 1) 新角色
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if new_role:
        print(f"ℹ️ 角色已存在：{new_role.name}（{new_role.id}）")
    else:
        new_role = await guild.create_role(
            name=role_name, hoist=False, mentionable=True, reason="Create role for new game section"
        )
        print(f"✅ 新角色：{new_role.name}（{new_role.id}）")
    admin_roles = [guild.get_role(rid) for rid in ADMIN_ROLE_IDS if guild.get_role(rid)]

    # 2) 新分區 + 鎖權限
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 新分區：#{new_cat.name}（{new_cat.id}）已上鎖（只有新角色/管理看得到）")

    created_forum: Optional[discord.ForumChannel] = None
    name_set = set()

    # 3) 依模板建立各類頻道
    for ch in template_children:
        name_set.add(ch.name)
        ow = make_private_overwrites(guild, [new_role], admin_roles)

        if isinstance(ch, discord.TextChannel):
            await guild.create_text_channel(ch.name, category=new_cat, overwrites=ow)
            print(f"   📝 Text：#{ch.name} ✅")

        elif isinstance(ch, discord.VoiceChannel):
            kwargs = {}
            if ch.bitrate is not None: kwargs["bitrate"] = ch.bitrate
            if ch.user_limit is not None: kwargs["user_limit"] = ch.user_limit
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_voice_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"   🔊 Voice：{ch.name} ✅")

        elif isinstance(ch, discord.StageChannel):
            kwargs = {}
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_stage_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"   🎤 Stage：{ch.name} ✅")

        elif isinstance(ch, discord.ForumChannel):
            created_forum = await guild.create_forum(ch.name, category=new_cat, overwrites=ow)
            print(f"   🗂️ Forum：#{ch.name} ✅")

        else:
            print(f"   （略過不支援的頻道類型）{ch.name}")

    # 4) 用後備補上缺的標準頻道
    # Text
    for tname in FALLBACK_CHANNELS.get("text", []) or []:
        if tname not in name_set:
            ow = make_private_overwrites(guild, [new_role], admin_roles)
            await guild.create_text_channel(tname, category=new_cat, overwrites=ow)
            print(f"   📝 Text（fallback）：#{tname} ✅")
    # Voice
    for vname in FALLBACK_CHANNELS.get("voice", []) or []:
        if vname not in name_set:
            ow = make_private_overwrites(guild, [new_role], admin_roles)
            await guild.create_voice_channel(vname, category=new_cat, overwrites=ow)
            print(f"   🔊 Voice（fallback）：{vname} ✅")
    # Forum（若模板無而且設定了後備名字）
    if not created_forum and (fname := FALLBACK_CHANNELS.get("forum")):
        ow = make_private_overwrites(guild, [new_role], admin_roles)
        created_forum = await guild.create_forum(fname, category=new_cat, overwrites=ow)
        print(f"   🗂️ Forum（fallback）：#{fname} ✅")

    # 5) 複製 Forum Tags（如有）
    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if TEMPLATE_FORUM_ID:
            c = await client.fetch_channel(TEMPLATE_FORUM_ID)
            if isinstance(c, discord.ForumChannel):
                tag_src = c
            else:
                print("⚠️ TEMPLATE_FORUM_ID 並不是 Forum，略過複製標籤。")
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"


# ---------- Slash 指令 ----------
@bot.tree.command(name="duplicate", description="（管理用）用模板分區複製出新遊戲分區")
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.checks.has_permissions(manage_channels=True)  # 只有有管理頻道權限的人可用
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        msg = await duplicate_section(interaction.client, interaction.guild, gamename)
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 出錯：{e}", ephemeral=True)


# ---------- 啟動：同步指令（Global + Guild） ----------
@bot.event
async def on_ready():
    print("🚀 Bot 啟動，開始同步指令…")
    # 1) Global sync（任何伺服器可見；首次需數分鐘，其後很快）
    try:
        gsynced = await bot.tree.sync()
        print(f"🌍 Global sync 完成：{len(gsynced)} commands")
    except Exception as e:
        print("Global sync 失敗：", e)

    # 2) 嘗試把 Global commands 複製到指定 Guild，並 Guild sync（通常即時）
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            bot.tree.copy_global_to(guild=guild)
            ls = await bot.tree.sync(guild=guild)
            print(f"🏠 Guild({GUILD_ID}) sync 完成：{len(ls)} commands")
        else:
            print(f"⚠️ Cache 未見到 Guild {GUILD_ID}；如果 Bot 已在該伺服器，稍後會再可見")
    except Exception as e:
        print("Guild sync 失敗：", e)

    print(f"✅ Logged in as {bot.user}")


if __name__ == "__main__":
    bot.run(TOKEN)
