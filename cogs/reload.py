# cogs/role.py
import asyncio
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

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
async def role_autocomplete(inter: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """回傳最多 25 個 Bot 真的有能力管理的角色（排除 @everyone）。"""
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
        if (not r.is_default())
        and (r < me.top_role)
        and (q in r.name.lower() if q else True)
    ]

    # 將 MOD_ROLE（如可管理）置前，方便 Helper 搜尋
    mod_role = guild.get_role(MOD_ROLE_ID)
    if mod_role and mod_role in candidates:
        candidates.remove(mod_role)
        candidates.insert(0, mod_role)

    candidates.sort(key=lambda rr: rr.position, reverse=True)
    return [app_commands.Choice(name=r.name, value=str(r.id)) for r in candidates[:25]]


class RoleManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Grant Role (single user OR role-bulk) ----------
    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="role_grant", description="對單一用戶或指定角色的所有成員加上某個角色")
    @app_commands.describe(
        target_member="（二選一）目標成員",
        target_role="（二選一）目標角色：會對所有擁有此角色的成員批量加角色",
        grant_role_id="要加嘅角色（可用自動完成）",
        include_bots="是否包含機械人（預設否）",
    )
    @app_commands.autocomplete(grant_role_id=role_autocomplete)
    async def role_grant(
        self,
        inter: discord.Interaction,
        grant_role_id: str,
        target_member: Optional[discord.Member] = None,
        target_role: Optional[discord.Role] = None,
        include_bots: bool = False,
    ):
        await self._apply_role_change(
            inter,
            role_id=grant_role_id,
            target_member=target_member,
            target_role=target_role,
            include_bots=include_bots,
            mode="add",
        )

    # ---------- Revoke Role (single user OR role-bulk) ----------
    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="role_revoke", description="對單一用戶或指定角色的所有成員移除某個角色")
    @app_commands.describe(
        target_member="（二選一）目標成員",
        target_role="（二選一）目標角色：會對所有擁有此角色的成員批量移除角色",
        revoke_role_id="要移除嘅角色（可用自動完成）",
        include_bots="是否包含機械人（預設否）",
    )
    @app_commands.autocomplete(revoke_role_id=role_autocomplete)
    async def role_revoke(
        self,
        inter: discord.Interaction,
        revoke_role_id: str,
        target_member: Optional[discord.Member] = None,
        target_role: Optional[discord.Role] = None,
        include_bots: bool = False,
    ):
        await self._apply_role_change(
            inter,
            role_id=revoke_role_id,
            target_member=target_member,
            target_role=target_role,
            include_bots=include_bots,
            mode="remove",
        )

    async def _apply_role_change(
        self,
        inter: discord.Interaction,
        role_id: str,
        target_member: Optional[discord.Member],
        target_role: Optional[discord.Role],
        include_bots: bool,
        mode: str,
    ):
        if inter.guild is None:
            await inter.response.send_message("⚠️ 呢個指令只可以喺伺服器內使用。", ephemeral=True)
            return

        # 必須二選一
        if (target_member is None and target_role is None) or (target_member is not None and target_role is not None):
            await inter.response.send_message(
                "❌ 請只填其中一個：target_member 或 target_role（不可同時填）。",
                ephemeral=True,
            )
            return

        guild = inter.guild
        role = guild.get_role(int(role_id)) if role_id.isdigit() else None
        if role is None:
            await inter.response.send_message("❌ 找不到指定角色，請重新選擇。", ephemeral=True)
            return

        # Helper（非 Admin）限制：只能對自己加/移除 MOD_ROLE
        if isinstance(inter.user, discord.Member):
            is_admin = inter.user.guild_permissions.administrator
            if (not is_admin) and user_is_helper(inter.user) and role.id == MOD_ROLE_ID:
                if target_member is None or target_member != inter.user:
                    await inter.response.send_message("⛔ 你只可以對自己處理 @Mod 角色。", ephemeral=True)
                    return

        if not bot_can_manage_role(self.bot, guild, role):
            await inter.response.send_message("❌ 我冇權限或角色層級不足以處理呢個角色。", ephemeral=True)
            return

        # --------- Single member ---------
        if target_member is not None:
            member = target_member
            if not bot_can_edit_member(self.bot, guild, member):
                await inter.response.send_message("❌ 我唔可以修改呢位成員嘅角色（層級或身分限制）。", ephemeral=True)
                return

            try:
                if mode == "add":
                    if role in member.roles:
                        await inter.response.send_message("ℹ️ 佢已經有呢個角色。", ephemeral=True)
                        return
                    await member.add_roles(role, reason=f"/role_grant by {inter.user}")
                    await inter.response.send_message(f"✅ 已幫 {member.mention} 加上 {role.mention}。", ephemeral=True)
                else:
                    if role not in member.roles:
                        await inter.response.send_message("ℹ️ 佢本身都無呢個角色。", ephemeral=True)
                        return
                    await member.remove_roles(role, reason=f"/role_revoke by {inter.user}")
                    await inter.response.send_message(f"✅ 已幫 {member.mention} 移除 {role.mention}。", ephemeral=True)
            except discord.Forbidden:
                await inter.response.send_message("❌ 我無權限處理呢個角色。", ephemeral=True)
            except Exception as e:
                await inter.response.send_message(f"⚠️ 出錯：{e}", ephemeral=True)
            return

        # --------- Bulk by target_role ---------
        assert target_role is not None
        await inter.response.defer(ephemeral=True)

        members = [m for m in guild.members if target_role in m.roles]
        if not include_bots:
            members = [m for m in members if not m.bot]

        if not members:
            await inter.followup.send("ℹ️ 找不到任何符合條件的成員。", ephemeral=True)
            return

        changed = 0
        skipped_have = 0
        skipped_cant = 0
        failed = 0

        for idx, m in enumerate(members, start=1):
            if not bot_can_edit_member(self.bot, guild, m):
                skipped_cant += 1
                continue

            try:
                if mode == "add":
                    if role in m.roles:
                        skipped_have += 1
                    else:
                        await m.add_roles(role, reason=f"/role_grant bulk by {inter.user} from {target_role.name}")
                        changed += 1
                else:
                    if role not in m.roles:
                        skipped_have += 1
                    else:
                        await m.remove_roles(role, reason=f"/role_revoke bulk by {inter.user} from {target_role.name}")
                        changed += 1
            except discord.Forbidden:
                skipped_cant += 1
            except Exception:
                failed += 1

            await asyncio.sleep(0.2)

            if idx % 25 == 0:
                await inter.followup.send(
                    f"⏳ 進度：{idx}/{len(members)} | ✅處理 {changed} | ↩️略過 {skipped_have} | ⛔跳過 {skipped_cant} | ⚠️失敗 {failed}",
                    ephemeral=True,
                )

        await inter.followup.send(
            "✅ 批量完成\n"
            f"目標：擁有 `{target_role.name}` 的成員（共 {len(members)} 人）\n"
            f"處理：{changed} | 略過：{skipped_have} | 跳過：{skipped_cant} | 失敗：{failed}",
            ephemeral=True,
        )

    # ---------- List Roles ----------
    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="role_list", description="查看某位成員擁有哪些角色")
    @app_commands.describe(member="要查看的成員")
    async def role_list(self, inter: discord.Interaction, member: discord.Member):
        if inter.guild is None:
            await inter.response.send_message("⚠️ 呢個指令只可以喺伺服器內使用。", ephemeral=True)
            return

        roles = [r for r in member.roles if not r.is_default()]
        if not roles:
            await inter.response.send_message(f"ℹ️ {member.mention} 沒有任何自訂角色。", ephemeral=True)
            return

        roles.sort(key=lambda rr: rr.position, reverse=True)
        lines = [f"{r.mention}  (ID: `{r.id}`)" for r in roles]

        desc = "\n".join(lines)
        if len(desc) > 3800:
            # 避免超過 embed 限制
            chunks: List[str] = []
            chunk: List[str] = []
            count = 0
            for line in lines:
                if count + len(line) + 1 > 3800:
                    chunks.append("\n".join(chunk))
                    chunk = []
                    count = 0
                chunk.append(line)
                count += len(line) + 1
            if chunk:
                chunks.append("\n".join(chunk))

            await inter.response.send_message(
                f"**{member} 的角色（高→低）**：\n```共有 {len(roles)} 個角色```",
                ephemeral=True,
            )
            for c in chunks:
                await inter.followup.send(c, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{member} 的角色（高→低）",
            description=desc,
            color=discord.Color.blurple(),
        )
        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleManager(bot), guild=TARGET_GUILD)
