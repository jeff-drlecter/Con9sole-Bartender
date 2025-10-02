# cogs/role.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional

import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)

HELPER_ROLE_ID = 1279071042249162856   # 你的 Helper role ID
MOD_ROLE_ID    = 626379227473903632    # 你的 Mod role ID（內含 Admin 權限的那個）

# ---------- Helpers ----------
def _bot_member(guild: discord.Guild, bot: commands.Bot) -> Optional[discord.Member]:
    """取回 Bot 在該 guild 的 Member。"""
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
    """Bot 要有 Manage Roles，且其最高角色層級要高於目標角色；不可動 @everyone。"""
    me = _bot_member(guild, bot)
    if me is None or not me.guild_permissions.manage_roles:
        return False
    if role.is_default() or role >= me.top_role:
        return False
    return True

def bot_can_edit_member(bot: commands.Bot, guild: discord.Guild, member: discord.Member) -> bool:
    """Bot 不能改動伺服器擁有者，亦不能改動層級 >= 自己最高角色的成員。"""
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
    """
    回傳最多 25 個 Bot 真的有能力管理的角色（排除 @everyone）。
    不再因為未選 member 而隱藏 MOD_ROLE；真正限制留待指令執行時判斷。
    """
    guild = inter.guild
    if guild is None:
        return []

    bot = inter.client
    if not isinstance(bot, commands.Bot):
        return []

    me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    if me is None:
        return []

    q = (current or "").lower()

    candidates = [
        r for r in guild.roles
        if not r.is_default()
        and r < me.top_role
        and (q in r.name.lower() if q else True)
    ]

    # 將 MOD_ROLE（如可管理）置前，方便 Helper 搜尋
    mod_role = guild.get_role(MOD_ROLE_ID)
    if mod_role and mod_role in candidates:
        try:
            candidates.remove(mod_role)
            candidates.insert(0, mod_role)
        except ValueError:
            pass

    # 由高到低
    candidates.sort(key=lambda rr: rr.position, reverse=True)

    return [app_commands.Choice(name=r.name, value=str(r.id)) for r in candidates[:25]]

class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Add Role ----------
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
            await inter.response.send_message("❌ 你無權限用呢個指令。", ephemeral=True)
            return

        guild = inter.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            await inter.response.send_message("❌ 找不到該角色，請重新選擇。", ephemeral=True)
            return

        # 安全：Helper（非 Admin）只能把 MOD_ROLE 畀「自己」
        if isinstance(inter.user, discord.Member):
            is_admin = inter.user.guild_permissions.administrator
            if (not is_admin) and user_is_helper(inter.user):
                if role.id == MOD_ROLE_ID and member != inter.user:
                    await inter.response.send_message("⛔ 你只可以把 @Mod 角色畀自己。", ephemeral=True)
                    return

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

    # ---------- Remove Role ----------
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

        # 安全：Helper（非 Admin）只能對「自己」移除 MOD_ROLE
        if isinstance(inter.user, discord.Member):
            is_admin = inter.user.guild_permissions.administrator
            if (not is_admin) and user_is_helper(inter.user):
                if role.id == MOD_ROLE_ID and member != inter.user:
                    await inter.response.send_message("⛔ 你只可以對自己移除 @Mod 角色。", ephemeral=True)
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

    # ---------- List Roles ----------
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="role_list", description="查看某位成員擁有哪些角色")
    @app_commands.describe(member="要查看的成員")
    async def role_list(
        self,
        inter: discord.Interaction,
        member: discord.Member,
    ):
        if inter.guild is None:
            await inter.response.send_message("⚠️ 呢個指令只可以喺伺服器內使用。", ephemeral=True)
            return

        if not user_is_admin_or_helper(inter):
            await inter.response.send_message("❌ 你無權限用呢個指令。", ephemeral=True)
            return

        roles = [r for r in member.roles if not r.is_default()]
        if not roles:
            await inter.response.send_message(f"ℹ️ {member.mention} 沒有任何自訂角色。", ephemeral=True)
            return

        # 由高到低
        roles.sort(key=lambda rr: rr.position, reverse=True)

        lines = [f"{r.mention}  (ID: `{r.id}`)" for r in roles]
        # 最長訊息保險處理
        desc = "\n".join(lines)
        if len(desc) > 3800:  # 以防萬一太長，切片
            chunks = []
            chunk = []
            count = 0
            for line in lines:
                if count + len(line) + 1 > 3800:
                    chunks.append("\n".join(chunk)); chunk = []; count = 0
                chunk.append(line); count += len(line) + 1
            if chunk:
                chunks.append("\n".join(chunk))
            # 逐段發送
            await inter.response.send_message(
                f"**{member} 的角色（高→低）**：\n```共有 {len(roles)} 個角色```",
                ephemeral=True
            )
            for c in chunks:
                await inter.followup.send(c, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{member} 的角色（高→低）",
            description=desc,
            color=discord.Color.blurple()
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot), guild=TARGET_GUILD)
