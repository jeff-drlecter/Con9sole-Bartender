from __future__ import annotations
from typing import Optional
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
    perms = m.guild_permissions
    # 只接受 Admin。不要再容許 manage_channels / helper 等
    return bool(perms.administrator)

# ---------- 分區複製 ----------
async def duplicate_section(client: discord.Client, guild: discord.Guild, game_name: str) -> str:
    template_cat = guild.get_channel(config.TEMPLATE_CATEGORY_ID)
    if not isinstance(template_cat, discord.CategoryChannel):
        ch = await client.fetch_channel(config.TEMPLATE_CATEGORY_ID)
        if not isinstance(ch, discord.CategoryChannel):
            raise RuntimeError(f"TEMPLATE_CATEGORY_ID 並不是 Category（而是 {type(ch).__name__}）。")
        template_cat = ch

    all_chans = await guild.fetch_channels()
    template_children = [c for c in all_chans if getattr(c, "category_id", None) == template_cat.id]
    print(f"▶️ 模板分區：#{template_cat.name}（{template_cat.id}） 子頻道：{len(template_children)}")

    # 角色
    role_name = config.ROLE_NAME_PATTERN.format(game=game_name)
    new_role = discord.utils.get(guild.roles, name=role_name)
    if not new_role:
        new_role = await guild.create_role(name=role_name, hoist=False, mentionable=True, reason="Create game role")
        print(f"✅ 已建立角色：{new_role.name}（{new_role.id}）")

    admin_roles = [guild.get_role(rid) for rid in config.ADMIN_ROLE_IDS if guild.get_role(rid)]

    # 新分區
    cat_name = config.CATEGORY_NAME_PATTERN.format(game=game_name)
    new_cat = await guild.create_category(name=cat_name, reason="Create new game section")
    await new_cat.edit(overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    print(f"✅ 已建立分區：#{new_cat.name}（{new_cat.id}）並套用私密權限。")

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

    if not created_forum and config.FALLBACK_CHANNELS.get("forum"):
        created_forum = await guild.create_forum(
            config.FALLBACK_CHANNELS["forum"], category=new_cat,
            overwrites=make_private_overwrites(guild, [new_role], admin_roles)
        )

    if created_forum:
        tag_src: Optional[discord.ForumChannel] = None
        if config.TEMPLATE_FORUM_ID:
            c = await client.fetch_channel(config.TEMPLATE_FORUM_ID)
            if isinstance(c, discord.ForumChannel):
                tag_src = c
        if not tag_src:
            tag_src = next((c for c in template_children if isinstance(c, discord.ForumChannel)), None)
        if isinstance(tag_src, discord.ForumChannel):
            await copy_forum_tags(tag_src, created_forum)

    names_in_cat = {c.name for c in await guild.fetch_channels() if getattr(c, "category_id", None) == new_cat.id}
    for tname in config.FALLBACK_CHANNELS.get("text", []):
        if tname not in names_in_cat:
            await guild.create_text_channel(tname, category=new_cat,
                                            overwrites=make_private_overwrites(guild, [new_role], admin_roles))
    for vname in config.FALLBACK_CHANNELS.get("voice", []):
        if vname not in names_in_cat:
            await guild.create_voice_channel(vname, category=new_cat,
                                             overwrites=make_private_overwrites(guild, [new_role], admin_roles))

    return f"新分區：#{new_cat.name}；新角色：{new_role.name}"

class Duplicate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # 只有 Admin 會見到：default_permissions
    @app_commands.command(
        name="duplicate",
        description="複製模板分區，建立新遊戲分區（含 Forum/Stage/Tags）"
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
