# cogs/role.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional

import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)
HELPER_ROLE_ID = 1279071042249162856  # 你的 Helper role ID

# ---------- Helpers ----------
def _bot_member(guild: discord.Guild, bot: commands.Bot) -> Optional[discord.Member]:
    """兼容地取回機械人在此 guild 的 Member 物件。"""
    me = guild.me  # 2.x 依然可用
    if me is None and bot.user:
        me = guild.get_member(bot.user.id)
    return me

def user_is_admin_or_helper(inter: discord.Interaction) -> bool:
    """只允許 Admin 或擁有 HELPER_ROLE_ID 的成員使用。"""
    # 必須在 guild 內（Slash 本身已限制，但保險起見）
    if inter.guild is None:
        return False
    # 不是 Member（例如不正常情況）
    if not isinstance(inter.user, discord.Member):
        return False
    member: discord.Member = inter.user

    if member.guild_permissions.administrator:
        return True
    if any(r.id == HELPER_ROLE_ID for r in member.roles):
        return True
    return False

def bot_can_manage_role(bot: commands.Bot, guild: discord.Guild, role: discord.Role) -> bool:
    """
    機械人需要 Manage Roles 權限，且最高角色層級要高於目標角色；不可動 @everyone。
    """
    me = _bot_member(guild, bot)
    if me is None:
        return False
    if not me.guild_permissions.manage_roles:
        return False
    if role.is_default():
        return False
    # 角色層級必須嚴格高過對方
    if role >= me.top_role:
        return False
    return True

def bot_can_edit_member(bot: commands.Bot, guild: discord.Guild, member: discord.Member) -> bool:
    """
    機械人唔可以改動伺服器擁有者，亦唔可以改動層級 >= 自己最高角色的成員。
    """
    me = _bot_member(guild, bot)
    if me is None:
        return False
    if member == guild.owner:
        return False
    if member.top_role >= me.top_role:
        return False
    return True

# ---------- 角色 Autocomplete ----------
async def role_autocomplete(
    inter: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """
    回傳最多 25 個「機械人有能力管理」的角色，name 會顯示，value 會放 role.id（字串）。
    """
    guild = inter.guild
    if guild is None:
        return []

    # 機械人要存在於此 guild，否則不列出
    bot = inter.client  # commands.Bot
    if not isinstance(bot, commands.Bot):
        return []

    me = _bot_member(guild, bot)
    if me is None:
        return []

    q = (current or "").lower()

    # 只列出機械人層級可管理的角色，並排除 @everyone
    candidates = [
        r for r in guild.roles
        if not r.is_default() and r < me.top_role
           and (q in r.name.lower() if q else True)
    ]

    # 由高到低，易揀
    candidates.sort(key=lambda rr: rr.position, reverse=True)

    return [
        app_commands.Choice(name=r.name, value=str(r.id))
        for r in candidates[:25]
    ]

class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Add Role ----------
    @app_commands.command(name="role_add", description="幫成員加上某個角色")
    @app_commands.describe(
        member="要加角色嘅成員",
        role_id="要加嘅角色（可用自動完成選擇）"
    )
    @app_commands.autocomplete(role_id=role_autocomplete)
    async def role_add(
        self,
        inter: discord.Interaction,
        member: discord.Member,
        role_id: str,
    ):
        if inter.guild is None:
            await inter.response.send_message("⚠️ 呢個指令只可以喺伺服器內使用。", ephemeral=True)
            return

        if not user_is_admin_or_helper(inter):
            await inter.response.send_message("❌ 你無權限用呢個指令。", ephemeral=True)
            return

        guild = inter.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            await inter.response.send_message("❌ 找不到該角色，請重新選擇。", ephemeral=True)
            return

        if not bot_can_manage_role(self.bot, guild, role):
            await inter.response.send_message(
                "❌ 我冇 Manage Roles 權限、角色層級不足，或該角色不可被操作。", ephemeral=True
            )
            return

        if not bot_can_edit_member(self.bot, guild, member):
            await inter.response.send_message(
                "❌ 我唔可以修改呢位成員嘅角色（層級或身分限制）。", ephemeral=True
            )
            return

        if role in member.roles:
            await inter.response.send_message("ℹ️ 佢已經有呢個角色。", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"/role_add by {inter.user}")
            await inter.response.send_message(
                f"✅ 已幫 {member.mention} 加上 {role.mention}。"
            )
        except discord.Forbidden:
            await inter.response.send_message("❌ 我無權限加呢個角色。", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"⚠️ 出錯：{e}", ephemeral=True)

    # ---------- Remove Role ----------
    @app_commands.command(name="role_remove", description="幫成員移除某個角色")
    @app_commands.describe(
        member="要移除角色嘅成員",
        role_id="要移除嘅角色（可用自動完成選擇）"
    )
    @app_commands.autocomplete(role_id=role_autocomplete)
    async def role_remove(
        self,
        inter: discord.Interaction,
        member: discord.Member,
        role_id: str,
    ):
        if inter.guild is None:
            await inter.response.send_message("⚠️ 呢個指令只可以喺伺服器內使用。", ephemeral=True)
            return

        if not user_is_admin_or_helper(inter):
            await inter.response.send_message("❌ 你無權限用呢個指令。", ephemeral=True)
            return

        guild = inter.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            await inter.response.send_message("❌ 找不到該角色，請重新選擇。", ephemeral=True)
            return

        if not bot_can_manage_role(self.bot, guild, role):
            await inter.response.send_message(
                "❌ 我冇 Manage Roles 權限、角色層級不足，或該角色不可被操作。", ephemeral=True
            )
            return

        if not bot_can_edit_member(self.bot, guild, member):
            await inter.response.send_message(
                "❌ 我唔可以修改呢位成員嘅角色（層級或身分限制）。", ephemeral=True
            )
            return

        if role not in member.roles:
            await inter.response.send_message("ℹ️ 佢本身都無呢個角色。", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason=f"/role_remove by {inter.user}")
            await inter.response.send_message(
                f"✅ 已幫 {member.mention} 移除 {role.mention}。"
            )
        except discord.Forbidden:
            await inter.response.send_message("❌ 我無權限移除呢個角色。", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"⚠️ 出錯：{e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot), guild=TARGET_GUILD)
