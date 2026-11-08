from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from core.safe_send import send_or_followup
from features.daily_bar import (
    build_daily_bar_embed,
    get_daily_bar_completion,
    get_daily_bar_task,
)

log = logging.getLogger("con9sole-bartender.daily-bar.cog")


TASK_ACTIONS: dict[str, tuple[str, str]] = {
    "drink": ("Drink", "menu_entry"),
    "drink_gift": ("Drink", "gift_drink_entry"),
    "cheers": ("Cheers", "menu_entry"),
    "cheers_target": ("Cheers", "cheer_for_member_entry"),
    "drink_collection": ("Drink", "collection_entry"),
    "team": ("Teams", "menu_entry"),
}


class DailyBarActionButton(discord.ui.Button):
    def __init__(self, *, task_key: str, emoji: str, completed: bool) -> None:
        super().__init__(
            label="已完成" if completed else "去做任務",
            emoji="✅" if completed else emoji,
            style=discord.ButtonStyle.success if completed else discord.ButtonStyle.primary,
            disabled=completed,
            custom_id=f"bartender:daily_bar:action:{task_key}",
        )
        self.task_key = task_key

    async def callback(self, interaction: discord.Interaction) -> None:
        if get_daily_bar_task(interaction.guild_id).key != self.task_key:
            await interaction.response.send_message("任務已刷新，請重新開啟今日小任務。", ephemeral=True)
            return
        if self.task_key in ('text', 'voice'):
            task = get_daily_bar_task(interaction.guild_id)
            await interaction.response.send_message(task.method + "\n完成後可返回今日小任務查看進度。", ephemeral=True)
            return
        if self.task_key not in TASK_ACTIONS:
            await interaction.response.send_message("❌ 此每日任務暫時未設定動作。", ephemeral=True)
            return

        cog_name, method_name = TASK_ACTIONS[self.task_key]
        target = interaction.client.get_cog(cog_name)
        if target is None:
            await interaction.response.send_message(f"❌ `{cog_name}` 功能未載入。", ephemeral=True)
            return

        method = getattr(target, method_name, None)
        if method is None or not callable(method):
            await interaction.response.send_message(f"❌ `{cog_name}` 未提供 `{method_name}` 入口。", ephemeral=True)
            return

        await method(interaction)


class DailyBarView(discord.ui.View):
    def __init__(self, *, guild_id: int | None, user_id: int, completed: bool | None = None, now=None) -> None:
        super().__init__(timeout=180)
        self.owner_id = user_id
        from features.daily_bar import _current_date
        self.day = _current_date(now=now)
        task = get_daily_bar_task(guild_id, now=now)
        if completed is None:
            completed = get_daily_bar_completion(guild_id, user_id) is not None
        self.add_item(DailyBarActionButton(task_key=task.key, emoji=task.emoji, completed=completed))
        from features.drink_views import FeatureButton
        for index,(label,emoji,cog,method) in enumerate((
            ('我的會員卡','🎖️','CommunityLevels','menu_entry'),
            ('我的收藏','🍾','Drink','collection_entry'),
            ('重新整理','🔄','DailyBar','menu_entry'),
            ('返回吧枱','🍸','Menu','open_main_menu'),
        )):
            self.add_item(FeatureButton(label=label,emoji=emoji,cog=cog,method=method,row=1+index//2))


    async def interaction_check(self, interaction):
        from features.daily_bar import _current_date
        if interaction.user.id != self.owner_id or self.day != _current_date():
            await interaction.response.send_message("面板已過期或唔屬於你，請重新開啟今日小任務。", ephemeral=True)
            return False
        return True


class DailyBar(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _record_usage(self, interaction: discord.Interaction) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage("daily_bar", interaction.user.id, interaction.guild_id)
            except Exception:
                log.exception("Failed to record daily-bar usage: user=%s", interaction.user.id)

    async def _send_daily_bar(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._record_usage(interaction)
        from features.member_activity import reward_task
        reward = await reward_task(self.bot, interaction)
        import inspect
        status_method = getattr(self.bot.get_cog('CommunityLevels'), 'daily_task_status', None)
        status = {}
        if inspect.iscoroutinefunction(status_method):
            try:
                status = await status_method(interaction)
            except Exception:
                log.exception('Daily task status unavailable: user=%s', interaction.user.id)
                status = dict(reward_state='暫時未能核對入帳狀態，請稍後重新整理；唔使重複做任務。')
        embed = build_daily_bar_embed(interaction.guild_id, user=interaction.user, **status)
        if reward:
            embed.add_field(name='會員獎勵', value=reward, inline=False)
        view = DailyBarView(guild_id=interaction.guild_id, user_id=interaction.user.id,
            completed=(status["progress"] >= get_daily_bar_task(interaction.guild_id, now=status.get("now")).target) if "progress" in status else None,
            now=status.get("now"))
        await send_or_followup(interaction, embed=embed, view=view, ephemeral=True)

    async def menu_entry(self, interaction: discord.Interaction) -> None:
        await self._send_daily_bar(interaction)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="daily_bar", description="查看今日吧枱任務")
    async def daily_bar(self, interaction: discord.Interaction) -> None:
        await self._send_daily_bar(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyBar(bot))
