import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

import config
from features.member_hints import HK, HintStore, TIPS, add_member_hint


def rng(kind=0.1, chance=0.1):
    return NS(random=Mock(side_effect=[chance, kind]), choice=lambda choices: choices[0])


def stamp(day=16, hour=12, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=HK).timestamp()


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'hints.db'
        self.store = HintStore(self.path)

    def reserve(self, event, now, *, scope='public', scope_id=10, kind=.1):
        return self.store.reserve(1, scope, scope_id, event, list(TIPS), now=now, rng=rng(kind))

    def test_public_daily_limit_persists_and_cooldown_is_shared_between_members(self):
        first = self.reserve(1, stamp())
        self.assertIsNotNone(first)
        self.store = HintStore(self.path)  # restart
        self.assertIsNone(self.reserve(2, stamp(minute=29)))
        second = self.reserve(3, stamp(minute=30))
        self.assertIsNotNone(second)
        self.assertNotEqual(first.key, second.key)
        self.assertIsNone(self.reserve(4, stamp(hour=14)))

    def test_hong_kong_day_reset_still_obeys_midnight_cooldown(self):
        self.reserve(1, stamp(hour=22))
        self.reserve(2, stamp(hour=23, minute=50))
        self.assertIsNone(self.reserve(3, stamp(day=17, hour=0, minute=10)))
        self.assertIsNotNone(self.reserve(4, stamp(day=17, hour=0, minute=20)))

    def test_duplicate_uncertain_delivery_never_gets_another_slot(self):
        self.reserve(1, stamp())
        self.assertIsNone(self.reserve(1, stamp(day=17)))
        self.assertIsNotNone(self.reserve(2, stamp(day=17)))

    def test_private_scope_never_consumes_public_or_another_member_quota(self):
        self.reserve(1, stamp())
        self.assertIsNotNone(self.reserve(2, stamp(), scope='private'))
        self.assertIsNotNone(self.reserve(3, stamp(), scope='private', scope_id=11))
        self.assertIsNone(self.reserve(4, stamp(), scope='private'))

    def test_probability_boundaries_are_25_percent_and_60_40(self):
        self.assertIsNone(self.store.reserve(1, 'public', 10, 1, list(TIPS), now=stamp(), rng=rng(chance=.25)))
        self.assertEqual(self.store.reserve(1, 'public', 10, 2, list(TIPS), now=stamp(), rng=rng(.599, .249)).kind, 'mention')
        self.assertEqual(self.reserve(3, stamp(minute=30), kind=.6).kind, 'feature')

    def test_concurrent_calls_and_recreated_store_share_atomic_quota(self):
        def reserve(event):
            return HintStore(self.path).reserve(1, 'public', 10, event, list(TIPS), now=stamp(), rng=rng())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(1, 9)))
        self.assertEqual(sum(result is not None for result in results), 1)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = NS(user=NS(id=900), get_cog=lambda name: object())
        self.inter = NS(guild_id=config.GUILD_ID, channel_id=10, id=1,
                        user=NS(id=20, bot=False, roles=[]))
        self.embed = discord.Embed(title='原有標題', description='原有內容')
        self.embed.set_footer(text='稀有度／作者不可被取代')
        self.embed.add_field(name='重要資料', value='保留')

    async def test_public_neutral_private_hk_and_tw_and_no_footer_overwrite(self):
        role = lambda code: NS(name='語境偏好｜' + code, managed=False, permissions=discord.Permissions.none())
        for private, selected, expected in [(False, '香港', '單獨提及'), (True, '香港', '單獨 tag'),
                                           (True, '台灣', '單獨提及'), (True, '', '單獨提及')]:
            self.inter.user.roles = [role(selected)] if selected else []
            embed = self.embed.copy()
            with patch.object(HintStore, 'reserve', return_value=TIPS[0]) as reserve:
                await add_member_hint(self.bot, self.inter, embed, context='menu' if private else 'drink', private=private)
            self.assertIn(expected + ' <@900>', embed.description)
            self.assertEqual(embed.footer.text, self.embed.footer.text)
            self.assertEqual(embed.fields, self.embed.fields)
            self.assertEqual(reserve.call_args.args[2], 20 if private else 10)

    async def test_important_messages_dm_and_disabled_hints_are_not_touched(self):
        for context in ('squad', 'notification', 'news', 'error', 'admin'):
            with patch.object(HintStore, 'reserve') as reserve:
                await add_member_hint(self.bot, self.inter, self.embed, context=context)
            reserve.assert_not_called()
        self.inter.guild_id = None
        with patch.object(HintStore, 'reserve') as reserve:
            await add_member_hint(self.bot, self.inter, self.embed, context='drink')
        reserve.assert_not_called()
        self.inter.guild_id = config.GUILD_ID
        with patch.dict('os.environ', {'MEMBER_HINTS_ENABLED': '0'}), patch.object(HintStore, 'reserve') as reserve:
            await add_member_hint(self.bot, self.inter, self.embed, context='drink')
        reserve.assert_not_called()
        self.assertEqual(self.embed.description, '原有內容')

    async def test_context_and_loaded_capabilities_filter_tips(self):
        self.bot.get_cog = lambda name: object() if name in ('Menu', 'Drink') else None
        with patch.object(HintStore, 'reserve', return_value=None) as reserve:
            await add_member_hint(self.bot, self.inter, self.embed, context='drink')
        keys = {tip.key for tip in reserve.call_args.args[4]}
        self.assertEqual(keys, {'mention_open', 'mention_find', 'mention_shortcut', 'collection', 'gift'})

    async def test_full_embed_or_duplicate_hint_never_reserves_or_truncates(self):
        for description in ('x' * 4096, '原有內容\n\n💡 已有提示'):
            self.embed.description = description
            with patch.object(HintStore, 'reserve') as reserve:
                await add_member_hint(self.bot, self.inter, self.embed, context='drink')
            reserve.assert_not_called()
            self.assertEqual(self.embed.description, description)

    async def test_storage_failure_does_not_break_primary_action(self):
        with patch.object(HintStore, 'reserve', side_effect=OSError('fixture')):
            await add_member_hint(self.bot, self.inter, self.embed, context='drink')
        self.assertEqual(self.embed.description, '原有內容')

    async def test_slow_optional_storage_does_not_hold_initial_reply(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
        with patch('features.member_hints.asyncio.to_thread', side_effect=slow):
            await asyncio.wait_for(add_member_hint(self.bot, self.inter, self.embed, context='drink'), timeout=1)
        self.assertEqual(self.embed.description, '原有內容')

    async def test_cheers_success_keeps_one_delivery_buttons_and_mention_policy(self):
        from cogs.cheers import Cheers
        self.inter.user.mention = '<@20>'
        self.inter.response = NS(defer=AsyncMock())
        self.inter.edit_original_response = AsyncMock()
        cog = Cheers(self.bot)
        cog._check_cheers_cooldown = AsyncMock(return_value=True)
        cog._record_usage = AsyncMock()
        cog._complete_daily_bar = AsyncMock()
        with patch('cogs.cheers.require_public_send', AsyncMock(return_value=True)), \
             patch('cogs.cheers.credit_success', AsyncMock(return_value=None)), \
             patch('cogs.cheers.touch_cheers_cooldown'), \
             patch('cogs.cheers.pick_quote', return_value=NS(english='Keep going', chinese='繼續努力', author='Author')), \
             patch.object(HintStore, 'reserve', return_value=TIPS[0]):
            self.assertTrue(await cog.do_cheers(self.inter))
        self.inter.edit_original_response.assert_awaited_once()
        kwargs = self.inter.edit_original_response.call_args.kwargs
        self.assertIn('💡', kwargs['embed'].description)
        self.assertEqual(kwargs['embed'].footer.text, 'Author')
        self.assertGreater(len(kwargs['view'].children), 0)
        self.assertFalse(kwargs['allowed_mentions'].users)
        self.assertFalse(kwargs['allowed_mentions'].everyone)
