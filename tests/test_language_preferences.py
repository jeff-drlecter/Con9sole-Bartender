import unittest
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from features.role_audit_reason import RoleAuditReason, parse_role_audit_reason
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
        self.assertEqual(set(preference_roles([role('hk'), role('tw')], set())), {'hk', 'tw'})
        for roles in ([role('hk')], [role('hk'),role('tw',8)], [role('hk'),role('tw',managed=True)], [role('hk'),role('tw'),role('tw')]):
            with self.assertRaises(ValueError):
                preference_roles(roles, set())

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
        with self.assertRaises(ValueError):
            preference_roles([role('hk'), role('tw')], {2})

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
    def interaction(self, rows):
        import config

        class R:
            managed = False
            permissions = discord.Permissions.none()

            def __init__(self, code):
                self.id = 1 if code == 'hk' else 2
                self.name = ROLE_NAMES[code]

            def __ge__(self, other):
                return False

        hk, tw = R('hk'), R('tw')
        member = NS(id=10, roles=[hk], add_roles=AsyncMock(), remove_roles=AsyncMock())
        http = NS(get_all_guild_channels=AsyncMock(return_value=rows),
                  edit_guild_onboarding=AsyncMock())
        guild = NS(id=config.GUILD_ID, _state=NS(http=http),
                   fetch_roles=AsyncMock(return_value=[hk, tw]),
                   fetch_member=AsyncMock(side_effect=[member, NS(top_role=object()), NS(id=10, roles=[tw])]),
                   create_role=AsyncMock())
        # Run the installed library conversion, rather than mocking its failure.
        guild.fetch_channels = lambda: discord.Guild.fetch_channels(guild)
        cog = NS(lock=asyncio.Lock())
        interaction = NS(user=NS(id=10), guild=guild, guild_id=config.GUILD_ID,
                         response=NS(defer=AsyncMock(), send_message=AsyncMock()), followup=NS(send=AsyncMock()),
                         client=NS(user=NS(id=50), get_cog=lambda name: cog))
        return interaction, member

    async def choose(self, interaction, code='tw'):
        from features.language_preferences import LanguageView
        with patch('features.menu_embeds.build_quick_bar_embed', return_value=None), \
                patch('features.menu_views.QuickBarView', return_value=None), \
                patch('features.menu_helpers.can_use_admin', return_value=False):
            # Exercise the actual temporary menu button callback wiring too.
            view = LanguageView(10)
            await next(button for button in view.children if button.custom_id == f'language:{code}').callback(interaction)

    async def setup_language(self, interaction):
        from cogs.language_preferences import LanguagePreferences
        from features.language_preferences import PROMPT_TITLE
        from features.onboarding_wording import LANGUAGE_OPTIONS
        guild = interaction.guild
        admin = MagicMock(spec=discord.Member)
        admin.guild_permissions = discord.Permissions(administrator=True)
        guild.fetch_member = AsyncMock(return_value=admin)
        options = [discord.OnboardingPromptOption.from_dict(
            data=dict(id=str(100 + i), title=title, description=LANGUAGE_OPTIONS[i - 1][2], role_ids=[str(i)], channel_ids=[]),
            state=MagicMock(), guild=MagicMock()) for i, title in ((1, '香港語境'), (2, '台灣語境'))]
        prompt = discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice,
                                         title=PROMPT_TITLE, options=options, single_select=True, in_onboarding=True)
        prompt.id = 1000
        guild.onboarding = AsyncMock(return_value=NS(prompts=[prompt]))
        cog = LanguagePreferences(NS())
        await cog.setup_command.callback(cog, interaction)

    async def test_unknown_channel_type_does_not_break_member_button(self):
        rows = [dict(id='100', type=20, permission_overwrites=[])]
        interaction, member = self.interaction(rows)
        with self.assertRaises(discord.InvalidData):
            await interaction.guild.fetch_channels()
        interaction.guild._state.http.get_all_guild_channels.reset_mock()
        await self.choose(interaction)
        member.add_roles.assert_awaited_once()
        member.remove_roles.assert_awaited_once()
        interaction.guild._state.http.get_all_guild_channels.assert_awaited_once_with(interaction.guild.id)
        self.assertEqual(interaction.followup.send.await_args.args[0], '已切換為台灣用語。')
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])

    async def test_unknown_channel_type_does_not_break_admin_setup(self):
        interaction, _ = self.interaction([dict(id='100', type=20, permission_overwrites=[])])
        await self.setup_language(interaction)
        self.assertTrue(interaction.followup.send.await_args.args[0].startswith('✅'), interaction.followup.send.await_args.args[0])
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        interaction.guild._state.http.get_all_guild_channels.assert_awaited_once_with(interaction.guild.id)

    def assert_blocked(self, interaction, member):
        member.add_roles.assert_not_awaited()
        member.remove_roles.assert_not_awaited()
        interaction.guild.create_role.assert_not_awaited()
        interaction.guild._state.http.edit_guild_onboarding.assert_not_awaited()
        self.assertTrue(interaction.followup.send.await_args.args[0].startswith('設定未完成：'))
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])

    async def test_any_language_role_overwrite_blocks_both_paths(self):
        for entry in (self.choose, self.setup_language):
            for channel_type in (0, 20):
                for role_id in ('1', '2'):
                    for bits in ({'allow': '1024', 'deny': '0'}, {'allow': '0', 'deny': '1024'},
                                 {'allow': '0', 'deny': '0'}, {}):
                        with self.subTest(entry=entry.__name__, channel_type=channel_type, role_id=role_id, bits=bits):
                            rows = [dict(id='100', type=channel_type,
                                         permission_overwrites=[dict(id=role_id, type=0, **bits)])]
                            interaction, member = self.interaction(rows)
                            await entry(interaction)
                            self.assert_blocked(interaction, member)
                            self.assertIn('覆寫', interaction.followup.send.await_args.args[0])

    async def test_supported_and_unknown_channels_accept_legitimate_omissions(self):
        # Omitted guild_id/permission_overwrites and omitted allow/deny follow
        # Discord and discord.py defaults. Matching member IDs are not roles.
        rows = [dict(id='100', type=0, name='general', position=0),
                dict(id='101', type=20, permission_overwrites=[
                    dict(id='1', type=1), dict(id='2', type=1, allow='1024'),
                    dict(id='999', type=0, deny='1024')])]
        for code in ('hk', 'tw'):
            with self.subTest(code=code):
                interaction, member = self.interaction(rows)
                chosen = next(r for r in interaction.guild.fetch_roles.return_value if r.name == ROLE_NAMES[code])
                interaction.guild.fetch_member.side_effect = [member, NS(top_role=object()), NS(id=10, roles=[chosen])]
                await self.choose(interaction, code)
                member.add_roles.assert_awaited_once_with(chosen, reason=member.add_roles.await_args.kwargs['reason'])
                self.assertFalse(interaction.followup.send.await_args.args[0].startswith('設定未完成'))
        interaction, _ = self.interaction(rows)
        await self.setup_language(interaction)
        self.assertTrue(interaction.followup.send.await_args.args[0].startswith('✅'))

    async def test_malformed_inventory_blocks_both_paths(self):
        bad_overwrites = [None, {}, [None], [{}], [dict(id='2', type=2)],
                          [dict(id='2', type=False)], [dict(id='2', type='0')],
                          [dict(id=True, type=0)], [dict(id='bad', type=0)],
                          [dict(id='2', type=0, allow=None)], [dict(id='2', type=0, deny='bad')],
                          [dict(id='2', type=0, allow=-1)], [dict(id='2', type=0, deny=0.5)]]
        inventories = [None, [], {}, [None], [{}], [dict(id='100')], [dict(id=None, type=0)],
                       [dict(id='100', type=False)], [dict(id='100', type=0, guild_id='999')],
                       [dict(id='100', type=0), dict(id='100', type=20)]]
        inventories.extend([dict(id='100', type=20, permission_overwrites=value)] for value in bad_overwrites)
        for entry in (self.choose, self.setup_language):
            for rows in inventories:
                with self.subTest(entry=entry.__name__, rows=rows):
                    interaction, member = self.interaction(rows)
                    if entry == self.setup_language:
                        # A missing role must not be created before the inventory passes.
                        interaction.guild.fetch_roles.return_value = [role('hk')]
                    await entry(interaction)
                    self.assert_blocked(interaction, member)
                    self.assertIn('未能確認頻道權限資料', interaction.followup.send.await_args.args[0])

    async def test_unreadable_inventory_blocks_both_paths(self):
        import aiohttp
        errors = [discord.HTTPException(NS(status=status, reason='fixture'), 'private synthetic response')
                  for status in (403, 500)] + [OSError('private synthetic response'),
                                             TimeoutError('private synthetic response'),
                                             aiohttp.ClientError('private synthetic response')]
        for entry in (self.choose, self.setup_language):
            for error in errors:
                with self.subTest(entry=entry.__name__, error=type(error).__name__):
                    interaction, member = self.interaction([])
                    if entry == self.setup_language:
                        interaction.guild.fetch_roles.return_value = [role('hk')]
                    interaction.guild._state.http.get_all_guild_channels.side_effect = error
                    await entry(interaction)
                    self.assert_blocked(interaction, member)
                    message = interaction.followup.send.await_args.args[0]
                    self.assertIn('未能讀取頻道權限', message)
                    self.assertNotIn('private synthetic response', message)

    async def test_admin_refreshes_inventory_after_creating_missing_role(self):
        clean = [dict(id='100', type=20)]
        unsafe = [dict(id='100', type=20, permission_overwrites=[dict(id='2', type=0)])]
        for refreshed in (clean, unsafe):
            with self.subTest(refreshed=refreshed):
                interaction, _ = self.interaction(clean)
                guild = interaction.guild
                guild.fetch_roles.return_value = [role('hk')]
                guild.create_role.return_value = role('tw')
                guild._state.http.get_all_guild_channels.side_effect = [clean, refreshed]
                await self.setup_language(interaction)
                guild.create_role.assert_awaited_once()
                self.assertEqual(guild.create_role.await_args.kwargs['permissions'].value, 0)
                self.assertEqual(guild._state.http.get_all_guild_channels.await_count, 2)
                if refreshed == clean:
                    self.assertTrue(interaction.followup.send.await_args.args[0].startswith('✅'))
                else:
                    guild.onboarding.assert_not_awaited()
                    guild._state.http.edit_guild_onboarding.assert_not_awaited()
                    self.assertIn('覆寫', interaction.followup.send.await_args.args[0])

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
        guild = NS(id=config.GUILD_ID, _state=NS(http=NS(get_all_guild_channels=AsyncMock(return_value=[dict(id='100', type=0)]))),
                   fetch_roles=AsyncMock(return_value=[hk,tw]),
                   fetch_member=AsyncMock(side_effect=[member, NS(top_role=object()), fresh]))
        cog = NS(lock=asyncio.Lock())
        interaction = NS(user=NS(id=10), guild=guild, guild_id=config.GUILD_ID,
                         response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()),
                         client=NS(user=NS(id=50), get_cog=lambda name: cog if name == 'LanguagePreferences' else NS()))
        await LanguageView(10).choose(interaction, 'tw')
        self.assertEqual(member.add_roles.await_args.args, (tw,))
        self.assertEqual(member.remove_roles.await_args.args, (hk,))
        self.assertEqual(parse_role_audit_reason(member.add_roles.await_args.kwargs['reason']),
                         RoleAuditReason(10, 'self', 'language_grant'))
        self.assertEqual(parse_role_audit_reason(member.remove_roles.await_args.kwargs['reason']),
                         RoleAuditReason(10, 'self', 'language_revoke'))
        self.assertIn(unrelated, fresh.roles)
        self.assertEqual(interaction.followup.send.await_args.args[0], '已切換為台灣用語。')
