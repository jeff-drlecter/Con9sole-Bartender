# cogs/role.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional

import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)
HELPER_ROLE_ID = 1279071042249162856   # Helper role ID
MOD_ROLE_ID = 123456789012345678       # <<< 改成你實際的 mod role ID

# ---------- Helpers ----------
def _bot_member(guild: discord.Guild, bot: commands.Bot) -> Optional[discord.Member]:
    me = guild.me
    if me is None and bot.user:
        me = guild.get_member(bot.user.id)
    return me

def user_is_helper(member: discord.Member) -> bool:
    return any(r.id == HELPER_ROLE_ID for r in member.roles)

def user_is_admin_or_helper(inter: discord.Interaction) -> bool:
    if inter.guild is None or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    return m.guild_permissions.administrator or user_is_helper(m)

def bot_can_manage_role(bot: commands.Bot, guild: discord.Guild, role: discord.Role) -> bool:
    me = _bot_member(guild, bot)
    if me is None or not me.guild_permissions.manage_roles:
        return False
    if role.is_default() or role >= me.top_role:
        return False
    return True

def bot_can_edit_member(bot: commands.Bot, guild: discord.Guild, member: discord.Member) -> bool:
    me = _bot_member(guild, bot)
    if me is None:
        return False
    if member == guild.owner or member.top_role >= me.top_role:
        return False
    return True

# ---------- 角色 Autocomplete ----------
async def role_autocomplete(
    inter: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    guild = inter.guild
    if guild is None:
        return []

    bot = inter.client
    if not isinstance(bot, commands.Bot):
        return []

    me = _bot_member(guild, bot)
    if me is None:
        return []

    # 已填入的 member（用來限制 Helper 只可對自己揀到 mod）
    target_member: Optional[discord.Member] = None
    try:
        # Discord.py 2.x：已填的 options 會落在 namespace
        target_member = getattr(inter.namespace, "member", None)
    except Exception:
        pass

    # 基本候選（機械人可管理，且名稱包含 current）
    q = (current or "").lower()
    candidates = [
        r for r in guild.roles
        if not r.is_default() and r < me.top_role
           and (q in r.name.lower() if q else True)
    ]

    # 如果用家係「Helper 但非 Admin」→ 只在「目標成員 == 自己」時先顯示 MOD_ROLE
    if isinstance(inter.user, discord.Member):
        is_admin = inter.user.guild_permissions.administrator
        is_helper_only = (not is_admin) and user_is_helper(inter.user)
        if is_helper_only:
            if target_member is None or target_member != inter.user:
                # 隱藏 MOD_ROLE
                candidates = [r for r in candidates if r.id != MOD_ROLE_ID]

    # 排序：高層級在前
    candidates.sort(key=lambda rr: rr.position, reverse=True)

    return [app_commands.Choice(name=r.name, value=str(r.id)) for r in candidates[:25]]

class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # 只限 Guild，並預設只 Admin 可見/可用（普通用戶唔會見到）
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="role_add", description="幫成員加上某個角色")
    @app_commands.describe(member="要加角色嘅成員", role_id="要加嘅角色（可用自動完成）")
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
            # 理論上見唔到，但以防萬一
            await inter.response.send_message("❌ 你無權限用呢個指令。", ephemeral=True)
            return

        guild = inter.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            await inter.response.send_message("❌ 找不到該角色，請重新選擇。", ephemeral=True)
            return

        # 安全規則：Helper（非 Admin）只能把 MOD_ROLE 畀「自己」
        if isinstance(inter.user, discord.Member):
            is_admin = inter.user.guild_permissions.administrator
            if (not is_admin) and user_is_helper(inter.user):
                if role.id == MOD_ROLE_ID and member != inter.user:
                    await inter.response.send_message("⛔ 你只可以把 mod 角色畀自己。", ephemeral=True)
                    return
                # 如果想再嚴格啲：禁止 Helper 對其他人加任何「高過 Helper 自己最高層級」的角色
                # 可在此加多一層判斷

        if not bot_can_manage_role(self.bot, guild, role):
            await inter.response.send_message("❌ 我冇權限或角色層級不足以加上呢個角色。", ephemeral=True)
            return

        if not bot_can_edit_member(self.bot, guild, member):
            await inter.response.send_message("❌ 我唔可以修改呢位成員嘅角色（層級或身分限制）。", ephemeral=True)
            return

        if role in member.roles:
            await inter.response.send_message("ℹ️ 佢已經有呢個角色。", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"/role_add by {inter.user}")
            await inter.response.send_message(f"✅ 已幫 {member.mention} 加上 {role.mention}。")
        except discord.Forbidden:
            await inter.response.send_message("❌ 我無權限加呢個角色。", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"⚠️ 出錯：{e}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="role_remove", description="幫成員移除某個角色")
    @app_commands.describe(member="要移除角色嘅成員", role_id="要移除嘅角色（可用自動完成）")
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

        # 同一套安全規則（Helper 只可把 mod 從自己身上移除；對其他人處理 mod 需 Admin）
        if isinstance(inter.user, discord.Member):
            is_admin = inter.user.guild_permissions.administrator
            if (not is_admin) and user_is_helper(inter.user):
                if role.id == MOD_ROLE_ID and member != inter.user:
                    await inter.response.send_message("⛔ 你只可以對自己移除 mod 角色。", ephemeral=True)
                    return

        if not bot_can_manage_role(self.bot, guild, role):
            await inter.response.send_message("❌ 我冇權限或角色層級不足以移除呢個角色。", ephemeral=True)
            return

        if not bot_can_edit_member(self.bot, guild, member):
            await inter.response.send_message("❌ 我唔可以修改呢位成員嘅角色（層級或身分限制）。", ephemeral=True)
            return

        if role not in member.roles:
            await inter.response.send_message("ℹ️ 佢本身都無呢個角色。", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason=f"/role_remove by {inter.user}")
            await inter.response.send_message(f"✅ 已幫 {member.mention} 移除 {role.mention}。")
        except discord.Forbidden:
            await inter.response.send_message("❌ 我無權限移除呢個角色。", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"⚠️ 出錯：{e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot), guild=TARGET_GUILD)
