from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config


# ============================================================
# Bartender Menu
# - /menu：開啟控制面板
# - @Bot：提示使用 /menu
# - Buttons：直接導向 cheers / drink 功能
#
# 注意：
# 1) 呢份 menu.py 係先做 UI 入口。
# 2) 我呢版預設係「按掣後回覆提示」，避免硬 call 你現有 cheers.py / drink.py
#    入面未知結構而造成報錯。
# 3) 如果你之後想，我可以再幫你第二步改成：
#    Button 真正直接執行 cheers / drink 邏輯。
# ============================================================


MENU_COLOR = 0x2B2D31


class BartenderMenuView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "呢個控制面板唔屬於你。請使用 `/menu` 開自己嘅 Bartender 控制面板。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Cheers", emoji="🍻", style=discord.ButtonStyle.success, row=0)
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🍻 Cheers 功能按鈕已收到。\n請先保留你現有 `/cheers` 功能；下一步可以再接駁到按一下就直接執行。",
            ephemeral=True,
        )

    @discord.ui.button(label="Drink", emoji="🍹", style=discord.ButtonStyle.primary, row=0)
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🍹 Drink 功能按鈕已收到。\n請先保留你現有 `/drink` 功能；下一步可以再接駁到按一下就直接執行。",
            ephemeral=True,
        )

    @discord.ui.button(label="Help", emoji="ℹ️", style=discord.ButtonStyle.secondary, row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "可用方式：\n- `/menu`：開啟控制面板\n- `/cheers`：使用 Cheers\n- `/drink`：使用 Drink",
            ephemeral=True,
        )

    @discord.ui.button(label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="🍻 Bartender 控制面板",
            description="控制面板已關閉。請使用 `/menu` 再次開啟。",
            color=MENU_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_menu_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🍻 Bartender 控制面板",
            description="點擊下面按鈕使用功能。",
            color=MENU_COLOR,
        )
        embed.add_field(name="🍻 Cheers", value="敬酒 / 互動功能", inline=True)
        embed.add_field(name="🍹 Drink", value="飲品 / 酒類功能", inline=True)
        embed.add_field(name="ℹ️ Help", value="顯示簡單說明", inline=True)
        embed.set_footer(text=f"Requested by {user.display_name}")
        return embed

    @app_commands.command(name="menu", description="開啟 Bartender 控制面板")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction):
        embed = self.build_menu_embed(interaction.user)
        view = BartenderMenuView(author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if self.bot.user is None:
            return

        # 只在「單純 mention bot」時提示，避免干擾其他正常對話
        content = (message.content or "").strip()
        expected_mentions = {
            f"<@{self.bot.user.id}>",
            f"<@!{self.bot.user.id}>",
        }

        if content in expected_mentions:
            await message.reply("🍻 請使用 `/menu` 開啟 Bartender 控制面板。", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Menu(bot))
