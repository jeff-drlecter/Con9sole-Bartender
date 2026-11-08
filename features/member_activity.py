"""One integration point for successfully delivered community actions."""
import inspect
import logging

log = logging.getLogger(__name__)


async def reward_task(bot, interaction):
    credit = getattr(bot.get_cog('CommunityLevels'), 'task_credit', None)
    if inspect.iscoroutinefunction(credit):
        try:
            return await credit(interaction)
        except Exception:
            log.exception('Daily reward remains retryable: interaction=%s', interaction.id)
    return None


async def complete_task(bot, interaction, feature):
    from features.daily_bar import complete_daily_bar_task
    from features.menu_stats import run_stats
    completed = await run_stats(complete_daily_bar_task, guild_id=interaction.guild_id,
                                user_id=interaction.user.id, feature_key=feature)
    reward = await reward_task(bot, interaction)
    if completed or reward:
        try:
            await interaction.followup.send(reward or '📅 每日任務已完成！獎勵會喺等級系統可用時核對。', ephemeral=True)
        except Exception:
            log.exception('Could not show task completion: interaction=%s', interaction.id)


async def credit_success(bot, interaction, action):
    """Use the level ledger once; return confirmed XP feedback, if available."""
    event = f'{action}:{interaction.id}'
    levels = bot.get_cog('CommunityLevels')
    credit = getattr(levels, 'action_credit', None)
    if inspect.iscoroutinefunction(credit):
        try:
            return await credit(interaction, event)
        except Exception:
            # An award may already have committed: never dispatch a second attempt.
            log.exception('Activity feedback failed: action=%s interaction=%s', action, interaction.id)
            return None
    bot.dispatch('community_activity', interaction.user, interaction.channel, event)
    return None
