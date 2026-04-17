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
        title="🍸 Con9sole Bartender",
        description="你走近吧檯，酒保抬頭看向你。\n\n**「歡迎光臨，要點什麼？」**",
        color=MENU_COLOR,
    )

    # 👉 只保留「選項名稱」，唔再教學
    embed.add_field(name="📋 主選單", value="\u200b", inline=True)
    embed.add_field(name="👥 召集隊友", value="\u200b", inline=True)
    embed.add_field(name="🎧 小隊房", value="\u200b", inline=True)

    embed.add_field(name="🎉 來一點鼓勵", value="\u200b", inline=True)
    embed.add_field(name="🍹 來一杯", value="\u200b", inline=True)
    embed.add_field(name="📱 社群", value="\u200b", inline=True)

    embed.add_field(name="ℹ️ 說明", value="\u200b", inline=True)
    embed.add_field(name="🗑️ 關閉", value="\u200b", inline=True)

    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，今晚由我為你服務。")

    return embed


def build_help_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ 使用說明",
        description="酒保已經準備好，以下是你可以使用的服務。",
        color=MENU_COLOR,
    )
    embed.add_field(name="👥 召集隊友", value="發起組隊 / 招募隊友", inline=False)
    embed.add_field(name="🎧 開一間小隊房", value="建立臨時語音房", inline=False)
    embed.add_field(name="🎉 來一點鼓勵", value="送出隨機打氣內容", inline=False)
    embed.add_field(name="🍹 來一杯", value="抽一杯隨機飲品", inline=False)
    embed.add_field(name="📱 社群", value="查看官方 IG / Threads", inline=False)
    embed.add_field(name="🗑️ 關閉", value="關閉目前面板", inline=False)
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，慢慢揀，我喺度等你。")
    return embed


def build_socials_embed(user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📱 Con9sole 社群",
        description="想追蹤最新動態？酒保幫你準備好官方連結。",
        color=MENU_COLOR,
    )
    embed.add_field(name="📸 Instagram", value="官方 IG", inline=False)
    embed.add_field(name="🧵 Threads", value="官方 Threads", inline=False)
    embed.set_image(url=f"attachment://{BARTENDER_ATTACHMENT_NAME}")
    embed.set_footer(text=f"{user.display_name}，有空都可以去逛逛。")
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
        label="返回主選單",
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
        label="返回主選單",
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
            file=build_menu_file(),
        )


class MenuEntryView(BaseMenuView):
    def __init__(self, cog: "Menu") -> None:
        super().__init__(cog)

    @discord.ui.button(
        label="主選單",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="bartender:entry:menu",
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
            file=build_menu_file(),
        )


def build_menu_entry_view(interaction: discord.Interaction) -> discord.ui.View | None:
    menu_cog = interaction.client.get_cog("Menu")
    if menu_cog is None:
        return None
    return MenuEntryView(menu_cog)


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
        label="主選單",
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
            file=build_menu_file(),
        )

    @discord.ui.button(
        label="召集隊友",
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
            missing_message="❌ 召集隊友功能未載入。",
        )

    @discord.ui.button(
        label="開一間小隊房",
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
            missing_message="❌ 搵唔到小隊房控制面板入口。",
        )

    @discord.ui.button(
        label="來一點鼓勵",
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
            missing_message="❌ 鼓勵功能未載入。",
        )

    @discord.ui.button(
        label="來一杯",
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
        label="社群",
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
        label="說明",
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
        label="關閉",
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
            await interaction.followup.send("❌ 呢個面板刪除失敗。", ephemeral=True)


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
        self.bot.add_view(MenuEntryView(self))
        self.bot.add_view(SocialsMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self._views_registered = True

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 面板")
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
