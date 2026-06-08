from __future__ import annotations

import discord

import config
from core.safe_send import send_or_followup
from features.menu_stats import record_usage_sync

INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://threads.net/con9sole")


class SocialLinkConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        platform_label: str,
        url: str,
        feature_key: str,
    ) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.platform_label = platform_label
        self.url = url
        self.feature_key = feature_key
        self.done = False

        self.add_item(
            discord.ui.Button(
                label=f"開啟 {platform_label}",
                emoji="🔗",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("呢個連結選項只限發起者使用。", ephemeral=True)
            return False
        return True

    def _disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.style is not discord.ButtonStyle.link:
                item.disabled = True

    @discord.ui.button(label="取消", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.done:
            await interaction.response.send_message("呢個連結請求已經處理咗。", ephemeral=True)
            return

        self.done = True
        self._disable_buttons()
        await interaction.response.edit_message(content="已取消。", embed=None, view=self)
        self.stop()


def build_social_confirm_embed(user: discord.abc.User, *, platform_label: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔗 {platform_label}",
        description=f"{user.mention}，要開啟 Con9sole {platform_label} 嗎？",
        color=0x2B2D31,
    )
    embed.set_footer(text="Con9sole Bartender｜外部連結只會傳畀你。")
    return embed


class SocialPromptButton(discord.ui.Button):
    def __init__(
        self,
        *,
        label: str,
        emoji: str,
        platform_label: str,
        url: str,
        feature_key: str,
        row: int,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            row=row,
            custom_id=f"bartender:home:social:{feature_key}",
        )
        self.platform_label = platform_label
        self.url = url
        self.feature_key = feature_key

    async def callback(self, interaction: discord.Interaction) -> None:
        record_usage_sync(self.feature_key, interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_social_confirm_embed(interaction.user, platform_label=self.platform_label),
            view=SocialLinkConfirmView(
                owner_id=interaction.user.id,
                platform_label=self.platform_label,
                url=self.url,
                feature_key=self.feature_key,
            ),
            ephemeral=True,
        )


class InstagramPromptButton(SocialPromptButton):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="IG",
            emoji="📸",
            platform_label="Instagram",
            url=INSTAGRAM_URL,
            feature_key="instagram",
            row=row,
        )


class ThreadsPromptButton(SocialPromptButton):
    def __init__(self, *, row: int) -> None:
        super().__init__(
            label="Threads",
            emoji="🧵",
            platform_label="Threads",
            url=THREADS_URL,
            feature_key="threads",
            row=row,
        )
