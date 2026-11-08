import types
import unittest
from unittest.mock import AsyncMock, MagicMock
from features.member_activity import credit_success


class MemberActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_successes_use_one_shared_award_path(self):
        for action in ('drink', 'cheers'):
            levels = types.SimpleNamespace(action_credit=AsyncMock(return_value='會員 XP +1'))
            bot = MagicMock(); bot.get_cog.return_value = levels
            inter = types.SimpleNamespace(id=123)
            self.assertEqual(await credit_success(bot, inter, action), '會員 XP +1')
            levels.action_credit.assert_awaited_once_with(inter, f'{action}:123')
            bot.dispatch.assert_not_called()

    async def test_uncertain_award_never_dispatches_another_attempt(self):
        bot = MagicMock()
        bot.get_cog.return_value = types.SimpleNamespace(action_credit=AsyncMock(side_effect=RuntimeError('after commit')))
        self.assertIsNone(await credit_success(bot, types.SimpleNamespace(id=123), 'cheers'))
        bot.dispatch.assert_not_called()

    async def test_cooldown_does_not_claim_xp(self):
        bot = MagicMock()
        bot.get_cog.return_value = types.SimpleNamespace(action_credit=AsyncMock(return_value=None))
        self.assertIsNone(await credit_success(bot, types.SimpleNamespace(id=123), 'drink'))
        bot.dispatch.assert_not_called()
