from __future__ import annotations

import inspect
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import config

MENU_COLOR = 0x2B2D31

INSTAGRAM_URL = getattr(config, "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/con9sole/")
THREADS_URL = getattr(config, "SOCIAL_THREADS_URL", "https://www.threads.net/@con9sole")


def build_main_menu_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="🍻 Bartender 控制面板",
        description="點擊下面按鈕，直接使用自己嘅功能。",
        color=MENU_COLOR,
    )
    embed.add_field(name="🍻 Cheers", value="為大家送上一句打氣", inline=True)
    embed.add_field(name="🍹 Drink", value="為自己隨機點一杯酒", inline=True)
    embed.add_field(name="🎧 Temp VC", value="臨時語音房控制", inline=True)
    embed.add_field(name="📱 Socials", value="查看 Con9sole 官方 IG / Threads", inline=True)
    embed.add_field(name="ℹ️ Help", value="顯示簡單說明", inline=True)
    embed.add_field(name="📋 Menu", value="重新顯示主選單", inline=True)
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ Bartender Help",
        description="以下按鈕可直接使用常用功能：",
        color=MENU_COLOR,
    )
    embed.add_field(name="🍻 Cheers", value="送出一條隨機中英對照打氣語錄。", inline=False)
    embed.add_field(name="🍹 Drink", value="隨機點一杯酒；如 drink.py 有抽卡系統會直接沿用。", inline=False)
    embed.add_field(name="🎧 Temp VC", value="打開 Temp VC 控制面板。", inline=False)
    embed.add_field(name="📱 Socials", value="查看官方 Instagram / Threads。", inline=False)
    embed.add_field(name="📋 Menu", value="重新送出一個主選單。", inline=False)
    embed.add_field(name="🗑️ Close", value="刪除當前公開 menu 訊息。", inline=False)
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


def build_socials_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📱 Con9sole Socials",
        description="點擊下面按鈕前往 Con9sole 官方社交平台。",
        color=MENU_COLOR,
    )
    embed.add_field(name="📸 Instagram", value="查看 Con9sole 官方 Instagram", inline=False)
    embed.add_field(name="🧵 Threads", value="查看 Con9sole 官方 Threads", inline=False)
    embed.set_footer(text=f"Requested by {user.display_name}")
    return embed


async def send_or_followup(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)


class SocialLinksView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
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


class SocialsMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog
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
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=False,
        )


class HelpMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Back",
        emoji="🔙",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:help:back",
        row=0,
    )
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=False,
        )


class MainMenuView(discord.ui.View):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _call_cog_method(
        self,
        interaction: discord.Interaction,
        *,
        cog_name: str,
        method_names: list[str],
        missing_message: str,
    ) -> None:
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
            # 某些既有方法簽名可能要求 keyword / positional to=None
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
        label="Cheers",
        emoji="🍻",
        style=discord.ButtonStyle.success,
        custom_id="bartender:main:cheers",
        row=0,
    )
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="Cheers",
            method_names=["do_cheers", "cheers_cmd", "cheers"],
            missing_message="❌ Cheers 功能未載入。",
        )

    @discord.ui.button(
        label="Drink",
        emoji="🍹",
        style=discord.ButtonStyle.primary,
        custom_id="bartender:main:drink",
        row=0,
    )
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._call_cog_method(
            interaction,
            cog_name="Drink",
            method_names=["do_drink", "drink"],
            missing_message="❌ Drink 功能未載入。",
        )

    @discord.ui.button(
        label="Temp VC",
        emoji="🎧",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:tempvc",
        row=1,
    )
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        tempvc_cog = interaction.client.get_cog("TempVC")
        if not tempvc_cog:
            await send_or_followup(interaction, content="❌ Temp VC 功能未載入。", ephemeral=True)
            return

        for method_name in ["send_control_panel", "tempvc_panel", "tempvc", "panel"]:
            method = getattr(tempvc_cog, method_name, None)
            if method and inspect.iscoroutinefunction(method):
                try:
                    await method(interaction)
                except TypeError:
                    await method(interaction, None)
                except discord.InteractionResponded:
                    pass
                except Exception as exc:
                    await send_or_followup(
                        interaction,
                        content=f"❌ Temp VC 出錯：{type(exc).__name__}",
                        ephemeral=True,
                    )
                return

        await send_or_followup(interaction, content="❌ 搵唔到 Temp VC 控制面板入口。", ephemeral=True)

    @discord.ui.button(
        label="Help",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:help",
        row=1,
    )
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Socials",
        emoji="📱",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:socials",
        row=2,
    )
    async def socials_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_or_followup(
            interaction,
            embed=build_socials_embed(interaction.user),
            view=SocialsMenuView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Menu",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:main:menu",
        row=2,
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_or_followup(
            interaction,
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Close",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="bartender:main:close",
        row=2,
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
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
        await interaction.response.send_message(
            embed=build_main_menu_embed(interaction.user),
            view=MainMenuView(self),
            ephemeral=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
