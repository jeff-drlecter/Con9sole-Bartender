# Con9sole-Bartender — main.py
# 功能：
# 1) /duplicate 依模板分區建立新遊戲分區（含 Forum/Stage/Tags）
#    只有「Administrator」或「Manage Channels」可用
# 2) /vc_new、/vc_teardown 建立／移除臨時語音房（空房 120 秒自動刪除）
#    擁有 VERIFIED_ROLE_ID 即可（無須管理權）
# 3) /tu 隨機分隊（同樣需 VERIFIED_ROLE_ID）
# 4) 歡迎訊息 + 伺服器活動 Logging（取代 Dyno 風格）

import os
import asyncio
import random
from typing import Dict, Optional, List, Set
from datetime import datetime, timezone


import discord
from discord import app_commands
from discord.ext import commands

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731                     # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343        # 模板 Category
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519 # 可選；用作複製 forum tags

CATEGORY_NAME_PATTERN = "{game}"   # 新分區命名
ROLE_NAME_PATTERN = "{game}"       # 新角色命名
ADMIN_ROLE_IDS: List[int] = []     # 額外管理角色（可留空）

# 後備頻道（當模板無該類型時會建立）
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],
    "forum": "分區討論區",
    "voice": ["小隊Call 1", "小隊Call 2"],
}

# 臨時語音房設定
VERIFIED_ROLE_ID: int = 1279040517451022419   # 擁有此角色即可用 /vc_new、/vc_teardown、/tu
TEMP_VC_EMPTY_SECONDS: int = 120              # 無人時自動刪除的等待秒數
TEMP_VC_PREFIX: str = "Temp • "               # 自動命名前綴

# 歡迎訊息發送位置（請換成你嘅頻道 ID）
WELCOME_CHANNEL_ID: int = 1010456227769229355  # 歡迎訊息要發送嘅頻道
RULES_CHANNEL_ID: int   = 1278976821710426133 # #rules
GUIDE_CHANNEL_ID: int   = 1279074807685578885 # #教學
SUPPORT_CHANNEL_ID: int = 1362781427287986407 # #支援

# Logging 目的地
LOG_CHANNEL_ID: int = 1401346745346297966

# =================================

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
intents = discord.Intents(
    guilds=True, members=True, voice_states=True,
    messages=True, message_content=True
)
bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_GUILD = discord.Object(id=GUILD_ID)  # guild-scope 同步（秒生效）

# ---- Temp VC 內部狀態 ----
TEMP_VC_IDS: Set[int] = set()
_PENDING_DELETE_TASKS: Dict[int, asyncio.Task] = {}

# ---------- 共用 Helper ----------
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
        print("   （Tag）模板 Forum 無可用標籤，略過。")
        return
    new_tags = [discord.ForumTag(name=t.name, moderated=t.moderated, emoji=t.emoji) for t in tags]
    await dst_forum.edit(available_tags=new_tags, reason="Clone forum tags")
    print(f"   ✅ 已複製 Forum Tags：{len(new_tags)}")

# ---------- Duplicate（建立新分區） ----------
def user_is_section_admin(inter: discord.Interaction) -> bool:
    """只有 Administrator 或 Manage Channels 才可用 /duplicate。"""
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    return bool(perms.administrator or perms.manage_channels)

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

    # 角色
    role_name = ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(name=role_name, hoist=False, mentionable=True, reason="Create game role")
        print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")

    admin_roles = [guild.get_role(rid) for rid in ADMIN_ROLE_IDS if guild.get_role(rid)]

    # 新分區
    cat_name = CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

    created_forum: Optional[discord.ForumChannel] = None

    # 依模板逐個建立
    for ch in template_children:
        ow = make_private_overwrites(guild, [new_role], admin_roles)

        if isinstance(ch, discord.TextChannel):
            await guild.create_text_channel(ch.name, category=new_cat, overwrites=ow)
            print(f"  📝 Text：#{ch.name} ✅")

        elif isinstance(ch, discord.VoiceChannel):
            kwargs = {}
            if ch.bitrate is not None: kwargs["bitrate"] = ch.bitrate
            if ch.user_limit is not None: kwargs["user_limit"] = ch.user_limit
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_voice_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"  🔊 Voice：{ch.name} ✅")

        elif isinstance(ch, discord.StageChannel):
            kwargs = {}
            if ch.rtc_region is not None: kwargs["rtc_region"] = ch.rtc_region
            await guild.create_stage_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            print(f"  🎤 Stage：{ch.name} ✅")

        elif isinstance(ch, discord.ForumChannel):
            created_forum = await guild.create_forum(ch.name, category=new_cat, overwrites=ow)
            print(f"  🗂️ Forum：#{ch.name} ✅")

    # 如果模板沒有 Forum，用後備
    if not created_forum and FALLBACK_CHANNELS.get("forum"):
        created_forum = await guild.create_forum(
            FALLBACK_CHANNELS["forum"], category=new_cat,
            overwrites=make_private_overwrites(guild, [new_role], admin_roles)
        )
        print(f"  🗂️ Forum（fallback）：#{created_forum.name} ✅")

    # 複製 Forum tags
    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if TEMPLATE_FORUM_ID:
            c = await client.fetch_channel(TEMPLATE_FORUM_ID)
            if isinstance(c, discord.ForumChannel): tag_src = c
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    # 後備：如果模板完全沒有某些類型，補上
    names_in_cat = {c.name for c in await guild.fetch_channels() if getattr(c, "category_id", None) == new_cat.id}
    for tname in FALLBACK_CHANNELS.get("text", []):
        if tname not in names_in_cat:
            await guild.create_text_channel(tname, category=new_cat,
                                            overwrites=make_private_overwrites(guild, [new_role], admin_roles))
            print(f"  📝（fallback）Text：#{tname} ✅")
    for vname in FALLBACK_CHANNELS.get("voice", []):
        if vname not in names_in_cat:
            await guild.create_voice_channel(vname, category=new_cat,
                                             overwrites=make_private_overwrites(guild, [new_role], admin_roles))
            print(f"  🔊（fallback）Voice：{vname} ✅")

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"

# ---------- Channel Helper ----------
def _category_from_ctx_channel(ch: Optional[discord.abc.GuildChannel]) -> Optional[discord.CategoryChannel]:
    """從目前上下文 channel 取對應的 Category（支援 Forum 貼文 thread）。"""
    if ch is None:
        return None
    if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
        return ch.category
    if isinstance(ch, discord.Thread):
        parent = ch.parent  # TextChannel 或 ForumChannel
        if isinstance(parent, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel)):
            return parent.category
        return None
    return None

# ---------- Logging Helpers ----------
def _log_chan(guild: discord.Guild) -> Optional[discord.TextChannel]:
    ch = guild.get_channel(LOG_CHANNEL_ID)
    return ch if isinstance(ch, discord.TextChannel) else None

def _emb(title: str, desc: str = "", color: int = 0x5865F2) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.now(timezone.utc)
    return e

async def _send_log(guild: discord.Guild, embed: discord.Embed):
    ch = _log_chan(guild)
    if ch:
        await ch.send(embed=embed)

def _voice_arrow(before: Optional[discord.VoiceChannel], after: Optional[discord.VoiceChannel]) -> str:
    if before and after and before.id != after.id:
        return f"{before.mention} → {after.mention}"
    if after and not before:
        return f"加入 {after.mention}"
    if before and not after:
        return f"離開 {before.mention}"
    return "（狀態未變）"

# ---------- Temp VC（臨時語音房） ----------
def user_can_run_tempvc(inter: discord.Interaction) -> bool:
    """擁有 VERIFIED_ROLE_ID，或管理員/可管頻道者，可用 temp VC 指令。"""
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == VERIFIED_ROLE_ID for r in m.roles)

def _is_temp_vc_id(cid: int) -> bool:
    return cid in TEMP_VC_IDS

async def _maybe_log(guild: discord.Guild, text: str):
    print(text)

async def _schedule_delete_if_empty(channel: discord.VoiceChannel):
    """如語音房無人，安排在 TEMP_VC_EMPTY_SECONDS 後刪除；有人就取消。"""
    async def _task():
        try:
            await asyncio.sleep(TEMP_VC_EMPTY_SECONDS)
            if len(channel.members) == 0 and _is_temp_vc_id(channel.id):
                await _maybe_log(channel.guild, f"🧹 自動刪除空房：#{channel.name}（id={channel.id}）")
                TEMP_VC_IDS.discard(channel.id)
                await channel.delete(reason="Temp VC idle timeout")
        finally:
            _PENDING_DELETE_TASKS.pop(channel.id, None)

    old = _PENDING_DELETE_TASKS.pop(channel.id, None)
    if old and not old.done():
        old.cancel()
    if len(channel.members) == 0:
        _PENDING_DELETE_TASKS[channel.id] = asyncio.create_task(_task())

def _cancel_delete_task(channel_id: int):
    task = _PENDING_DELETE_TASKS.pop(channel_id, None)
    if task and not task.done():
        task.cancel()

# ===== Slash: /vc_new =====
@bot.tree.command(name="vc_new", description="建立一個臨時語音房（空房 120 秒自動刪除）")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(
    name="語音房名稱（可選）",
    limit="人數上限（可選；不填＝無限制）"
)
@app_commands.check(user_can_run_tempvc)
async def vc_new(inter: discord.Interaction, name: Optional[str] = None, limit: Optional[int] = None):
    if not inter.guild:
        return await inter.response.send_message("只可在伺服器使用。", ephemeral=True)

    category: Optional[discord.CategoryChannel] = _category_from_ctx_channel(inter.channel)
    vc_name = f"{TEMP_VC_PREFIX}{(name or '臨時語音').strip()}"

    await inter.response.defer(ephemeral=False)

    max_bitrate = inter.guild.bitrate_limit  # bps
    kwargs: Dict[str, object] = {"bitrate": max_bitrate}
    if limit is not None:
        limit = max(1, min(99, int(limit)))
        kwargs["user_limit"] = limit

    ch = await inter.guild.create_voice_channel(
        vc_name, category=category, reason="Create temp VC (bartender)", **kwargs
    )
    TEMP_VC_IDS.add(ch.id)

    await _maybe_log(inter.guild, f"✅ 建立 Temp VC：#{ch.name}（id={ch.id}）於 {category.name if category else '根目錄'}")
    await _schedule_delete_if_empty(ch)

    msg = (
        f"你好 {inter.user.mention} ，✅ 房間已經安排好 → {ch.mention}\n"
        f"（bitrate={ch.bitrate // 1000}kbps, limit={ch.user_limit or '無限制'}）"
    )
    await inter.followup.send(msg)

# ===== Slash: /vc_teardown =====
@bot.tree.command(name="vc_teardown", description="刪除由 Bot 建立的臨時語音房")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(channel="要刪嘅語音房（可選；唔填就刪你而家身處的 VC）")
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
    _cancel_delete_task(target.id)
    await _maybe_log(inter.guild, f"🗑️️  手動刪除 Temp VC：#{target.name}（id={target.id}）")
    await target.delete(reason="Manual teardown temp VC")
    await inter.followup.send("✅ 已刪除。", ephemeral=True)

# ---- Voice Events（Logging + Temp VC 清房）----
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # Logging：join / leave / move
    if before.channel != after.channel:
        if not before.channel and after.channel:
            await _send_log(member.guild, _emb("Voice Join", f"🎤 {member.mention} {_voice_arrow(before.channel, after.channel)}", 0x57F287))
        elif before.channel and not after.channel:
            await _send_log(member.guild, _emb("Voice Leave", f"🔇 {member.mention} {_voice_arrow(before.channel, after.channel)}", 0xED4245))
        else:
            await _send_log(member.guild, _emb("Voice Move", f"🔀 {member.mention} {_voice_arrow(before.channel, after.channel)}", 0x5865F2))

    # Temp VC 清房邏輯
    if before.channel and _is_temp_vc_id(before.channel.id):
        await _schedule_delete_if_empty(before.channel)
    if after.channel and _is_temp_vc_id(after.channel.id):
        _cancel_delete_task(after.channel.id)

# ---------- Slash：duplicate ----------
@bot.tree.command(name="duplicate", description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
@app_commands.check(lambda inter: user_is_section_admin(inter))
async def duplicate_cmd(inter: discord.Interaction, gamename: str):
    if inter.guild_id != GUILD_ID:
        return await inter.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)

    await inter.response.defer(ephemeral=True)
    try:
        msg = await duplicate_section(inter.client, inter.guild, gamename)
        await inter.followup.send(f"✅ {msg}", ephemeral=True)
    except Exception as e:
        await inter.followup.send(f"❌ 出錯：{e}", ephemeral=True)

# ---------- Slash：ping ----------
@bot.tree.command(name="ping", description="Bot 反應時間")
@app_commands.guilds(TARGET_GUILD)
async def ping_cmd(inter: discord.Interaction):
    await inter.response.send_message(f"Pong! 🏓 {round(bot.latency * 1000)}ms", ephemeral=True)

# ---------- Slash：tu（隨機分隊） ----------
def user_can_run_tu(inter: discord.Interaction) -> bool:
    """擁有 VERIFIED_ROLE_ID，或管理員/可管頻道者，可用 /tu。"""
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    perms = m.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    return any(r.id == VERIFIED_ROLE_ID for r in m.roles)

@bot.tree.command(name="tu", description="隨機將 @人 分成兩隊")
@app_commands.guilds(TARGET_GUILD)
@app_commands.describe(members="請 @ 想參與分隊的所有人")
@app_commands.check(user_can_run_tu)
async def tu_cmd(inter: discord.Interaction, members: str):
    await inter.response.defer(ephemeral=False)  # 分隊結果要公開比大家睇

    mentions = inter.user.mention + " " + members  # 包埋發指令嗰個人
    user_ids = [word for word in mentions.split() if word.startswith("<@")]

    if len(user_ids) < 2:
        return await inter.followup.send("⚠️ 請至少 @ 兩位參加者！", ephemeral=True)

    random.shuffle(user_ids)
    mid = len(user_ids) // 2
    team_a = user_ids[:mid]
    team_b = user_ids[mid:]

    result = (
        "🎮 **分隊結果**：\n\n"
        "🔴 **Team A**\n" + "\n".join(team_a) + "\n\n"
        "🔵 **Team B**\n" + "\n".join(team_b)
    )
    await inter.followup.send(result)

# ---- Member Events ----
def _role_mention_safe(role: discord.Role) -> str:
    try:
        return role.mention
    except Exception:
        return f"@{getattr(role, 'name', '（未知角色）')}"

@bot.event
async def on_member_join(member: discord.Member):
    """新成員加入伺服器時發送歡迎訊息 + 記錄 log"""
    # 歡迎訊息
    try:
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if channel and isinstance(channel, discord.TextChannel):
            rules_ch = member.guild.get_channel(RULES_CHANNEL_ID)
            guide_ch = member.guild.get_channel(GUIDE_CHANNEL_ID)
            support_ch = member.guild.get_channel(SUPPORT_CHANNEL_ID)

            msg = (
                f"🎉 歡迎 {member.mention} 加入 **{member.guild.name}**！\n\n"
                f"📜 請先細心閱讀 {rules_ch.mention if isinstance(rules_ch, discord.TextChannel) else '#rules'}\n"
                f"📝 組別分派會根據你揀嘅答案，如需更改請查看 {guide_ch.mention if isinstance(guide_ch, discord.TextChannel) else '#教學'}\n"
                f"💬 如果有任何疑問，請到 {support_ch.mention if isinstance(support_ch, discord.TextChannel) else '#支援'} 講聲 **hi**，會有專人協助你。\n\n"
                f"最後 🙌 喺呢度同大家打一聲招呼啦！\n👉 你想我哋點稱呼你？"
            )
            await channel.send(msg)
                except Exception:
                    # 歡迎訊息出錯唔好影響 logging
                    pass

    # Logging
    await _send_log(member.guild, _emb("Member Join", f"👋 {member.mention} 加入伺服器。", 0x57F287))
    
@bot.event
async def on_member_remove(member: discord.Member):
    await _send_log(member.guild, _emb("Member Leave", f"👋 {member.mention} 離開伺服器。", 0xED4245))

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # 暱稱變更
    if before.nick != after.nick:
        desc = (
            f"🪪 {after.mention} 暱稱變更：\n"
            f"**Before**：{before.nick or '（無）'}\n"
            f"**After**：{after.nick or '（無）'}"
        )
        await _send_log(after.guild, _emb("Nickname Change", desc, 0x5865F2))

    # 角色增減（兩邊都 clickable，如 cache 仍在）
    before_ids = {r.id for r in before.roles}
    after_ids  = {r.id for r in after.roles}

    added_roles   = [r for r in after.roles  if r.id not in before_ids and r.name != "@everyone"]
    removed_roles = [r for r in before.roles if r.id not in after_ids  and r.name != "@everyone"]

    if added_roles:
        txt = "➕ " + after.mention + " 新增角色： " + ", ".join(_role_mention_safe(r) for r in added_roles)
        await _send_log(after.guild, _emb("Member Role Add", txt, 0x57F287))

    if removed_roles:
        # 多數情況 cache 仍在 → 仍可 mention；如不可則 fallback 名稱
        txt = "➖ " + after.mention + " 移除角色： " + ", ".join(_role_mention_safe(r) for r in removed_roles)
        await _send_log(after.guild, _emb("Member Role Remove", txt, 0xED4245))

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await _send_log(guild, _emb("Member Ban", f"🔨 封鎖：{user.mention}", 0xED4245))

@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    await _send_log(guild, _emb("Member Unban", f"🕊️ 解除封鎖：{user.mention}", 0x57F287))

# ---- Message Events ----
@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild:
        return
    if getattr(message, "author", None) and getattr(message.author, "mention", None):
        author_mention = message.author.mention
    elif getattr(message, "author", None) and getattr(message.author, "id", None):
        author_mention = f"<@{message.author.id}>"
    else:
        author_mention = "（未知成員）"
    content = message.content or "（無文字，可能只有附件 / 嵌入）"
    if len(content) > 500:
        content = content[:497] + "…"
    attach_text = ""
    if message.attachments:
        attach_text = "\n附件：" + ", ".join(a.filename for a in message.attachments)
    desc = f"🧹 {author_mention} 的訊息被刪除於 {message.channel.mention}\n內容：{content}{attach_text}"
    emb = _emb("Message Delete", desc, 0xED4245)
    emb.set_footer(text=f"Author ID: {getattr(message.author, 'id', '未知')} • Message ID: {message.id}")
    await _send_log(message.guild, emb)

@bot.event
async def on_bulk_message_delete(messages: List[discord.Message]):
    if not messages:
        return
    g = messages[0].guild
    if not g:
        return
    await _send_log(g, _emb("Bulk Message Delete", f"一次刪除了 **{len(messages)}** 則訊息。", 0xED4245))

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot:
        return
    if before.content == after.content:
        return
    b = before.content or "（空）"
    a = after.content or "（空）"
    desc = (
        f"✏️ {before.author.mention if hasattr(before.author,'mention') else str(before.author)} "
        f"在 {before.channel.mention} 編輯了訊息：\n"
        f"**Before**：{b[:900]}\n**After**：{a[:900]}"
    )
    await _send_log(before.guild, _emb("Message Edit", desc, 0xFEE75C))

# ---- Role Events ----
@bot.event
async def on_guild_role_create(role: discord.Role):
    await _send_log(role.guild, _emb("Role Create", f"🎭 建立角色：{role.mention}", 0x57F287))

@bot.event
async def on_guild_role_delete(role: discord.Role):
    await _send_log(role.guild, _emb("Role Delete", f"🗑️ 刪除角色：**{role.name}**", 0xED4245))

@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    if before.name != after.name:
        await _send_log(after.guild, _emb("Role Update", f"✏️ 角色改名：**{before.name}** → **{after.name}**", 0xFEE75C))

# ---- Channel Events ----
@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    mention = channel.mention if hasattr(channel, "mention") else f"#{channel.name}"
    await _send_log(channel.guild, _emb("Channel Create", f"📦 建立：{mention}", 0x57F287))

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await _send_log(channel.guild, _emb("Channel Delete", f"🗑️ 刪除：**#{channel.name}**", 0xED4245))

@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name != after.name:
        await _send_log(after.guild, _emb("Channel Update", f"✏️ 頻道改名：**#{before.name}** → **#{after.name}**", 0xFEE75C))

# ---- Emoji Events ----
@bot.event
async def on_guild_emojis_update(guild: discord.Guild, before: List[discord.Emoji], after: List[discord.Emoji]):
    bmap = {e.id: e for e in before}
    amap = {e.id: e for e in after}
    created = [e for e in after if e.id not in bmap]
    deleted = [e for e in before if e.id not in amap]
    renamed = [(bmap[i], amap[i]) for i in set(bmap).intersection(amap) if bmap[i].name != amap[i].name]
    if created:
        await _send_log(guild, _emb("Emoji Create", "😀 新增：" + ", ".join(e.name for e in created), 0x57F287))
    if deleted:
        await _send_log(guild, _emb("Emoji Delete", "🫥 刪除：" + ", ".join(e.name for e in deleted), 0xED4245))
    for bef, aft in renamed:
        await _send_log(guild, _emb("Emoji Rename", f"✏️ **{bef.name}** → **{aft.name}**", 0xFEE75C))

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
    if not TOKEN:
        raise SystemExit("❌ 沒有 DISCORD_BOT_TOKEN 環境變數")
    bot.run(TOKEN)
