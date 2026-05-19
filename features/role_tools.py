from __future__ import annotations

import re
from dataclasses import dataclass

import discord

from core.permissions import is_admin_or_helper
from core.safe_send import send_or_followup

MENU_COLOR = 0x2B2D31
ROLE_TOOLS_TIMEOUT_SECONDS = 300


def can_use_admin(member: discord.Member | discord.User) -> bool:
    return is_admin_or_helper(member)


class RoleBaseView(discord.ui.View):
    def __init__(self, cog: object, *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
        enforce = getattr(self.cog, "enforce_menu_button_cooldown", None)
        if enforce is None:
            enforce = getattr(self.cog, "_enforce_command_cooldown", None)
        if enforce is None:
            return True
        return await enforce(interaction)

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True
        await send_or_followup(
            interaction,
            content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以使用 Admin Tool。",
            ephemeral=True,
        )
        return False


class OwnerOnlyRoleToolView(RoleBaseView):
    def __init__(self, cog: object, *, owner_id: int, timeout: float | None = ROLE_TOOLS_TIMEOUT_SECONDS) -> None:
        super().__init__(cog, timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return False
        if not await self._require_admin(interaction):
            return False
        return True


@dataclass(frozen=True)
class RoleActionState:
    mode: str  # add / remove
    target_kind: str  # member / role
    target_member_id: int | None = None
    target_role_id: int | None = None
    apply_role_id: int | None = None
    include_bots: bool = False


def extract_discord_id(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"<@!?([0-9]{15,25})>|<@&([0-9]{15,25})>|([0-9]{15,25})", text)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return int(group)
            except ValueError:
                return None
    return None


async def fetch_member_by_id(guild: discord.Guild, raw: str) -> discord.Member | None:
    member_id = extract_discord_id(raw)
    if member_id is None:
        return None

    member = guild.get_member(member_id)
    if member is not None:
        return member

    try:
        return await guild.fetch_member(member_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


def get_member_from_state(guild: discord.Guild, member_id: int | None) -> discord.Member | None:
    if member_id is None:
        return None
    return guild.get_member(member_id)


def get_role_from_state(guild: discord.Guild, role_id: int | None) -> discord.Role | None:
    if role_id is None:
        return None
    return guild.get_role(role_id)


def get_batch_target_members(target_role: discord.Role, *, include_bots: bool) -> list[discord.Member]:
    members = list(target_role.members)
    if not include_bots:
        members = [member for member in members if not member.bot]
    members.sort(key=lambda member: member.display_name.casefold())
    return members


def mode_label(mode: str) -> str:
    return "加角色" if mode == "add" else "移除角色"


def mode_emoji(mode: str) -> str:
    return "➕" if mode == "add" else "➖"


# -----------------------------------------------------------------------------
# Role Tools embeds
# -----------------------------------------------------------------------------

def build_role_action_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎭 Role Tools｜{mode_label(mode)}",
        description=(
            "請選擇操作模式：\n\n"
            "👤 **單一成員** — 對指定一位成員加 / 移除角色\n"
            "🎭 **角色群組** — 對所有擁有某個角色的成員批量處理\n\n"
            "每個操作最後都會有確認頁，避免誤操作。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def build_member_select_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇成員",
        description=(
            "請用下面的 **User Select** 選擇目標成員。\n\n"
            "如果 Discord 搜尋不到該成員，請撳 **🆔 用 User ID**。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="User Select 搜尋不到時，可用 Developer Mode 複製 User ID。")
    return embed


def build_group_select_embed(mode: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇目標群組",
        description=(
            "請用下面的 **Role Select** 選擇目標角色群組。\n\n"
            "Bot 會對所有擁有此角色的成員執行操作。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="批量操作會在最後顯示預計影響人數。")
    return embed


def build_apply_role_select_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    if state.target_kind == "member":
        member = get_member_from_state(guild, state.target_member_id)
        target_text = member.mention if member else "`目標成員已不存在或未在 cache，請重新選擇`"
    else:
        role = get_role_from_state(guild, state.target_role_id)
        target_text = f"所有擁有 {role.mention} 的成員" if role else "`目標角色已不存在`"

    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜{mode_label(mode)}｜選擇角色",
        description=(
            f"目標：{target_text}\n\n"
            f"請用下面的 **Role Select** 選擇要{mode_label(mode)}的角色。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="下一步會顯示確認頁。")
    return embed


def build_include_bots_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    target_role = get_role_from_state(guild, state.target_role_id)
    target_text = target_role.mention if target_role else "`目標角色已不存在`"
    apply_role = get_role_from_state(guild, state.apply_role_id)
    apply_text = apply_role.mention if apply_role else "`處理角色已不存在`"
    embed = discord.Embed(
        title=f"{mode_emoji(mode)} Role Tools｜批量設定",
        description=(
            f"目標群組：所有擁有 {target_text} 的成員\n"
            f"要{mode_label(mode)}：{apply_text}\n\n"
            "批量操作是否包含 Bot？\n\n"
            "建議保持 **不包含 Bot**，除非你清楚知道要處理 bot account。"
        ),
        color=MENU_COLOR,
    )
    return embed


def build_confirm_embed(mode: str, state: RoleActionState, guild: discord.Guild) -> discord.Embed:
    apply_role = get_role_from_state(guild, state.apply_role_id)
    apply_text = apply_role.mention if apply_role else "`處理角色已不存在`"

    if state.target_kind == "member":
        member = get_member_from_state(guild, state.target_member_id)
        target_text = member.mention if member else f"User ID `{state.target_member_id}`"
        impact_text = "`1` 位成員"
    else:
        target_role = get_role_from_state(guild, state.target_role_id)
        members = get_batch_target_members(target_role, include_bots=state.include_bots) if target_role else []
        target_text = f"所有擁有 {target_role.mention} 的成員" if target_role else "`目標角色已不存在`"
        impact_text = f"`{len(members)}` 位成員"

    embed = discord.Embed(
        title=f"{mode_emoji(mode)} 確認{mode_label(mode)}？",
        description=(
            f"目標：{target_text}\n"
            f"角色：{apply_text}\n"
            f"包含 Bot：`{'是' if state.include_bots else '否'}`\n"
            f"預計影響：{impact_text}\n\n"
            "⚠️ 此操作會立即修改成員角色。"
        ),
        color=0xED4245 if mode == "remove" else MENU_COLOR,
    )
    embed.set_footer(text="請確認無誤後先按確認。")
    return embed


def build_role_list_select_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📋 Role Tools｜查看角色",
        description=(
            "請用下面的 **User Select** 選擇要查看角色的成員。\n\n"
            "如果 Discord 搜尋不到該成員，請撳 **🆔 用 User ID 查詢**。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="User Select 搜尋不到時，可用 Developer Mode 複製 User ID。")
    return embed


def build_role_tools_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🎭 Role Tools",
        description=(
            "**Select Menu 角色管理工具**\n\n"
            "➕ **加角色** — 用選單選成員 / 角色，再確認執行\n"
            "➖ **移除角色** — 用選單選成員 / 角色，再確認執行\n"
            "📋 **查看角色** — 用 User Select 或 User ID 查看角色\n"
            "🧬 **新版本頻道** — 先保留為 slash 指令提示，不直接 button 執行\n\n"
            "✅ 平時用選單，搜尋不到成員時用 User ID fallback。\n"
            "⚠️ 批量處理前會顯示預計影響人數。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜Role Tools 只限授權成員使用。")
    return embed


def build_role_channel_new_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🧬 新版本頻道",
        description=(
            "呢個功能涉及 clone channel、建立新版本 role 同權限設定，暫時保留用 slash command 執行。\n\n"
            "請使用：\n"
            "`/role_channel_new`\n\n"
            "建議只喺需要建立新版 channel / role 時使用。"
        ),
        color=MENU_COLOR,
    )
    embed.set_footer(text="Con9sole Bartender｜此功能暫不直接由 button 執行。")
    return embed


# -----------------------------------------------------------------------------
# Role Tools select flow
# -----------------------------------------------------------------------------

class RoleMemberIdModal(discord.ui.Modal, title="Role Tools｜用 User ID 選成員"):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="例如：123456789012345678",
        required=True,
        min_length=15,
        max_length=25,
    )

    def __init__(self, cog: object, *, mode: str, owner_id: int):
        super().__init__(timeout=ROLE_TOOLS_TIMEOUT_SECONDS)
        self.cog = cog
        self.mode = mode
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        member = await fetch_member_by_id(interaction.guild, str(self.user_id.value))
        if member is None:
            await interaction.response.send_message(
                "❌ 找不到呢個 User ID 對應嘅伺服器成員。\n"
                "請確認：\n"
                "1. ID 正確\n"
                "2. 該用戶仍在伺服器內\n"
                "3. Bot 有 Server Members Intent / 權限讀取成員",
                ephemeral=True,
            )
            return

        state = RoleActionState(mode=self.mode, target_kind="member", target_member_id=member.id)
        await interaction.response.send_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
            ephemeral=True,
        )


class RoleListUserIdModal(discord.ui.Modal, title="Role Tools｜用 User ID 查看角色"):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="例如：123456789012345678",
        required=True,
        min_length=15,
        max_length=25,
    )

    def __init__(self, cog: object, *, owner_id: int):
        super().__init__(timeout=ROLE_TOOLS_TIMEOUT_SECONDS)
        self.cog = cog
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個 Role Tools 面板只限發起者使用。", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("❌ 只可在伺服器使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        member = await fetch_member_by_id(interaction.guild, str(self.user_id.value))
        if member is None:
            await interaction.response.send_message(
                "❌ 找不到呢個 User ID 對應嘅伺服器成員。\n"
                "請確認 ID 正確，而且該用戶仍在伺服器內。",
                ephemeral=True,
            )
            return

        await self.cog.execute_role_list_for_member(interaction, member=member, edit_existing=False)


class RoleToolsView(RoleBaseView):
    def __init__(self, cog: object) -> None:
        super().__init__(cog, timeout=None)

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:admin", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await self.cog.open_admin_tool_from_button(interaction)

    @discord.ui.button(label="加角色", emoji="➕", style=discord.ButtonStyle.primary, custom_id="bartender:role_tools:grant", row=0)
    async def grant_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_action_embed("add"),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode="add"),
            ephemeral=True,
        )

    @discord.ui.button(label="移除角色", emoji="➖", style=discord.ButtonStyle.danger, custom_id="bartender:role_tools:revoke", row=0)
    async def revoke_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_action_embed("remove"),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode="remove"),
            ephemeral=True,
        )

    @discord.ui.button(label="查看角色", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:list", row=1)
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            embed=build_role_list_select_embed(),
            view=RoleListSelectView(self.cog, owner_id=interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="新版本頻道", emoji="🧬", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:channel_new", row=1)
    async def channel_new_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        if not await self._require_admin(interaction):
            return
        await send_or_followup(
            interaction,
            embed=build_role_channel_new_help_embed(interaction.user),
            view=RoleToolsView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Menu", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id="bartender:role_tools:home", row=2)
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return
        await self.cog.open_home_menu_from_button(interaction)


class RoleActionTypeView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode

    @discord.ui.button(label="單一成員", emoji="👤", style=discord.ButtonStyle.primary, row=0)
    async def member_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_member_select_embed(self.mode),
            view=RoleMemberSelectView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="角色群組", emoji="🎭", style=discord.ButtonStyle.secondary, row=0)
    async def role_group_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_group_select_embed(self.mode),
            view=RoleGroupTargetSelectView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class MemberTargetSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇目標成員；搜尋不到請用 User ID", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleMemberSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_member_selected(interaction, self.values[0])


class RoleMemberSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode
        self.add_item(MemberTargetSelect())

    async def handle_member_selected(self, interaction: discord.Interaction, selected: discord.Member | discord.User) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return

        member = selected if isinstance(selected, discord.Member) else interaction.guild.get_member(selected.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(selected.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is None:
            await interaction.response.edit_message(content="❌ 找不到目標成員，請改用 User ID fallback。", embed=None, view=None)
            return

        state = RoleActionState(mode=self.mode, target_kind="member", target_member_id=member.id)
        await interaction.response.edit_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
        )

    @discord.ui.button(label="用 User ID", emoji="🆔", style=discord.ButtonStyle.primary, row=1)
    async def user_id_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoleMemberIdModal(self.cog, mode=self.mode, owner_id=interaction.user.id))

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_role_action_embed(self.mode),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class GroupTargetRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇目標角色群組", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleGroupTargetSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_target_role_selected(interaction, self.values[0])


class RoleGroupTargetSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, mode: str) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.mode = mode
        self.add_item(GroupTargetRoleSelect())

    async def handle_target_role_selected(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if role.is_default():
            await interaction.response.send_message("❌ 不能選擇 @everyone 作為目標群組。", ephemeral=True)
            return

        state = RoleActionState(mode=self.mode, target_kind="role", target_role_id=role.id)
        await interaction.response.edit_message(
            embed=build_apply_role_select_embed(self.mode, state, interaction.guild),
            view=RoleApplyRoleSelectView(self.cog, owner_id=interaction.user.id, state=state),
        )

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=build_role_action_embed(self.mode),
            view=RoleActionTypeView(self.cog, owner_id=interaction.user.id, mode=self.mode),
        )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class ApplyRoleSelect(discord.ui.RoleSelect):
    def __init__(self, mode: str) -> None:
        super().__init__(placeholder=f"選擇要{mode_label(mode)}的角色", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleApplyRoleSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_apply_role_selected(interaction, self.values[0])


class RoleApplyRoleSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state
        self.add_item(ApplyRoleSelect(state.mode))

    async def handle_apply_role_selected(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if role.is_default():
            await interaction.response.send_message("❌ 不能加上或移除 @everyone。", ephemeral=True)
            return

        new_state = RoleActionState(
            mode=self.state.mode,
            target_kind=self.state.target_kind,
            target_member_id=self.state.target_member_id,
            target_role_id=self.state.target_role_id,
            apply_role_id=role.id,
            include_bots=False,
        )

        if new_state.target_kind == "role":
            await interaction.response.edit_message(
                embed=build_include_bots_embed(new_state.mode, new_state, interaction.guild),
                view=RoleIncludeBotsView(self.cog, owner_id=interaction.user.id, state=new_state),
            )
            return

        await interaction.response.edit_message(
            embed=build_confirm_embed(new_state.mode, new_state, interaction.guild),
            view=RoleConfirmView(self.cog, owner_id=interaction.user.id, state=new_state),
        )

    @discord.ui.button(label="返回", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        if self.state.target_kind == "member":
            await interaction.response.edit_message(
                embed=build_member_select_embed(self.state.mode),
                view=RoleMemberSelectView(self.cog, owner_id=interaction.user.id, mode=self.state.mode),
            )
        else:
            await interaction.response.edit_message(
                embed=build_group_select_embed(self.state.mode),
                view=RoleGroupTargetSelectView(self.cog, owner_id=interaction.user.id, mode=self.state.mode),
            )

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleIncludeBotsView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state

    async def _go_confirm(self, interaction: discord.Interaction, include_bots: bool) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return
        new_state = RoleActionState(
            mode=self.state.mode,
            target_kind=self.state.target_kind,
            target_member_id=self.state.target_member_id,
            target_role_id=self.state.target_role_id,
            apply_role_id=self.state.apply_role_id,
            include_bots=include_bots,
        )
        await interaction.response.edit_message(
            embed=build_confirm_embed(new_state.mode, new_state, interaction.guild),
            view=RoleConfirmView(self.cog, owner_id=interaction.user.id, state=new_state),
        )

    @discord.ui.button(label="不包含 Bot", emoji="🚫", style=discord.ButtonStyle.primary, row=0)
    async def exclude_bots_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_confirm(interaction, include_bots=False)

    @discord.ui.button(label="包含 Bot", emoji="🤖", style=discord.ButtonStyle.secondary, row=0)
    async def include_bots_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_confirm(interaction, include_bots=True)

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleConfirmView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int, state: RoleActionState) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.state = state
        self.done = False

    @discord.ui.button(label="確認", emoji="✅", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個操作已經完成。", ephemeral=True)
            return
        self.done = True
        await self.cog.execute_role_change_from_select(interaction, state=self.state)
        self.stop()

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消 Role Tools 操作。", embed=None, view=None)
        self.stop()


class RoleListUserSelect(discord.ui.UserSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="選擇要查看角色的成員；搜尋不到請用 User ID", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, RoleListSelectView):
            await interaction.response.send_message("❌ Role Tools view 狀態異常，請重新開啟。", ephemeral=True)
            return
        await self.view.handle_user_selected(interaction, self.values[0])


class RoleListSelectView(OwnerOnlyRoleToolView):
    def __init__(self, cog: object, *, owner_id: int) -> None:
        super().__init__(cog, owner_id=owner_id)
        self.add_item(RoleListUserSelect())

    async def handle_user_selected(self, interaction: discord.Interaction, selected: discord.Member | discord.User) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="❌ 只可在伺服器使用。", embed=None, view=None)
            return

        member = selected if isinstance(selected, discord.Member) else interaction.guild.get_member(selected.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(selected.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is None:
            await interaction.response.edit_message(content="❌ 找不到指定成員，請改用 User ID fallback。", embed=None, view=None)
            return

        await self.cog.execute_role_list_for_member(interaction, member=member, edit_existing=True)

    @discord.ui.button(label="用 User ID 查詢", emoji="🆔", style=discord.ButtonStyle.primary, row=1)
    async def user_id_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoleListUserIdModal(self.cog, owner_id=interaction.user.id))

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="已取消查看角色。", embed=None, view=None)
        self.stop()
