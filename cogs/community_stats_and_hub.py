from __future__ import annotations
            days = 7
            title_scope = "本週"
        else:
            days = None
            title_scope = "全部"

        stats = self._get_stats(interaction.guild_id, days)
        total = self._get_total(interaction.guild_id, days)

        top_feature = "暫時未有"
        if stats:
            top_key = stats[0][0]
            top_feature = f"{FEATURE_EMOJIS.get(top_key, '🔹')} {FEATURE_LABELS.get(top_key, top_key)}"

        now_hk = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M")

        embed = discord.Embed(
            title=f"📊 Community Bot Insights｜{title_scope}",
            description=(
                f"**總使用次數：** `{total}`\n"
                f"**最活躍功能：** {top_feature}\n"
                f"**更新時間：** `{now_hk}`"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="功能使用分佈",
            value=self._format_stats_block(stats),
            inline=False,
        )
        embed.set_footer(text=f"{COMMUNITY_NAME} · Admin Stats")

        # admin stats 建議公開畀其他 admin 睇；如要私人改 ephemeral=True
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="community_hub", description="發出公開 Community Hub 入口")
    async def community_hub(self, interaction: discord.Interaction):
        await self.record_usage("hub", interaction.user.id, interaction.guild_id)

        embed = discord.Embed(
            title="🧭 Community Hub",
            description=(
                f"歡迎嚟到 **{COMMUNITY_NAME}**。\n\n"
                "你可以喺呢度快速開始：\n"
                "🎮 **組隊** — 搵隊友一齊玩\n"
                "🎙️ **建立小隊 call** — 開臨時語音房\n"
                "🎉 **打氣時間** — 為大家補充能量\n"
                "🍸 **調酒** — 來一杯今日心情\n"
                "📸 **Social Link** — 追蹤 Con9sole 最新動態\n\n"
                "按下面按鈕開始。"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Community Hub · Public Entry")

        await interaction.response.send_message(embed=embed, view=CommunityHubView(self), ephemeral=False)

    @app_commands.command(name="stats_ping", description="測試統計系統是否正常")
    async def stats_ping(self, interaction: discord.Interaction):
        await self.record_usage("stats_ping", interaction.user.id, interaction.guild_id)
        await interaction.response.send_message("✅ Community Stats 系統正常。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CommunityStatsHub(bot))
