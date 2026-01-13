from __future__ import annotations

from typing import Optional, Dict, Any, List

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import make_private_overwrites, copy_forum_tags


# ---------- 權限（只容許 Admin） ----------

def user_is_section_admin(inter: discord.Interaction) -> bool:
    if not inter.user or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    return bool(m.guild_permissions.administrator)


# ---------- Helpers ----------

async def _get_template_category(client: discord.Client, guild: discord.Guild) -> discord.CategoryChannel:
    template_cat = guild.get_channel(config.TEMPLATE_CATEGORY_ID)
    if isinstance(template_cat, discord.CategoryChannel):
        return template_cat

    ch = await client.fetch_channel(config.TEMPLATE_CATEGORY_ID)
    if not isinstance(ch, discord.CategoryChannel):
        raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（而是 {type(ch).__name__}）。")
    return ch


def _admin_roles(guild: discord.Guild) -> List[discord.Role]:
    return [guild.get_role(rid) for rid in config.ADMIN_ROLE_IDS if guild.get_role(rid)]


def _safe_get(obj: object, attr: str, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _build_text_kwargs(src: discord.TextChannel) -> Dict[str, Any]:
    # 只複製「設定」，唔複製權限（權限由 make_private_overwrites 決定）
    kwargs: Dict[str, Any] = {}
    topic = _safe_get(src, "topic")
    if topic is not None:
        kwargs["topic"] = topic

    nsfw = _safe_get(src, "nsfw")
    if nsfw is not None:
        kwargs["nsfw"] = nsfw

    slowmode = _safe_get(src, "rate_limit_per_user")
    if slowmode is not None:
        kwargs["rate_limit_per_user"] = slowmode

    # default_auto_archive_duration 可能視版本而定
    da = _safe_get(src, "default_auto_archive_duration")
    if da is not None:
        kwargs["default_auto_archive_duration"] = da

    return kwargs


def _build_voice_kwargs(src: discord.VoiceChannel) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    bitrate = _safe_get(src, "bitrate")
    if bitrate is not None:
        kwargs["bitrate"] = bitrate

    user_limit = _safe_get(src, "user_limit")
    if user_limit is not None:
        kwargs["user_limit"] = user_limit

    rtc_region = _safe_get(src, "rtc_region")
    if rtc_region is not None:
        kwargs["rtc_region"] = rtc_region

    # video_quality_mode 可能視版本而定
    vqm = _safe_get(src, "video_quality_mode")
    if vqm is not None:
        kwargs["video_quality_mode"] = vqm

    return kwargs


def _build_stage_kwargs(src: discord.StageChannel) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    rtc_region = _safe_get(src, "rtc_region")
    if rtc_region is not None:
        kwargs["rtc_region"] = rtc_region

    topic = _safe_get(src, "topic")
    if topic is not None:
        kwargs["topic"] = topic

    return kwargs


def _build_forum_kwargs(src: discord.ForumChannel) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}

    topic = _safe_get(src, "topic")
    if topic is not None:
        kwargs["topic"] = topic

    nsfw = _safe_get(src, "nsfw")
    if nsfw is not None:
        kwargs["nsfw"] = nsfw

    slowmode = _safe_get(src, "rate_limit_per_user")
    if slowmode is not None:
        kwargs["rate_limit_per_user"] = slowmode

    # Forum defaults（視版本/權限而定）
    default_sort_order = _safe_get(src, "default_sort_order")
    if default_sort_order is not None:
        kwargs["default_sort_order"] = default_sort_order

    default_layout = _safe_get(src, "default_layout")
    if default_layout is not None:
        kwargs["default_layout"] = default_layout

    # default_reaction_emoji 是 PartialEmoji / str / None
    dre = _safe_get(src, "default_reaction_emoji")
    if dre is not None:
        kwargs["default_reaction_emoji"] = dre

    dtrl = _safe_get(src, "default_thread_rate_limit_per_user")
    if dtrl is not None:
        kwargs["default_thread_rate_limit_per_user"] = dtrl

    da = _safe_get(src, "default_auto_archive_duration")
    if da is not None:
        kwargs["default_auto_archive_duration"] = da

    return kwargs


# ---------- 分區複製（完全跟 template 結構；權限改為 game role + admin 私密） ----------

async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    # 1) 取得 template category（最新一刻）
    template_cat = await _get_template_category(client, guild)

    # 2) 讀取 template 子頻道（最新一刻）
    all_chans = await guild.fetch_channels()
    template_children = [
        c for c in all_chans
        if getattr(c, "category_id", None) == template_cat.id
        and isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel))
    ]
    template_children.sort(key=lambda c: getattr(c, "position", 0))

    print(
        f"▶️ 模板分區：#{template_cat.name}（{template_cat.id}） 子頻道：{len(template_children)}"
    )

    # 3) 建立（或重用）遊戲 role
    role_name = config.ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(
            name=role_name,
            hoist=False,
            mentionable=True,
            reason="Create game role",
        )
        print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")

    admins = _admin_roles(guild)

    # 4) 建立新 category（命名沿用既有 pattern）
    cat_name = config.CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")

    # 5) 權限：每個分區依然私密，只放 game role + admin
    # （不 clone template permissions；但會 clone 其他設定到 channel level）
    private_overwrites = make_private_overwrites(guild, [new_role], admins)
    await new_cat.edit(overwrites=private_overwrites)

    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

    created_forum: Optional[discord.ForumChannel] = None

    # 6) 逐個複製 template channels（Forum/Text/Voice/Stage），名稱/順序跟足 template
    for ch in template_children:
        ow = private_overwrites

        if isinstance(ch, discord.TextChannel):
            kwargs = _build_text_kwargs(ch)
            created = await guild.create_text_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            # position
            try:
                await created.edit(position=ch.position)
            except Exception:
                pass

        elif isinstance(ch, discord.VoiceChannel):
            kwargs = _build_voice_kwargs(ch)
            created = await guild.create_voice_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            try:
                await created.edit(position=ch.position)
            except Exception:
                pass

        elif isinstance(ch, discord.StageChannel):
            kwargs = _build_stage_kwargs(ch)
            created = await guild.create_stage_channel(ch.name, category=new_cat, overwrites=ow, **kwargs)
            try:
                await created.edit(position=ch.position)
            except Exception:
                pass

        elif isinstance(ch, discord.ForumChannel):
            kwargs = _build_forum_kwargs(ch)
            created_forum = await guild.create_forum(ch.name, category=new_cat, overwrites=ow, **kwargs)
            try:
                await created_forum.edit(position=ch.position)
            except Exception:
                pass

    # 7) Forum tags：以 template 內第一個 forum 作 source（唔需要固定 TEMPLATE_FORUM_ID）
    if created_forum:
        tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            try:
                await copy_forum_tags(tag_src, created_forum)
            except Exception as e:
                print(f"⚠️ copy_forum_tags 失敗：{e}")

    # 8) （可選）Fallback channels：如果你 config.FALLBACK_CHANNELS 有設定，仍然會補齊
    # 你要「完全跟 template」的話，建議把 FALLBACK_CHANNELS 設成空。
    fallback = getattr(config, "FALLBACK_CHANNELS", {}) or {}
    if fallback:
        names_in_cat = {
            c.name
            for c in await guild.fetch_channels()
            if getattr(c, "category_id", None) == new_cat.id
        }
        for tname in fallback.get("text", []) or []:
            if tname not in names_in_cat:
                await guild.create_text_channel(tname, category=new_cat, overwrites=private_overwrites)
        for vname in fallback.get("voice", []) or []:
            if vname not in names_in_cat:
                await guild.create_voice_channel(vname, category=new_cat, overwrites=private_overwrites)
        if (not created_forum) and fallback.get("forum"):
            created_forum = await guild.create_forum(
                fallback["forum"],
                category=new_cat,
                overwrites=private_overwrites,
            )

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"


class Duplicate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="duplicate",
        description="複製模板分區（完全跟最新 Template 結構），建立新遊戲分區（私密：game role + admin）",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(gamename="新遊戲名稱（例如：Delta Force）")
    async def duplicate_cmd(self, inter: discord.Interaction, gamename: str):
        if inter.guild_id != config.GUILD_ID:
            return await inter.response.send_message("此指令只限指定伺服器使用。", ephemeral=True)
        if not user_is_section_admin(inter):
            return await inter.response.send_message("需要 Administrator 權限。", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        try:
            msg = await duplicate_section(inter.client, inter.guild, gamename)  # type: ignore[arg-type]
            await inter.followup.send(f"✅ {msg}", ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"❌ 出錯：{e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Duplicate(bot))
