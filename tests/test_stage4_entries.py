import unittest
from unittest.mock import AsyncMock, MagicMock

from quick_bar_fakes import interaction
from features.menu_views import QuickBarView, SectionMenuView
from features.language_preferences import localize_menu
from features.menu_embeds import build_help_embed


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_shortcuts_dispatch_without_activity_cooldown(self):
        menu = MagicMock()
        menu.enforce_menu_button_cooldown = AsyncMock(return_value=False)
        for key, cog, method in (
            ('tempvc_control', 'TempVC', 'open_control_panel_from_menu'),
            ('squad_subscriptions', 'SquadCards', 'menu_entry'),
        ):
            inter = interaction()
            target = MagicMock(**{method: AsyncMock()})
            inter.client.get_cog.return_value = target
            view = QuickBarView(menu)
            await view.handle_item(inter, next(b.item for b in view.children if b.item.id == key))
            inter.client.get_cog.assert_called_with(cog)
            getattr(target, method).assert_awaited_once_with(inter)
            view.stop()
        menu.enforce_menu_button_cooldown.assert_not_awaited()

    async def test_new_entries_fit_rows_and_keep_ids_in_both_wordings(self):
        from test_stage3_wording import member as language_member
        for code in ('hk', 'tw'):
            view = QuickBarView(MagicMock())
            ids = [b.custom_id for b in view.children]
            _, localized = localize_menu(language_member(code), view=view)
            self.assertEqual([b.custom_id for b in localized.children], ids)
            self.assertEqual(len(ids), len(set(ids)))
            for row in range(5):
                self.assertLessEqual(sum(b.row == row for b in localized.children), 3 if row == 3 else 2)
            self.assertIn('我的組隊通知', {b.label for b in localized.children})
            self.assertIn('小隊語音管理' if code == 'tw' else '小隊 call 控制', {b.label for b in localized.children})
            self.assertIn('我的組隊通知', build_help_embed(language_member(code)).description)
            view.stop()

    async def test_confession_entry_opens_existing_modal_without_submitting(self):
        from cogs.confession import Confession, ConfessionModal
        inter = interaction()
        target = Confession(MagicMock())
        inter.client.get_cog.return_value = target
        menu = MagicMock()
        menu.enforce_menu_button_cooldown = AsyncMock(return_value=True)
        view = SectionMenuView(menu, 'social')
        await view.handle_item(inter, next(b.item for b in view.children if b.item.id == 'confession'))
        inter.response.send_modal.assert_awaited_once()
        self.assertIsInstance(inter.response.send_modal.call_args.args[0], ConfessionModal)
        view.stop()

    async def test_voice_notice_omits_absent_view_for_initial_and_followup(self):
        from cogs.tempvc import _send_interaction_message
        for done in (False, True):
            inter = interaction()
            inter.response.is_done.return_value = done
            inter.followup.send = AsyncMock()
            await _send_interaction_message(inter, 'voice notice')
            sender = inter.followup.send if done else inter.response.send_message
            sender.assert_awaited_once_with(content='voice notice', ephemeral=True)
