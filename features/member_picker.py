from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from core.safe_send import send_or_followup
from core.ui import SafeView


async def resolve_member(
    interaction: discord.Interaction, user: discord.User | discord.Member
) -> discord.Member | None:
    guild = interaction.guild
    if guild is None:
        return None
    member = guild.get_member(user.id)
    if member is None:
        try:
            member = await guild.fetch_member(user.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return member


class MemberPicker(SafeView):
    """Private, owner-only target selection; the service rechecks cooldown on submit."""

    def __init__(
        self, *, owner_id: int, deliver: Callable[..., Awaitable[bool]], label: str
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.deliver = deliver
        self.finished = False
        self.busy = False
        self.message: discord.InteractionMessage | None = None
        select = discord.ui.UserSelect(
            placeholder=label, min_values=1, max_values=1, row=0
        )
        select.callback = self.select_member
        self.selector = select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await send_or_followup(
                interaction, content="呢個選單只限開啟者使用。", ephemeral=True
            )
            return False
        if self.finished or self.busy:
            await send_or_followup(
                interaction,
                content="呢個請求已處理或正在送出，請稍候。",
                ephemeral=True,
            )
            return False
        return True

    async def select_member(self, interaction: discord.Interaction) -> None:
        if not await self.interaction_check(interaction):
            return
        self.busy = True
        try:
            if await self.deliver(interaction, to=self.selector.values[0]):
                self.finished = True
                self.stop()
                if self.message is not None:
                    try:
                        await self.message.edit(
                            content="✅ 已送出。", embed=None, view=None
                        )
                    except discord.HTTPException:
                        pass
        finally:
            self.busy = False

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        self.finished = True
        self.stop()
        await interaction.response.edit_message(
            content="已取消。", embed=None, view=None
        )

    async def on_timeout(self) -> None:
        self.finished = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="選單已過期，請用 `/menu` 重新開啟。", embed=None, view=None
                )
            except discord.HTTPException:
                pass


async def open_member_picker(
    interaction: discord.Interaction,
    *,
    deliver: Callable[..., Awaitable[bool]],
    label: str,
) -> None:
    if interaction.guild is None:
        await send_or_followup(
            interaction, content="請喺伺服器內使用。", ephemeral=True
        )
        return
    view = MemberPicker(owner_id=interaction.user.id, deliver=deliver, label=label)
    await interaction.response.send_message(label, view=view, ephemeral=True)
    view.message = await interaction.original_response()
