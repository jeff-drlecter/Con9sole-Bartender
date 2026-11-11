import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import discord
from features.language_preferences import language, preference_roles, ROLE_NAMES, serialize_prompts, localize_menu, menu_text


def role(code, value=0, managed=False):
    return NS(name=ROLE_NAMES[code], permissions=discord.Permissions(value), managed=managed, id=1 if code == 'hk' else 2)


class LanguageTests(unittest.TestCase):
    def test_default_and_conflict(self):
        self.assertEqual(language(NS(roles=[])), 'neutral')
        self.assertEqual(language(NS(roles=[role('tw')])), 'tw')
        self.assertEqual(language(NS(roles=[role('tw'), role('hk')])), 'neutral')
        self.assertEqual(language(NS(roles=[role('tw', 8)])), 'neutral')

    def test_role_safety(self):
        self.assertEqual(set(preference_roles([role('hk'), role('tw')])), {'hk', 'tw'})
        for roles in ([role('hk')], [role('hk'),role('tw',8)], [role('hk'),role('tw',managed=True)], [role('hk'),role('tw'),role('tw')]):
            with self.assertRaises(ValueError):
                preference_roles(roles)

    def test_no_substring_translation(self):
        self.assertEqual(menu_text('Jeff話：飲一杯', 'tw'), 'Jeff話：飲一杯')
        self.assertEqual(menu_text('🥂 請人飲', 'tw'), '🥂 請客喝一杯')

    def test_embed_copied(self):
        embed = discord.Embed(title='🍸 Con9sole 吧枱', description='飲杯嘢，定搵人開局？')
        translated, _ = localize_menu(NS(roles=[role('tw')]), embed)
        self.assertEqual(translated.title, '🍸 Con9sole 吧台')
        self.assertEqual(embed.title, '🍸 Con9sole 吧枱')

    def test_prompt_option_ids_preserved(self):
        guild = MagicMock()
        option = discord.OnboardingPromptOption.from_dict(data=dict(id='222222222222222222', title='Games', description='', role_ids=['333333333333333333'], channel_ids=[]), state=MagicMock(), guild=guild)
        prompt = discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice, title='Games', options=[option])
        prompt.id = 111111111111111111
        serialized = serialize_prompts(NS(prompts=[prompt]))[0]
        self.assertEqual(serialized['id'], '111111111111111111')
        self.assertEqual(serialized['options'][0]['id'], '222222222222222222')
        self.assertEqual(serialized['options'][0]['role_ids'], ['333333333333333333'])

    def test_channel_overwrites_rejected(self):
        hk, tw = MagicMock(), MagicMock()
        hk.name, tw.name = ROLE_NAMES['hk'], ROLE_NAMES['tw']
        for r in (hk, tw):
            r.managed = False
            r.permissions = discord.Permissions.none()
        with self.assertRaises(ValueError):
            preference_roles([hk, tw], [NS(overwrites={tw: discord.PermissionOverwrite(view_channel=True)})])

    def test_make_room_only_moves_known_news_prompt(self):
        from features.language_preferences import make_room_for_language, NEWS_PROMPT_ID
        prompts = [dict(id=str(i), in_onboarding=True, options=[dict(id='answer')]) for i in range(3)]
        prompts.append(dict(id=NEWS_PROMPT_ID, in_onboarding=True, options=[dict(id='keep')]))
        result = make_room_for_language(prompts)
        self.assertFalse(result[-1]['in_onboarding'])
        self.assertTrue(prompts[-1]['in_onboarding'])
        self.assertEqual(result[-1]['options'], prompts[-1]['options'])
        with self.assertRaises(ValueError):
            make_room_for_language([dict(id=str(i), in_onboarding=True) for i in range(4)])


class LanguageAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_owner_cannot_write(self):
        from features.language_preferences import LanguageView
        from unittest.mock import AsyncMock
        interaction = NS(user=NS(id=9), guild=MagicMock(), response=NS(send_message=AsyncMock()))
        view = LanguageView(1)
        self.assertFalse(await view.interaction_check(interaction))
        await view.choose(interaction, 'tw')
        interaction.guild.fetch_roles.assert_not_called()

    async def test_switch_uses_per_role_endpoints_and_readback(self):
        import asyncio
        import config
        from features.language_preferences import LanguageView
        from unittest.mock import AsyncMock, patch
        class R:
            managed = False
            permissions = discord.Permissions.none()
            def __init__(self, code):
                self.id = 1 if code == 'hk' else 2
                self.name = ROLE_NAMES[code]
            def __ge__(self, other):
                return False
        hk, tw = R('hk'), R('tw')
        unrelated = NS(id=99, name='member', managed=False, permissions=discord.Permissions.none())
        member = NS(id=10, roles=[hk, unrelated], add_roles=AsyncMock(), remove_roles=AsyncMock())
        fresh = NS(id=10, roles=[tw, unrelated])
        guild = NS(fetch_roles=AsyncMock(return_value=[hk,tw]), fetch_channels=AsyncMock(return_value=[]),
                   fetch_member=AsyncMock(side_effect=[member, NS(top_role=object()), fresh]))
        cog = NS(lock=asyncio.Lock())
        interaction = NS(user=NS(id=10), guild=guild, guild_id=config.GUILD_ID,
                         response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()),
                         client=NS(user=NS(id=50), get_cog=lambda name: cog if name == 'LanguagePreferences' else NS()))
        await LanguageView(10).choose(interaction, 'tw')
        self.assertEqual(member.add_roles.await_args.args, (tw,))
        self.assertEqual(member.remove_roles.await_args.args, (hk,))
        self.assertIn(unrelated, fresh.roles)
        self.assertEqual(interaction.followup.send.await_args.args[0], '已切換為台灣用語。')

    async def test_neutral_removes_only_preference_roles(self):
        import asyncio
        import config
        from features.language_preferences import LanguageView
        from unittest.mock import AsyncMock
        class R:
            managed = False
            permissions = discord.Permissions.none()
            def __init__(self, code):
                self.id = 1 if code == 'hk' else 2
                self.name = ROLE_NAMES[code]
            def __ge__(self, other):
                return False
        hk, tw = R('hk'), R('tw')
        unrelated = NS(id=99, name='member', managed=False, permissions=discord.Permissions.none())
        member = NS(id=10, roles=[hk, unrelated], add_roles=AsyncMock(), remove_roles=AsyncMock())
        fresh = NS(id=10, roles=[unrelated])
        guild = NS(fetch_roles=AsyncMock(return_value=[hk,tw]), fetch_channels=AsyncMock(return_value=[]),
                   fetch_member=AsyncMock(side_effect=[member, NS(top_role=object()), fresh]))
        cog = NS(lock=asyncio.Lock())
        interaction = NS(user=NS(id=10), guild=guild, guild_id=config.GUILD_ID,
                         response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()),
                         client=NS(user=NS(id=50), get_cog=lambda name: cog if name == 'LanguagePreferences' else NS()))
        await LanguageView(10).choose(interaction, 'neutral')
        member.add_roles.assert_not_awaited()
        self.assertEqual(member.remove_roles.await_args.args, (hk, tw))
        self.assertEqual(fresh.roles, [unrelated])
        self.assertEqual(language(fresh), 'neutral')
        self.assertEqual(interaction.followup.send.await_args.args[0], '已切換為通用繁體中文。')
