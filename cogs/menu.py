from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.safe_send import send_or_followup
from features.admin_actions import (
    admin_ping_from_button as run_admin_ping_from_button,
    admin_reload_from_button as run_admin_reload_from_button,
    admin_role_tools_from_button as run_admin_role_tools_from_button,
    admin_stats_command as run_admin_stats_command,
    admin_stats_from_button as run_admin_stats_from_button,
    admin_vc_teardown_from_button as run_admin_vc_teardown_from_button,
)
from features.menu_actions import (
    open_admin_tool_menu as run_open_admin_tool_menu,
    open_help_menu as run_open_help_menu,
    open_home_menu as run_open_home_menu,
    open_instagram_menu as run_open_instagram_menu,
    open_invite_menu as run_open_invite_menu,
    open_quick_bar_menu as run_open_quick_bar_menu,
    open_threads_menu as run_open_threads_menu,
    send_mention_quick_bar as run_send_mention_quick_bar,
)
from features.menu_helpers import (
    can_use_admin,
    claim_mention_message,
    get_retry_after,
    touch_cooldown,
)
from features.menu_stats import init_stats_db, record_usage_sync
from features.menu_views import (
    AdminToolView,
    HelpMenuView,
    HomeMenuView,
    QuickBarView,
)
from features.role_tools import RoleActionState, RoleToolsView
from features.role_tools_actions import (
    execute_role_change_from_select as run_execute_role_change_from_select,
    execute_role_list_for_member as run_execute_role_list_for_member,
)


class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._views_registered = False
        init_stats_db()

    async def _enforce_command_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(interaction, content=f"⏳ 請等 {retry_after:.1f} 秒後再用 /menu。", ephemeral=True)
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def enforce_menu_button_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

        retry_after = get_retry_after(interaction.user.id)
        if retry_after > 0:
            await send_or_followup(interaction, content=f"⏳ 請等 {retry_after:.1f} 秒後再撳。", ephemeral=True)
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def record_usage(self, feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
        record_usage_sync(feature, user_id, guild_id)

    async def execute_role_change_from_select(self, interaction: discord.Interaction, *, state: RoleActionState) -> None:
        await run_execute_role_change_from_select(interaction, state=state)

    async def execute_role_list_for_member(self, interaction: discord.Interaction, *, member: discord.Member, edit_existing: bool = True) -> None:
        await run_execute_role_list_for_member(interaction, member=member, edit_existing=edit_existing)

    async def open_main_menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        await run_open_quick_bar_menu(self, interaction, ephemeral=True)

    async def open_home_menu_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_home_menu(self, interaction)

    async def open_help_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_help_menu(self, interaction)

    async def open_admin_tool_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_admin_tool_menu(self, interaction)

    async def create_invite_link_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_invite_menu(interaction)

    async def open_instagram_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_instagram_menu(interaction)

    async def open_threads_from_button(self, interaction: discord.Interaction) -> None:
        await run_open_threads_menu(interaction)

    async def admin_stats_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_stats_from_button(self, interaction)

    async def admin_reload_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_reload_from_button(interaction)

    async def admin_role_tools_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_role_tools_from_button(self, interaction)

    async def admin_ping_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_ping_from_button(interaction)

    async def admin_vc_teardown_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_vc_teardown_from_button(interaction)

    async def send_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not claim_mention_message(message.id):
            return
        await run_send_mention_quick_bar(self, message)

    async def cog_load(self) -> None:
        if self._views_registered:
            return
        self.bot.add_view(QuickBarView(self))
        self.bot.add_view(HomeMenuView(self))
        self.bot.add_view(HelpMenuView(self))
        self.bot.add_view(AdminToolView(self))
        self.bot.add_view(RoleToolsView(self))
        self._views_registered = True

    @commands.Cog.listener("on_message")
    async def on_message_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or self.bot.user is None:
            return
        bot_id = self.bot.user.id
        direct_mention = f"<@{bot_id}>" in message.content or f"<@!{bot_id}>" in message.content
        if not direct_mention:
            return
        cleaned = message.content.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()
        if cleaned:
            return
        await self.send_mention_menu(message)

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 快捷吧枱")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        await run_open_quick_bar_menu(self, interaction, ephemeral=False)

    @app_commands.command(name="community_hub", description="顯示 Con9sole Bartender 主頁")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        await run_open_home_menu(self, interaction)

    @app_commands.command(name="admin_stats", description="查看 Community Bot 使用數據")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(scope="查看範圍：today / week / all")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="今日", value="today"),
            app_commands.Choice(name="本週", value="week"),
            app_commands.Choice(name="全部", value="all"),
        ]
    )
    async def admin_stats(self, interaction: discord.Interaction, scope: app_commands.Choice[str]) -> None:
        await run_admin_stats_command(interaction, scope_value=scope.value)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
