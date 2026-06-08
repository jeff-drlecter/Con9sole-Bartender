from __future__ import annotations

import discord

from core.safe_send import send_or_followup
from features.menu_helpers import MENU_COLOR, can_use_admin
from features.menu_stats import record_usage_sync
from features.role_tools import RoleActionState, get_member_from_state, get_role_from_state


async def execute_role_change_from_select(interaction: discord.Interaction, *, state: RoleActionState) -> None:
    if not interaction.guild:
        await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
        return
    if not can_use_admin(interaction.user):
        await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
        return

    role_cog = interaction.client.get_cog("RoleManager")
    if role_cog is None or not hasattr(role_cog, "_apply_role_change"):
        await interaction.response.edit_message(content="❌ RoleManager cog 未載入，請先 `/reload role`。", embed=None, view=None)
        return

    apply_role = get_role_from_state(interaction.guild, state.apply_role_id)
    if apply_role is None:
        await interaction.response.edit_message(content="❌ 要處理嘅角色已不存在。", embed=None, view=None)
        return

    target_member: discord.Member | None = None
    target_role: discord.Role | None = None

    if state.target_kind == "member":
        target_member = get_member_from_state(interaction.guild, state.target_member_id)
        if target_member is None and state.target_member_id is not None:
            try:
                target_member = await interaction.guild.fetch_member(state.target_member_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target_member = None
        if target_member is None:
            await interaction.response.edit_message(content="❌ 目標成員已不存在，或 Bot 無法讀取該成員。", embed=None, view=None)
            return
    else:
        target_role = get_role_from_state(interaction.guild, state.target_role_id)
        if target_role is None:
            await interaction.response.edit_message(content="❌ 目標角色群組已不存在。", embed=None, view=None)
            return

    feature = "admin_role_grant" if state.mode == "add" else "admin_role_revoke"
    record_usage_sync(feature, interaction.user.id, interaction.guild_id)

    try:
        await role_cog._apply_role_change(  # type: ignore[attr-defined]
            interaction,
            role_id=str(apply_role.id),
            target_member=target_member,
            target_role=target_role,
            include_bots=state.include_bots,
            mode=state.mode,
        )
    except discord.InteractionResponded:
        return
    except Exception as exc:
        await send_or_followup(
            interaction,
            content=f"⚠️ Role Tools 執行失敗：`{type(exc).__name__}`：{exc}",
            ephemeral=True,
        )


async def execute_role_list_for_member(
    interaction: discord.Interaction,
    *,
    member: discord.Member,
    edit_existing: bool = True,
) -> None:
    if not interaction.guild:
        if edit_existing:
            await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
        else:
            await interaction.response.send_message("⚠️ 呢個工具只可以喺伺服器內使用。", ephemeral=True)
        return
    if not can_use_admin(interaction.user):
        if edit_existing:
            await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
        else:
            await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
        return

    roles = [role for role in member.roles if not role.is_default()]
    roles.sort(key=lambda role: role.position, reverse=True)
    record_usage_sync("admin_role_list", interaction.user.id, interaction.guild_id)

    if not roles:
        content = f"ℹ️ {member.mention} 沒有任何自訂角色。"
        if edit_existing:
            await interaction.response.edit_message(content=content, embed=None, view=None)
        else:
            await interaction.response.send_message(content, ephemeral=True)
        return

    lines = [f"{role.mention} (ID: `{role.id}`)" for role in roles]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 3800:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))

    embed = discord.Embed(
        title=f"📋 {member.display_name} 的角色（高→低）",
        description=chunks[0],
        color=MENU_COLOR,
    )
    embed.set_footer(text=f"共有 {len(roles)} 個角色")

    if edit_existing:
        await interaction.response.edit_message(content=None, embed=embed, view=None)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, ephemeral=True)
