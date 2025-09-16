# Con9sole-Bartender — main.py
# - Guild-only slash commands
# - /ping, /duplicate
# - /duplicate 只限 Admin 或 Helper 角色使用
# - 會複製模板分區內的 Text/Voice/Stage/Forum，並補上 FALLBACK_CHANNELS
# - 複製 Forum Tags
# - 使用環境變數 DISCORD_BOT_TOKEN（如無則回退 DISCORD_TOKEN）

import os
from typing import Dict, Optional, List
import discord
from discord.ext import commands
from discord import app_commands

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731
TEMPLATE_CATEGORY_ID: int = 1417446665626849343
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519  # 可選：用來複製 Forum Tags

CATEGORY_NAME_PATTERN = "{game}"
ROLE_NAME_PATTERN = "{game}"

ADMIN_ROLE_IDS: List[int] = []                     # 固定管理角色（可留空）
HELPER_ROLE_IDS: List[int] = [1279071042249162856] # ✅ 你的 Helper Role ID

FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],
    "forum": "分區討論區",
    "voice": ["小隊Call 1", "小隊Call 2"]
}
# =================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN（或 DISCORD_TOKEN）環境變數，請設定後再啟動。")

intents = discord.Intents(guilds=True, voice_states=True)
bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=GUILD_ID)

# ---------- Helpers ----------
def make_private_overwrites(
    guild: discord.Guild, allow_roles: List[discord.Role], manage_roles: List[discord.Role]
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
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

def user_is_admin_or_helper(inter: discord.Interaction) -> bool:
    """允許：Administrator／Manage Channels／擁有 HELPER_ROLE_IDS 指定角色"""
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    if HELPER_ROLE_IDS and any(r.id in HELPER_ROLE_IDS for r in m.roles):
        return True
    return False

async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    # 取得模板 Category 及其子頻道
    template_cat = guild.get_channel(TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        ch = await client.fetch_channel(TEMPLATE_CATEGORY_ID)
        if not isinstance(ch, discord.CategoryChannel):
            raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（而是 {type(ch).__name__}）。")
        template_cat = ch

    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]
    print(f"▶️ 模板分區：#{template_cat.name}（{template_cat.id}） 子頻道：{len(template_children)}")

    # 建新 Role（若存在則重用）
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(name=role_name, hoist=False, mentionable=True, reason="Create game role")
        print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")
    else:
        print(f"ℹ️ 角色已存在：{new_role.name}（{new_role.id}）")

    admin_roles = [r for rid in ADMIN_ROLE_IDS if (r := guild.get_role(rid))]

    # 建新 Category（先設私密權限）
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

    # 建頻道：先按模板複製；再補 fallback
    created_forum: Optional[discord.ForumChannel] = None
    existing_names = set()

    async def ensure_text(name: str, tmpl: Optional[discord.TextChannel]):
        if name in existing_names: return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        ch = await guild.create_text_channel(name=name, category=new_cat, overwrites=ow)
        existing_names.add(name)
        print(f"   📝 Text：#{ch.name} ✅")

    async def ensure_voice(name: str, tmpl: Optional[discord.VoiceChannel]):
        if name in existing_names: return
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
        if name in existing_names: return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        kwargs = {}
        if tmpl and tmpl.rtc_region is not None:
            kwargs["rtc_region"] = tmpl.rtc_region
        ch = await guild.create_stage_channel(name=name, category=new_cat, overwrites=ow, **kwargs)
        existing_names.add(name)
        print(f"   🎤 Stage：{ch.name} ✅")

    async def ensure_forum(name: str, tmpl: Optional[discord.ForumChannel]):
        nonlocal created_forum
        if created_forum: return
        ow = clone_overwrites_from(tmpl) or make_private_overwrites(guild, [new_role], admin_roles)
        created_forum = await guild.create_forum(name=name, category=new_cat, overwrites=ow)
        print(f"   🗂️ Forum：#{created_forum.name} ✅")

    # 1) 複製模板
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

    # 2) Fallback 補齊
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
            maybe = guild.get_channel(TEMPLATE_FORUM_ID) or await bot.fetch_channel(TEMPLATE_FORUM_ID)
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

@bot.tree.command(
    name="duplicate",
    description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）",
)
@app_commands.guilds(TARGET_GUILD)
@app_commands.default_permissions(manage_channels=True)  # ✅ 舊版兼容做法
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.check(user_is_admin_or_helper)
async def duplicate_cmd(interaction: discord.Interaction, gamename: str):
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

@duplicate_cmd.error
async def duplicate_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ 你沒有權限使用此指令。", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 發生錯誤，請稍後再試。", ephemeral=True)
        raise error

# ====== Temp VC（臨時語音房）設定 ======
# 任何擁有以下其中一個 Role 的會員，都可以用 /vc_new /vc_teardown
ALLOWED_TEMPVC_ROLE_IDS: list[int] = [
    1279040517451022419,  # ← 你指定嘅 role（Verified/TempVC 允許角色）
]

# 空房自動刪除延遲（秒）
TEMP_VC_AUTODELETE_SECONDS = 120

# 如要把操作記錄到某個 mod-log 文字頻道，可填入其 channel ID；唔用就 None
MOD_LOG_CHANNEL_ID: Optional[int] = None


# 允許使用 Temp VC 指令的檢查（Admin / Manage Channels / 或擁有上面 ALLOWED_TEMPVC_ROLE_IDS 任一角色）
def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    if ALLOWED_TEMPVC_ROLE_IDS and any(r.id in ALLOWED_TEMPVC_ROLE_IDS for r in m.roles):
        return True
    return False


# ====== Temp VC 內部狀態 ======
TEMP_VC_IDS: set[int] = set()                # 記錄由 Bot 建立嘅臨時 VC（重啟會清空，free tier 友善）
_PENDING_DELETE_TASKS: dict[int, asyncio.Task] = {}  # 避免重覆安排刪除


async def _maybe_log(guild: discord.Guild, text: str):
    if MOD_LOG_CHANNEL_ID:
        ch = guild.get_channel(MOD_LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(text)
            except Exception:
                pass


def _is_temp_vc_id(cid: Optional[int]) -> bool:
    return bool(cid and cid in TEMP_VC_IDS)


async def _schedule_delete_if_empty(vc: discord.VoiceChannel):
    """安排空房延遲刪除；期間如果有人加入會自動取消"""
    if vc.id in _PENDING_DELETE_TASKS:
        return

    async def _task():
        try:
            await asyncio.sleep(TEMP_VC_AUTODELETE_SECONDS)
            fresh = vc.guild.get_channel(vc.id)
            if isinstance(fresh, discord.VoiceChannel) and len(fresh.members) == 0:
                TEMP_VC_IDS.discard(vc.id)
                await _maybe_log(vc.guild, f"🗑️ 自動刪除空置 Temp VC：#{vc.name}（id={vc.id}）")
                await vc.delete(reason="Auto delete empty Temp VC")
        finally:
            _PENDING_DELETE_TASKS.pop(vc.id, None)

    _PENDING_DELETE_TASKS[vc.id] = asyncio.create_task(_task())


async def create_temp_vc(
    guild: discord.Guild,
    name: str,
    *,
    category: Optional[discord.CategoryChannel] = None,
    user_limit: Optional[int] = None,
):
    """
    在指定 category 內建立 VC，並與該 category 權限同步（不設自訂 overwrites）。
    亦即：繼承分區權限 → 只有該分區本身能見到/進入的人可以用。
    """
    vc = await guild.create_voice_channel(
        name=name,
        category=category,           # 跟該分區
        overwrites=None,             # 不覆蓋 → 直接繼承分區權限
        user_limit=user_limit or 0,  # 0 = 無上限
        reason="Create temporary VC (inherit category perms)",
    )
    TEMP_VC_IDS.add(vc.id)
    await _maybe_log(guild, f"🆕 建立 Temp VC（跟分區權限）：{vc.mention}（id={vc.id}）")
    return vc


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """
    監聽語音狀態：
    - 離開 Temp VC 後，如果該房無人 → 安排延時刪除。
    - 加入 Temp VC → 若之前有刪除計劃則取消。
    """
    try:
        if before.channel and _is_temp_vc_id(before.channel.id):
            if len(before.channel.members) == 0:
                await _schedule_delete_if_empty(before.channel)

        if after.channel and _is_temp_vc_id(after.channel.id):
            task = _PENDING_DELETE_TASKS.pop(after.channel.id, None)
            if task and not task.done():
                task.cancel()
    except Exception:
        # 靜默忽略，避免影響其他功能
        pass


# ========== Slash Commands：Temp VC ==========
@bot.tree.command(name="vc_new", description="建立臨時語音房（清空 120 秒自動刪）")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(
    name="語音房名稱",
    user_limit="人數上限（選填）",
)
@app_commands.check(user_can_run_tempvc)  # 允許：Admin/Manage Channels/指定角色
async def vc_new(inter: discord.Interaction, name: str, user_limit: Optional[int] = None):
    if not inter.guild:
        return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

    # 必須要喺某個分區入面用（用邊個分區，就喺嗰度開）
    channel = inter.channel
    category = None
    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
        category = channel.category
    if not isinstance(category, discord.CategoryChannel):
        return await inter.response.send_message("請喺目標分區入面執行指令（要有上層 Category）。", ephemeral=True)

    await inter.response.defer(ephemeral=True)
    vc = await create_temp_vc(inter.guild, name, category=category, user_limit=user_limit)
    await inter.followup.send(
        f"✅ 已建立臨時語音房：{vc.mention}（清空 {TEMP_VC_AUTODELETE_SECONDS}s 後自動刪）",
        ephemeral=True
    )


@bot.tree.command(name="vc_teardown", description="手動刪除由 Bot 建立的臨時語音房")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(
    channel="要刪嘅語音房（可選；唔填就刪你而家身處的 VC）"
)
@app_commands.check(user_can_run_tempvc)
async def vc_teardown(inter: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
    if not inter.guild:
        return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    target = channel
    if target is None:
        if isinstance(inter.user, discord.Member) and inter.user.voice and inter.user.voice.channel:
            target = inter.user.voice.channel  # type: ignore[assignment]

    if not isinstance(target, discord.VoiceChannel):
        return await inter.followup.send("請指定或身處一個語音房。", ephemeral=True)

    if not _is_temp_vc_id(target.id):
        return await inter.followup.send("呢個唔係由 Bot 建立的臨時語音房。", ephemeral=True)

    TEMP_VC_IDS.discard(target.id)
    task = _PENDING_DELETE_TASKS.pop(target.id, None)
    if task and not task.done():
        task.cancel()
    await _maybe_log(inter.guild, f"🗑️ 手動刪除 Temp VC：#{target.name}（id={target.id}）")
    await target.delete(reason="Manual teardown temp VC")
    await inter.followup.send("✅ 已刪除。", ephemeral=True)

# ---------- Lifecycle ----------
@bot.event
async def on_ready():
    print("🚀 Bot 啟動，開始同步指令（Guild-only）…")
    try:
        synced = await bot.tree.sync(guild=TARGET_GUILD)
        print(f"🏠 Guild({GUILD_ID}) sync 完成：{len(synced)} commands -> {[c.name for c in synced]}")
    except Exception as e:
        print("Guild sync 失敗：", e)
    print(f"✅ Logged in as {bot.user}")

if __name__ == "__main__":
    bot.run(TOKEN)
