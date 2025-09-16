# Con9sole-Bartender — main.py (Guild-only slash commands, no global clearing)
# 要求：
#   - 環境變數：DISCORD_BOT_TOKEN
#   - Bot 權限：Manage Channels、Manage Roles（至少）
#   - 在 Discord Dev Portal 已開啟 Privileged Intents 非必須（slash 指令唔需要）

import os
from typing import Dict, Optional, List

import discord
from discord.ext import commands
from discord import app_commands


# ====== 你的伺服器/模板設定（請按需要修改）======
GUILD_ID: int = 626378673523785731                  # 伺服器 ID
TEMPLATE_CATEGORY_ID: int = 1417446665626849343     # 模板 Category ID
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # （可選）模板 Forum ID（用來複製 tags）

# 新分區/角色命名規則
CATEGORY_NAME_PATTERN = "{game}"    # 例如 "EA {game}" 會變 "EA Delta Force"
ROLE_NAME_PATTERN = "{game}"

# 會被加入「可見/管理」權限的常設管理角色（填現有 Role 的 ID；留空即無）
ADMIN_ROLE_IDS: List[int] = []

# 如果模板內欠缺某類頻道，會用呢個 fallback 自動補上
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],   # 文字頻道
    "forum": "分區討論區",                # 如不需要 forum 後備，可設為 None
    "voice": ["小隊Call 1", "小隊Call 2"] # 語音頻道
}
# =============================================


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")

# 只開 Guilds intents（slash 指令足夠）
intents = discord.Intents.none()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=GUILD_ID)  # 用於 guild-only 註冊


# ---------- Helpers ----------
def make_private_overwrites(
    guild: discord.Guild,
    allow_roles: List[discord.Role],
    manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """
    令分區/頻道對 @everyone 隱藏；allow_roles 可見發言；
    manage_roles 額外管理權限。
    """
    ow: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False)
    }
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


def clone_overwrites_from(src: Optional[discord.abc.GuildChannel]) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    return {} if not src else {target: ow for target, ow in src.overwrites.items()}


async def copy_forum_tags(src_forum: discord.ForumChannel, dst_forum: discord.ForumChannel):
    tags = src_forum.available_tags
    if not tags:
        print("   （Tag）模板 Forum 無可用標籤，略過。")
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    print(f"   ✅ 已複製 Forum Tags：{len(new_tags)}")


async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    # 取得模板 Category 及其子頻道
    template_cat = guild.get_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        # 如果 cache 無，試 fetch
        ch = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
        if not isinstance(ch, discord.CategoryChannel):
            raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（實際是 {type(ch).__name__}）。")
        template_cat = ch

    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]
    print(f"▶️ 模板分區：#{template_cat.name}（{template_cat.id}） 子頻道：{len(template_children)}")

    # 建新 Role（如果同名已存在就重用）
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(
            name=role_name, hoist=False, mentionable=True, reason="Create game role"
        )
        print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")
    else:
        print(f"ℹ️ 角色已存在：{new_role.name}（{new_role.id}）")

    admin_roles = [r for rid in ADMIN_ROLE_IDS if (r := guild.get_role(rid))]

    # 建新 Category（先設私密權限）
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

    # 建頻道：優先按模板複製；其後補上 fallback
    created_forum: Optional[discord.ForumChannel] = None
    existing_names = set()

    async def ensure_text(name: str, tmpl: Optional[discord.TextChannel]):
        nonlocal existing_names
        if name in existing_names:
            return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        ch = await guild.create_text_channel(name=name, category=new_cat, overwrites=ow)
        existing_names.add(name)
        print(f"   📝 Text：#{ch.name} ✅")

    async def ensure_voice(name: str, tmpl: Optional[discord.VoiceChannel]):
        nonlocal existing_names
        if name in existing_names:
            return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        kwargs = {}
        if tmpl:
            if tmpl.bitrate is not None: kwargs["bitrate"] = tmpl.bitrate
            if tmpl.user_limit is not None: kwargs["user_limit"] = tmpl.user_limit
            if tmpl.rtc_region is not None: kwargs["rtc_region"] = tmpl.rtc_region
        ch = await guild.create_voice_channel(name=name, category=new_cat, overwrites=ow, **kwargs)
        existing_names.add(name)
        print(f"   🔊 Voice：{ch.name} ✅")

    async def ensure_stage(name: str, tmpl: Optional[discord.StageChannel]):
        nonlocal existing_names
        if name in existing_names:
            return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        kwargs = {}
        if tmpl and tmpl.rtc_region is not None:
            kwargs["rtc_region"] = tmpl.rtc_region
        ch = await guild.create_stage_channel(name=name, category=new_cat, overwrites=ow, **kwargs)
        existing_names.add(name)
        print(f"   🎤 Stage：{ch.name} ✅")

    async def ensure_forum(name: str, tmpl: Optional[discord.ForumChannel]):
        nonlocal existing_names, created_forum
        if created_forum or name in existing_names:
            return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        created_forum = await guild.create_forum(name=name, category=new_cat, overwrites=ow)
        existing_names.add(name)
        print(f"   🗂️ Forum：#{created_forum.name} ✅")

    # 1) 按模板逐一複製
    for ch in template_children:
        if isinstance(ch, discord.TextChannel):
            await ensure_text(ch.name, ch)
        elif isinstance(ch, discord.VoiceChannel):
            await ensure_voice(ch.name, ch)
        elif isinstance(ch, discord.StageChannel):
            await ensure_stage(ch.name, ch)
        elif isinstance(ch, discord.ForumChannel):
            await ensure_forum(ch.name, ch)
        else:
            print(f"   （略過）{ch.name} 類型：{type(ch).__name__}")

    # 2) 用 fallback 補齊
    for name in FALLBACK_CHANNELS.get("text", []) or []:
        await ensure_text(name, None)
    for name in FALLBACK_CHANNELS.get("voice", []) or []:
        await ensure_voice(name, None)
    fb_forum = FALLBACK_CHANNELS.get("forum")
    if fb_forum and not created_forum:
        await ensure_forum(fb_forum, None)

    # 3) 複製 Forum Tags
    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if TEMPLATE_FORUM_ID:
            maybe = guild.get_channel(TEMPLATE_FORUM_ID) or await client.fetch_channel(TEMPLATE_FORUM_ID)
            if isinstance(maybe, discord.ForumChannel):
                tag_src = maybe
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}（{new_role.id}）"


# ---------- Slash Commands（Guild-only）----------
@bot.tree.command(name="ping", description="Health check")
@app_commands.guilds(TARGET_GUILD)
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! 🏓 {round(bot.latency*1000)}ms", ephemeral=True)


@bot.tree.command(name="duplicate", description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
    # 限伺服器（雙重保險）
    if interaction.guild_id != GUILD_ID:
        return await interaction.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        msg = await duplicate_section(interaction.client, interaction.guild, gamename.strip())
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ 權限不足：請確保 Bot 擁有 Manage Channels / Manage Roles。", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 出錯：{e}", ephemeral=True)


# ---------- Lifecycle ----------
@bot.event
async def on_ready():
    print("🚀 Bot 啟動，開始同步指令（Guild-only）…")
    try:
        # 只做 Guild-scope 同步 → 秒生效、避免 UI 出 duplicate
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🏠 Guild({GUILD_ID}) sync 完成：{len(synced)} commands -> {[c.name for c in synced]}")
    except Exception as e:
        print("Guild sync 失敗：", e)
    print(f"✅ Logged in as {bot.user}")


if __name__ == "__main__":
    bot.run(TOKEN)
