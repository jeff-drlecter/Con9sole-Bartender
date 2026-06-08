from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import discord

import config
from core.safe_send import send_or_followup
from features.menu_stats import record_usage_sync

INVITE_CHANNEL_ID = getattr(config, "INVITE_CHANNEL_ID", None)
INVITE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
INVITE_MAX_USES = 10
INVITE_COOLDOWN_SECONDS = 60
INVITE_REUSE_MIN_REMAINING_SECONDS = 24 * 60 * 60
USER_INVITE_COOLDOWNS: dict[int, float] = {}


def get_invite_retry_after(user_id: int) -> float:
    last_used = USER_INVITE_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = INVITE_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_invite_cooldown(user_id: int) -> None:
    USER_INVITE_COOLDOWNS[user_id] = time.time()


def format_retry_seconds(seconds: float) -> str:
    seconds_int = max(0, int(seconds + 0.999))
    minutes, sec = divmod(seconds_int, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _invite_expires_at(invite: discord.Invite) -> datetime | None:
    expires_at = getattr(invite, "expires_at", None)
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            return expires_at.replace(tzinfo=timezone.utc)
        return expires_at

    max_age = int(getattr(invite, "max_age", 0) or 0)
    if max_age <= 0:
        return None

    created_at = getattr(invite, "created_at", None)
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(seconds=max_age)


def _invite_has_uses_left(invite: discord.Invite) -> bool:
    max_uses = int(getattr(invite, "max_uses", 0) or 0)
    if max_uses <= 0:
        return True

    uses = getattr(invite, "uses", None)
    if uses is None:
        return True
    return int(uses) < max_uses


def _invite_has_one_day_left(invite: discord.Invite) -> bool:
    expires_at = _invite_expires_at(invite)
    if expires_at is None:
        return True
    return (expires_at - _now_utc()).total_seconds() >= INVITE_REUSE_MIN_REMAINING_SECONDS


def _format_invite_expiry(invite: discord.Invite) -> str:
    expires_at = _invite_expires_at(invite)
    if expires_at is None:
        return "永久有效"

    remaining = max(0, int((expires_at - _now_utc()).total_seconds()))
    days, rem = divmod(remaining, 24 * 60 * 60)
    hours, _ = divmod(rem, 60 * 60)
    if days > 0:
        return f"約 {days} 日 {hours} 小時"
    return f"約 {hours} 小時"


def _is_reusable_invite(invite: discord.Invite) -> bool:
    return _invite_has_uses_left(invite) and _invite_has_one_day_left(invite)


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
    except discord.HTTPException:
        pass


async def _resolve_invite_channel(interaction: discord.Interaction) -> discord.TextChannel | discord.VoiceChannel | discord.StageChannel | None:
    if INVITE_CHANNEL_ID is None:
        return None

    channel = interaction.client.get_channel(int(INVITE_CHANNEL_ID))
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(int(INVITE_CHANNEL_ID))
        except discord.HTTPException:
            channel = None

    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
        return channel
    return None


async def _find_reusable_invite(
    channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel,
) -> discord.Invite | None:
    try:
        invites = await channel.invites()
    except discord.Forbidden:
        return None
    except discord.HTTPException:
        return None

    reusable = [invite for invite in invites if _is_reusable_invite(invite)]
    if not reusable:
        return None

    reusable.sort(
        key=lambda invite: _invite_expires_at(invite) or datetime.max.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return reusable[0]


def build_invite_confirm_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🔗 邀請",
        description=(
            f"{user.mention}，是否生成邀請碼？\n\n"
            "如果現有邀請碼仲有至少一日有效期，我會直接畀現有連結你。\n"
            "如果冇，我會生成一個新邀請碼，有效期 `7 日`。"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜邀請碼會只傳畀你。")
    return embed


class InviteConfirmView(discord.ui.View):
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
            await interaction.response.send_message("呢個邀請確認只限發起者使用。", ephemeral=True)
            return False
        return True

    async def _disable_original(self, interaction: discord.Interaction, content: str) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.edit_original_response(content=content, embed=None, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="生成", emoji="🔗", style=discord.ButtonStyle.primary)
    async def generate_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個邀請請求已經處理咗。", ephemeral=True)
            return

        self.done = True
        await safe_defer(interaction, ephemeral=True)
        await self._disable_original(interaction, "⏳ 正在處理邀請碼……")

        await _handle_invite_generation(interaction, can_use_admin_func=self.can_use_admin_func)
        self.stop()

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個邀請請求已經處理咗。", ephemeral=True)
            return

        self.done = True
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(content="已取消邀請。", embed=None, view=self)
        self.stop()


async def _handle_invite_generation(
    interaction: discord.Interaction,
    *,
    can_use_admin_func: Callable[[discord.Member | discord.User], bool],
) -> None:
    record_usage_sync("invite", interaction.user.id, interaction.guild_id)

    if INVITE_CHANNEL_ID is None:
        await interaction.followup.send(
            "⚠️ 未設定邀請入口頻道。\n"
            "請先喺 `config.py` 加：\n"
            "`INVITE_CHANNEL_ID: int = 你的channel_id`",
            ephemeral=True,
        )
        return

    channel = await _resolve_invite_channel(interaction)
    if channel is None:
        await interaction.followup.send("⚠️ 搵唔到指定邀請入口頻道，請檢查 `INVITE_CHANNEL_ID`。", ephemeral=True)
        return

    existing_invite = await _find_reusable_invite(channel)
    if existing_invite is not None:
        await interaction.followup.send(
            "🔗 **現有邀請碼仍然有效：**\n"
            f"{existing_invite.url}\n\n"
            f"剩餘有效期：`{_format_invite_expiry(existing_invite)}`\n"
            "我冇生成新邀請碼。",
            ephemeral=True,
        )
        return

    if not can_use_admin_func(interaction.user):
        retry_after = get_invite_retry_after(interaction.user.id)
        if retry_after > 0:
            await interaction.followup.send(
                f"⏳ 你啱啱已經生成過邀請碼，請等 {format_retry_seconds(retry_after)} 後再試。",
                ephemeral=True,
            )
            return

    try:
        invite = await channel.create_invite(
            max_age=INVITE_MAX_AGE_SECONDS,
            max_uses=INVITE_MAX_USES,
            unique=True,
            temporary=False,
            reason=f"Invite generated by {interaction.user} ({interaction.user.id}) via Bartender menu",
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"❌ Bartender 無權喺 {channel.mention} 建立 invite，請開啟 `Create Instant Invite` 權限。",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        await interaction.followup.send(f"❌ 建立邀請碼失敗：{type(exc).__name__}", ephemeral=True)
        return

    if not can_use_admin_func(interaction.user):
        touch_invite_cooldown(interaction.user.id)

    await interaction.followup.send(
        "🔗 **邀請碼已生成：**\n"
        f"{invite.url}\n\n"
        "有效期：`7 日`\n"
        "使用次數：`最多 10 次`\n"
        "我已經只傳畀你，想邀請朋友就 copy 呢條 link。",
        ephemeral=True,
    )


async def create_invite_link_from_button(
    interaction: discord.Interaction,
    *,
    can_use_admin_func: Callable[[discord.Member | discord.User], bool],
) -> None:
    await send_or_followup(
        interaction,
        embed=build_invite_confirm_embed(interaction.user),
        view=InviteConfirmView(owner_id=interaction.user.id, can_use_admin_func=can_use_admin_func),
        ephemeral=True,
    )
