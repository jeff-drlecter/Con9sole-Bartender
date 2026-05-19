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
        self.stop()
