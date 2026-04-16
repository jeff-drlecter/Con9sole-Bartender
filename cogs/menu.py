from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config

MENU_COLOR = 0x2B2D31


class MemberTargetSelect(discord.ui.UserSelect):
    def __init__(self, mode: str, author_id: int):
        self.mode = mode
        self.author_id = author_id

        placeholder = "選擇要 Cheers 嘅對象" if mode == "cheers" else "選擇要請 Drink 嘅對象"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "呢個控制面板唔屬於你。請使用 `/menu` 開自己嘅 Bartender 控制面板。",
                ephemeral=True,
            )
            return

        target = self.values[0]

        if self.mode == "cheers":
            cog = interaction.client.get_cog("Cheers")
            if cog is None or not hasattr(cog, "do_cheers"):
                await interaction.response.send_message(
                    "Cheers 模組未載入或未支援 menu 整合。",
                    ephemeral=True,
                )
                return
            await cog.do_cheers(interaction, to=target)
            return

        if self.mode == "drink":
            cog = interaction.client.get_cog("Drink")
            if cog is None or not hasattr(cog, "do_drink"):
                await interaction.response.send_message(
                    "Drink 模組未載入或未支援 menu 整合。",
                    ephemeral=True,
                )
                return
            await cog.do_drink(interaction, to=target)
            return

        await interaction.response.send_message("未知操作。", ephemeral=True)


class MemberTargetView(discord.ui.View):
    def __init__(self, author_id: int, mode: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.mode = mode
        self.add_item(MemberTargetSelect(mode=mode, author_id=author_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "呢個控制面板唔屬於你。請使用 `/menu` 開自己嘅 Bartender 控制面板。",
                ephemeral=True,
            )
            return False
        return True

    @staticmethod
    def build_embed(user: discord.abc.User, mode: str) -> discord.Embed:
        title = "🍻 Cheers 選擇對象" if mode == "cheers" else "🍹 Drink 選擇對象"
        embed = discord.Embed(
            title=title,
            description="請喺下面選擇一位成員。",
            color=MENU_COLOR,
        )
        embed.set_footer(text=f"Requested by {user.display_name}")
        return embed

    @discord.ui.button(label="Back", emoji="🔙", style=discord.ButtonStyle.primary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = MainMenuView.build_embed(interaction.user)
        view = MainMenuView(author_id=self.author_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class TempVCMenuView(discord.ui.View):
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

    @staticmethod
    def build_embed(user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🎧 Temp VC 控制面板",
            description="點擊下面按鈕管理臨時語音房。",
            color=MENU_COLOR,
        )
        embed.add_field(name="➕ Create Temp VC", value="手動建立一個 Temp VC", inline=False)
        embed.add_field(name="🗑️ Delete Current VC", value="刪除你目前身處嘅 Temp VC", inline=False)
        embed.add_field(
            name="📖 How it works",
            value="加入每個分區嘅「開call」會自動建立小隊call。",
            inline=False,
        )
        embed.set_footer(text=f"Requested by {user.display_name}")
        return embed

    @discord.ui.button(label="Create", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("TempVC")
        if cog is None or not hasattr(cog, "create_temp_vc_from_menu"):
            await interaction.response.send_message(
                "TempVC 模組未載入或未支援 menu 整合。",
                ephemeral=True,
            )
            return
        await cog.create_temp_vc_from_menu(interaction)

    @discord.ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("TempVC")
        if cog is None or not hasattr(cog, "teardown_temp_vc_from_menu"):
            await interaction.response.send_message(
                "TempVC 模組未載入或未支援 menu 整合。",
                ephemeral=True,
            )
            return
        await cog.teardown_temp_vc_from_menu(interaction)

    @discord.ui.button(label="How it works", emoji="📖", style=discord.ButtonStyle.secondary, row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🎧 Temp VC 說明：\n"
            "- 每個分區都有一個 `開call` Hub VC\n"
            "- 成員加入 `開call` 時，Bot 會喺同分區建立 `小隊call • N`\n"
            "- 空房達指定秒數後會自動刪除\n"
            "- 你亦可以喺呢個面板手動建立 / 刪除 Temp VC",
            ephemeral=True,
        )

    @discord.ui.button(label="Back", emoji="🔙", style=discord.ButtonStyle.primary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = MainMenuView.build_embed(interaction.user)
        view = MainMenuView(author_id=self.author_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class MainMenuView(discord.ui.View):
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

    @staticmethod
    def build_embed(user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🍻 Bartender 控制面板",
            description="點擊下面按鈕使用功能。",
            color=MENU_COLOR,
        )
        embed.add_field(name="🍻 Cheers", value="選擇成員後送上打氣", inline=True)
        embed.add_field(name="🍹 Drink", value="選擇成員後請對方飲酒", inline=True)
        embed.add_field(name="🎧 Temp VC", value="臨時語音房控制", inline=True)
        embed.add_field(name="ℹ️ Help", value="顯示簡單說明", inline=True)
        embed.set_footer(text=f"Requested by {user.display_name}")
        return embed

    @discord.ui.button(label="Cheers", emoji="🍻", style=discord.ButtonStyle.success, row=0)
    async def cheers_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = MemberTargetView.build_embed(interaction.user, mode="cheers")
        view = MemberTargetView(author_id=self.author_id, mode="cheers")
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Drink", emoji="🍹", style=discord.ButtonStyle.primary, row=0)
    async def drink_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = MemberTargetView.build_embed(interaction.user, mode="drink")
        view = MemberTargetView(author_id=self.author_id, mode="drink")
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Temp VC", emoji="🎧", style=discord.ButtonStyle.secondary, row=1)
    async def tempvc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = TempVCMenuView.build_embed(interaction.user)
        view = TempVCMenuView(author_id=self.author_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Help", emoji="ℹ️", style=discord.ButtonStyle.secondary, row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "可用方式：\n"
            "- `/menu`：開啟 Bartender 控制面板\n"
            "- `/cheers`：使用 Cheers\n"
            "- `/drink`：使用 Drink\n"
            "- `@con9sole-bartender`：提示你去用 `/menu`",
            ephemeral=True,
        )

    @discord.ui.button(label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
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

    @app_commands.command(name="menu", description="開啟 Bartender 控制面板")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction):
        embed = MainMenuView.build_embed(interaction.user)
        view = MainMenuView(author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if self.bot.user is None:
            return

        content = (message.content or "").strip()
        expected_mentions = {
            f"<@{self.bot.user.id}>",
            f"<@!{self.bot.user.id}>",
        }

        if content in expected_mentions:
            await message.reply(
                "🍻 請使用 `/menu` 開啟 Bartender 控制面板。",
                mention_author=False,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Menu(bot))
