from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import config

MENU_COLOR = 0x2B2D31
COOLDOWN_SECONDS = 3.0
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BARTENDER_IMAGE = ASSETS_DIR / "bartender.png"
BARTENDER_ATTACHMENT_NAME = "bartender.png"

INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://www.threads.net/@con9sole")

# 全局 user cooldown：同一個 user 撳任何 menu / submenu 按鈕都會共用 CD
USER_MENU_COOLDOWNS: dict[int, float] = {}


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍻 Bartender 控制面板",
        description="揀一個功能開始。",
        color=MENU_COLOR,
    )
    embed.add_field(name="📋 Menu", value="主選單", inline=True)
    embed.add_field(name="👥 組隊", value="開團招募", inline=True)
    embed.add_field(name="🎧 小隊 Call", value="臨時語音", inline=True)

    embed.add_field(name="🎉 打氣時間", value="隨機打氣", inline=True)
    embed.add_field(name="🍹 調酒", value="隨機飲品", inline=True)
    embed.add_field(name="📱 Social", value="IG / Threads", inline=True)

    embed.add_field(name="ℹ️ Help", value="使用說明", inline=True)
    embed.add_field(name="🗑️ Close", value="關閉面板", inline=True)
    embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ Bartender Help",
        description="常用功能快速入口。",
        color=MENU_COLOR,
    )
    embed.add_field(name="👥 組隊", value="開團 / 招募隊友", inline=False)
    embed.add_field(name="🎧 小隊 Call", value="建立臨時語音房", inline=False)
    embed.add_field(name="🎉 打氣時間", value="發送隨機打氣句", inline=False)
    embed.add_field(name="🍹 調酒", value="抽一杯隨機飲品", inline=False)
    embed.add_field(name="📱 Social", value="查看官方連結", inline=False)
    embed.add_field(name="🗑️ Close", value="刪除此 menu", inline=False)
    embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


def build_socials_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📱 Con9sole Social",
        description="官方社交平台連結。",
        color=MENU_COLOR,
    )
    embed.add_field(name="📸 Instagram", value="官方 IG", inline=False)
    embed.add_field(name="🧵 Threads", value="官方 Threads", inline=False)
    embed.set_thumbnail(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


def build_menu_file() -> discord.File | None:
    if not BARTENDER_IMAGE.exists():
        return None
    return discord.File(BARTENDER_IMAGE, filename=BARTENDER_ATTACHMENT_NAME)


async def send_or_followup(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
    file: discord.File | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
            file=file,
        )
    else:
        await interaction.response.send_message(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
            file=file,
        )


def get_retry_after(user_id: int) -> float:
    last_used = USER_MENU_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cooldown(user_id: int) -> None:
    USER_MENU_COOLDOWNS[user_id] = time.time()


class BaseMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _enforce_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再撳。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True


class SocialsMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

        self.add_item(
            discord.ui.Button(
                label="Instagram",
                emoji="📸",
                style=discord.ButtonStyle.link,
                url=INSTAGRAM_URL,
                row=0,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Threads",
                emoji="🧵",
                style=discord.ButtonStyle.link,
                url=THREADS_URL,
                row=0,
            )
        )

    @discord.ui.button(
        label="Back",
        emoji="🔙",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:socials:back",
        row=1,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )


class HelpMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="Back",
        emoji="🔙",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:help:back",
        row=0,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
        )


class MainMenuView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    async def _call_cog_method(
        self,
        interaction: discord.Interaction,
        *,
        cog_name: str,
        method_names: list[str],
        missing_message: str,
    ) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        target_cog = interaction.client.get_cog(cog_name)
        if not target_cog:
            await send_or_followup(interaction, content=missing_message, ephemeral=True)
            return

        method: Callable[..., Awaitable[None]] | None = None
        for method_name in method_names:
            candidate = getattr(target_cog, method_name, None)
            if candidate and inspect.iscoroutinefunction(candidate):
                method = candidate
                break

        if method is None:
            await send_or_followup(interaction, content=missing_message, ephemeral=True)
            return

        try:
            await method(interaction)
        except TypeError:
            try:
                await method(interaction, None)
            except TypeError:
                await method(interaction, to=None)
        except discord.InteractionResponded:
            pass
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"❌ 執行功能時出錯：{type(exc).__name__}",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Menu",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:menu",
        row=0,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="組隊",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:main:team",
        row=0,
    )
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="Teams",
            method_names=["open_team_menu", "start_team_menu", "team_menu"],
            missing_message="❌ 組隊功能未載入。",
        )

    @discord.ui.button(
        label="建立小隊 call",
        emoji="🎧",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:main:tempvc",
        row=0,
    )
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="TempVC",
            method_names=[
                "create_temp_vc_from_menu",
                "send_control_panel",
                "tempvc_panel",
                "tempvc",
                "panel",
            ],
            missing_message="❌ 搵唔到 Temp VC 控制面板入口。",
        )

    @discord.ui.button(
        label="打氣時間",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="bartender:main:cheers",
        row=1,
    )
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ 打氣時間功能未載入。",
        )

    @discord.ui.button(
        label="調酒",
        emoji="🍹",
        style=discord.ButtonStyle.success,
        custom_id="bartender:main:drink",
        row=1,
    )
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ 調酒功能未載入。",
        )

    @discord.ui.button(
        label="Social Link",
        emoji="📱",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:socials",
        row=1,
    )
    async def socials_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_socials_embed(interaction.user),
            view=SocialsMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="Help",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:help",
        row=2,
    )
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self.cog),
            ephemeral=True,
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="Close",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="bartender:main:close",
        row=2,
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._enforce_cooldown(interaction):
            return

        if not interaction.response.is_done():
            await interaction.response.defer()

        try:
            await interaction.message.delete()
        except discord.HTTPException:
            await interaction.followup.send("❌ 呢個 menu 刪除失敗。", ephemeral=True)


class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False

    async def _enforce_command_cooldown(self, interaction: discord.Interaction) -> bool:
        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再用 /menu。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def open_main_menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(MainMenuView(self))
        self.bot.add_view(SocialsMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self._views_registered = True

    @app_commands.command(name="menu", description="顯示 Bartender 控制面板")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return

        await interaction.response.send_message(
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self),
            ephemeral=False,
            file=build_menu_file(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
