from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.safe_send import safe_message_kwargs, send_or_followup
from features.admin_actions import (
    admin_ping_from_button as run_admin_ping_from_button,
    admin_reload_from_button as run_admin_reload_from_button,
    admin_vc_teardown_from_button as run_admin_vc_teardown_from_button,
)
from features.invite_tools import create_invite_link_from_button as run_create_invite_link_from_button
from features.menu_embeds import (
    build_admin_tool_embed,
    build_help_embed,
    build_home_menu_embed,
    build_main_menu_embed,
    build_quick_bar_embed,
)
from features.menu_helpers import (
    MENU_COLOR,
    build_menu_file,
    can_use_admin,
    can_use_admin_stats,
    claim_mention_message,
    get_retry_after,
    safe_defer,
    touch_cooldown,
)
from features.menu_stats import build_admin_stats_embed, init_stats_db, record_usage_sync
from features.menu_views import (
    AdminToolView,
    CommunityHubView,
    HelpMenuView,
    HomeMenuView,
    MainMenuView,
    MenuEntryView,
    QuickBarView,
    build_full_menu_view,
    build_menu_entry_view,
)
from features.role_tools import (
    RoleActionState,
    RoleToolsView,
    build_role_tools_embed,
    get_member_from_state,
    get_role_from_state,
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
            await send_or_followup(
                interaction,
                content=f"⏳ 請等 {retry_after:.1f} 秒後再用 /menu。",
                ephemeral=True,
            )
            return False

        touch_cooldown(interaction.user.id)
        return True

    async def enforce_menu_button_cooldown(self, interaction: discord.Interaction) -> bool:
        if can_use_admin(interaction.user):
            return True

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

    async def record_usage(self, feature: str, user_id: int | None = None, guild_id: int | None = None) -> None:
        record_usage_sync(feature, user_id, guild_id)

    async def execute_role_change_from_select(self, interaction: discord.Interaction, *, state: RoleActionState) -> None:
        if not interaction.guild:
            await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            return
        if not can_use_admin(interaction.user):
            await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            return

        role_cog = interaction.client.get_cog("RoleManager")
        if role_cog is None or not hasattr(role_cog, "_apply_role_change"):
            await interaction.response.edit_message(content="❌ RoleManager cog 未載入，請先 `/reload role`。", embed=None, view=None)
            return

        apply_role = get_role_from_state(interaction.guild, state.apply_role_id)
        if apply_role is None:
            await interaction.response.edit_message(content="❌ 要處理嘅角色已不存在。", embed=None, view=None)
            return

        target_member: discord.Member | None = None
        target_role: discord.Role | None = None

        if state.target_kind == "member":
            target_member = get_member_from_state(interaction.guild, state.target_member_id)
            if target_member is None and state.target_member_id is not None:
                try:
                    target_member = await interaction.guild.fetch_member(state.target_member_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    target_member = None
            if target_member is None:
                await interaction.response.edit_message(content="❌ 目標成員已不存在，或 Bot 無法讀取該成員。", embed=None, view=None)
                return
        else:
            target_role = get_role_from_state(interaction.guild, state.target_role_id)
            if target_role is None:
                await interaction.response.edit_message(content="❌ 目標角色群組已不存在。", embed=None, view=None)
                return

        feature = "admin_role_grant" if state.mode == "add" else "admin_role_revoke"
        record_usage_sync(feature, interaction.user.id, interaction.guild_id)

        try:
            await role_cog._apply_role_change(  # type: ignore[attr-defined]
                interaction,
                role_id=str(apply_role.id),
                target_member=target_member,
                target_role=target_role,
                include_bots=state.include_bots,
                mode=state.mode,
            )
        except discord.InteractionResponded:
            return
        except Exception as exc:
            await send_or_followup(
                interaction,
                content=f"⚠️ Role Tools 執行失敗：`{type(exc).__name__}`：{exc}",
                ephemeral=True,
            )

    async def execute_role_list_for_member(
        self,
        interaction: discord.Interaction,
        *,
        member: discord.Member,
        edit_existing: bool = True,
    ) -> None:
        if not interaction.guild:
            if edit_existing:
                await interaction.response.edit_message(content="⚠️ 呢個工具只可以喺伺服器內使用。", embed=None, view=None)
            else:
                await interaction.response.send_message("⚠️ 呢個工具只可以喺伺服器內使用。", ephemeral=True)
            return
        if not can_use_admin(interaction.user):
            if edit_existing:
                await interaction.response.edit_message(content="❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", embed=None, view=None)
            else:
                await interaction.response.send_message("❌ 你需要 Admin / Helper 權限先可以使用 Role Tools。", ephemeral=True)
            return

        roles = [role for role in member.roles if not role.is_default()]
        roles.sort(key=lambda role: role.position, reverse=True)
        record_usage_sync("admin_role_list", interaction.user.id, interaction.guild_id)

        if not roles:
            content = f"ℹ️ {member.mention} 沒有任何自訂角色。"
            if edit_existing:
                await interaction.response.edit_message(content=content, embed=None, view=None)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        lines = [f"{role.mention} (ID: `{role.id}`)" for role in roles]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current_len + len(line) + 1 > 3800:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))

        embed = discord.Embed(
            title=f"📋 {member.display_name} 的角色（高→低）",
            description=chunks[0],
            color=MENU_COLOR,
        )
        embed.set_footer(text=f"共有 {len(roles)} 個角色")

        if edit_existing:
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    async def open_main_menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_home_menu_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_help_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("help", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_help_embed(interaction.user),
            view=HelpMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

    async def open_admin_tool_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_tool", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_admin_tool_embed(interaction.user),
            view=AdminToolView(self),
            ephemeral=True,
        )

    async def create_invite_link_from_button(self, interaction: discord.Interaction) -> None:
        await run_create_invite_link_from_button(interaction, can_use_admin_func=can_use_admin)

    async def admin_stats_from_button(self, interaction: discord.Interaction) -> None:
        await safe_defer(interaction, ephemeral=True)
        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)
        embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=7, title_scope="本週")
        await send_or_followup(interaction, embed=embed, view=AdminToolView(self), ephemeral=True)

    async def admin_reload_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_reload_from_button(interaction)

    async def admin_role_tools_from_button(self, interaction: discord.Interaction) -> None:
        record_usage_sync("admin_role", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_role_tools_embed(interaction.user),
            view=RoleToolsView(self),
            ephemeral=True,
        )

    async def admin_ping_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_ping_from_button(interaction)

    async def admin_vc_teardown_from_button(self, interaction: discord.Interaction) -> None:
        await run_admin_vc_teardown_from_button(interaction)

    async def send_mention_menu(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not claim_mention_message(message.id):
            return

        if not can_use_admin(message.author):
            retry_after = get_retry_after(message.author.id)
            if retry_after > 0:
                return
            touch_cooldown(message.author.id)

        record_usage_sync("mention_menu", message.author.id, message.guild.id if message.guild else None)

        try:
            kwargs = safe_message_kwargs(
                embed=build_quick_bar_embed(message.author),
                view=QuickBarView(self),
                file=build_menu_file(),
            )
            kwargs["mention_author"] = False
            await message.reply(**kwargs)
        except discord.HTTPException:
            pass

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
        if message.author.bot:
            return
        if message.guild is None:
            return
        if self.bot.user is None:
            return

        direct_mention = f"<@{self.bot.user.id}>" in message.content or f"<@!{self.bot.user.id}>" in message.content
        if not direct_mention:
            return

        cleaned = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        if cleaned:
            return

        await self.send_mention_menu(message)

    @app_commands.command(name="menu", description="顯示 Con9sole Bartender 快捷吧枱")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def menu(self, interaction: discord.Interaction) -> None:
        if not await self._enforce_command_cooldown(interaction):
            return
        record_usage_sync("menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_quick_bar_embed(interaction.user),
            view=QuickBarView(self),
            ephemeral=False,
            file=build_menu_file(),
        )

    @app_commands.command(name="community_hub", description="顯示 Con9sole Bartender 主頁")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def community_hub(self, interaction: discord.Interaction) -> None:
        record_usage_sync("home_menu", interaction.user.id, interaction.guild_id)
        await send_or_followup(
            interaction,
            embed=build_home_menu_embed(interaction.user),
            view=HomeMenuView(self),
            ephemeral=True,
            file=build_menu_file(),
        )

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
        if not can_use_admin(interaction.user):
            await send_or_followup(
                interaction,
                content="❌ 你需要 `Manage Server` 權限或 helpers role 先可以查看統計。",
                ephemeral=True,
            )
            return

        record_usage_sync("admin_stats", interaction.user.id, interaction.guild_id)

        if scope.value == "today":
            days: int | None = 1
            title_scope = "今日"
        elif scope.value == "week":
            days = 7
            title_scope = "本週"
        else:
            days = None
            title_scope = "全部"

        embed = build_admin_stats_embed(guild_id=interaction.guild_id, days=days, title_scope=title_scope)
        await send_or_followup(interaction, embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
