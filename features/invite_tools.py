from __future__ import annotations

from collections.abc import Callable

import discord

import config
from core.safe_send import send_or_followup
from features.menu_stats import record_usage_sync

DEFAULT_INVITE_CODE = "QNbSTTkn83"
DEFAULT_INVITE_URL = f"https://discord.gg/{DEFAULT_INVITE_CODE}"
FIXED_INVITE_URL = str(
    getattr(
        config,
        "FIXED_INVITE_URL",
        getattr(config, "COMMUNITY_INVITE_URL", DEFAULT_INVITE_URL),
    )
    or DEFAULT_INVITE_URL
)


def _invite_code_from_url(invite_url: str) -> str:
    cleaned = invite_url.strip().rstrip("/")
    if not cleaned:
        return ""

    for marker in ("discord.gg/", "discord.com/invite/"):
        if marker in cleaned:
            code = cleaned.split(marker, 1)[1]
            return code.split("?", 1)[0].split("/", 1)[0]

    return cleaned


def build_invite_format_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🔗 邀請",
        description=f"{user.mention}，你想要邊種格式？",
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜邀請資訊只會傳畀你。")
    return embed


class InviteFormatView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        can_use_admin_func: Callable[[discord.Member | discord.User], bool],
    ) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.can_use_admin_func = can_use_admin_func
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個邀請選項只限發起者使用。", ephemeral=True)
            return False
        return True

    def _disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def _finish_with_invite(self, interaction: discord.Interaction, *, as_full_link: bool) -> None:
        if self.done:
            await interaction.response.send_message("呢個邀請請求已經處理咗。", ephemeral=True)
            return

        self.done = True
        self._disable_buttons()
        record_usage_sync("invite", interaction.user.id, interaction.guild_id)

        if as_full_link:
            content = (
                "🔗 **邀請連結：**\n"
                f"{FIXED_INVITE_URL}"
            )
        else:
            invite_code = _invite_code_from_url(FIXED_INVITE_URL)
            content = (
                "#️⃣ **純邀請碼：**\n"
                f"`{invite_code}`"
            )

        await interaction.response.edit_message(content=content, embed=None, view=self)
        self.stop()

    @discord.ui.button(label="完整連結", emoji="🔗", style=discord.ButtonStyle.primary)
    async def hyperlink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish_with_invite(interaction, as_full_link=True)

    @discord.ui.button(label="純邀請碼", emoji="#️⃣", style=discord.ButtonStyle.secondary)
    async def code_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish_with_invite(interaction, as_full_link=False)

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個邀請請求已經處理咗。", ephemeral=True)
            return

        self.done = True
        self._disable_buttons()
        await interaction.response.edit_message(content="已取消邀請。", embed=None, view=self)
        self.stop()


async def create_invite_link_from_button(
    interaction: discord.Interaction,
    *,
    can_use_admin_func: Callable[[discord.Member | discord.User], bool],
) -> None:
    await send_or_followup(
        interaction,
        embed=build_invite_format_embed(interaction.user),
        view=InviteFormatView(owner_id=interaction.user.id, can_use_admin_func=can_use_admin_func),
        ephemeral=True,
    )
