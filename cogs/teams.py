from __future__ import annotations

import discord
from discord.ext import commands
from dataclasses import dataclass, field


# =========================
# Data
# =========================

@dataclass
class TeamState:
    leader_id: int
    required: int
    mode: str
    channel_id: int
    message_id: int | None = None

    join_now: set[int] = field(default_factory=set)
    join_later: set[int] = field(default_factory=set)

    cancelled: bool = False


# =========================
# Main Cog
# =========================

class Teams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, TeamState] = {}

    # ===== Entry from menu.py =====
    async def open_team_menu(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "請選擇需要多少位隊友：",
            view=TeamCountView(self),
            ephemeral=True,
        )

    # ===== 建立招募 =====
    async def create_team(self, interaction: discord.Interaction, count: int, mode: str):
        if not mode.strip():
            mode = "未知"

        state = TeamState(
            leader_id=interaction.user.id,
            required=count,
            mode=mode,
            channel_id=interaction.channel_id,
        )

        msg = await interaction.followup.send(
            self.build_message(state),
            view=TeamView(self, state),
        )

        state.message_id = msg.id
        self.states[msg.id] = state

    # ===== Render =====
    def build_message(self, state: TeamState) -> str:
        filled = len(state.join_now) + len(state.join_later)
        remaining = max(state.required - filled, 0)

        def fmt(ids):
            return " ".join(f"<@{i}>" for i in ids) if ids else "暫時未有人"

        if state.cancelled:
            return f"❌ 組隊行動已取消。\n召集人：<@{state.leader_id}>"

        if remaining == 0:
            status = "✅ 已齊人，可以開始！\n請按「建立小隊 call」開始對話。\n"
        else:
            status = "如果加入請按「立即加入」或「稍後加入」。\n"

        return (
            f"<@{state.leader_id}> 正在召集隊友，需要 {state.required} 位！\n"
            f"遊玩模式：{state.mode}\n\n"
            f"{status}"
            f"目前尚欠人數：{remaining}\n\n"
            f"可以立即加入：{fmt(state.join_now)}\n"
            f"可以稍後加入：{fmt(state.join_later)}"
        )


# =========================
# Select View
# =========================

class TeamCountView(discord.ui.View):
    def __init__(self, cog: Teams):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.select(
        placeholder="選擇人數",
        options=[
            discord.SelectOption(label=str(i), value=str(i))
            for i in range(1, 17)
        ],
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        count = int(select.values[0])
        await interaction.response.send_modal(TeamModeModal(self.cog, count))


# =========================
# Modal
# =========================

class TeamModeModal(discord.ui.Modal, title="設定遊玩模式"):
    def __init__(self, cog: Teams, count: int):
        super().__init__()
        self.cog = cog
        self.count = count

        self.mode = discord.ui.TextInput(
            label="遊玩模式（可留空）",
            required=False,
            placeholder="例如：Rank / ARAM / 任務",
        )
        self.add_item(self.mode)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.cog.create_team(interaction, self.count, self.mode.value)


# =========================
# Recruit View
# =========================

class TeamView(discord.ui.View):
    def __init__(self, cog: Teams, state: TeamState):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state

    def refresh(self, interaction: discord.Interaction):
        return interaction.response.edit_message(
            content=self.cog.build_message(self.state),
            view=self,
        )

    @discord.ui.button(label="立即加入", style=discord.ButtonStyle.success)
    async def join_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.cancelled:
            return

        uid = interaction.user.id

        if uid == self.state.leader_id:
            return await interaction.response.send_message("你係召集人", ephemeral=True)

        filled = len(self.state.join_now) + len(self.state.join_later)
        if filled >= self.state.required:
            return await interaction.response.send_message("❌ 已滿人", ephemeral=True)

        self.state.join_later.discard(uid)
        self.state.join_now.add(uid)

        await self.refresh(interaction)

    @discord.ui.button(label="稍後加入", style=discord.ButtonStyle.primary)
    async def join_later(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.cancelled:
            return

        uid = interaction.user.id

        if uid == self.state.leader_id:
            return await interaction.response.send_message("你係召集人", ephemeral=True)

        filled = len(self.state.join_now) + len(self.state.join_later)
        if filled >= self.state.required:
            return await interaction.response.send_message("❌ 已滿人", ephemeral=True)

        self.state.join_now.discard(uid)
        self.state.join_later.add(uid)

        await self.refresh(interaction)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id

        # leader cancel
        if uid == self.state.leader_id:
            self.state.cancelled = True
            return await interaction.response.edit_message(
                content=self.cog.build_message(self.state),
                view=None,
            )

        # member cancel
        if uid not in self.state.join_now and uid not in self.state.join_later:
            return await interaction.response.send_message("你未加入", ephemeral=True)

        self.state.join_now.discard(uid)
        self.state.join_later.discard(uid)

        await self.refresh(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Teams(bot))
