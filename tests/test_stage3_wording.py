import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from features.language_preferences import ROLE_NAMES, language
from features.wording import text, view_copy, modal_copy
from cogs.tempvc import _build_created_message, _build_control_panel_message
from features.squad_subscription_views import SubscriptionView


def member(code='tw'):
    return NS(id=10, roles=[NS(name=ROLE_NAMES[code], managed=False, permissions=discord.Permissions.none())])


class CopyTests(unittest.TestCase):
    def test_dynamic_room_name_is_never_translated(self):
        room = NS(name='搵唔到房間。', mention='<#123>', user_limit=3, members=[])
        tw = _build_created_message(room, 3, wording_member=member())
        self.assertIn('臨時語音房已建立', tw)
        self.assertIn('`搵唔到房間。`', tw)
        self.assertIn('祝大家聊得開心', tw)
        self.assertIn('小隊語音管理', _build_control_panel_message(room, wording_member=member()))
        self.assertIn('Temp VC 已建立', _build_created_message(room, 3, wording_member=member('hk')))

    def test_arbitrary_input_and_default_not_inferred(self):
        self.assertEqual(text(member(), 'Jeff：搵唔到房間。'), 'Jeff：搵唔到房間。')
        self.assertEqual(text(NS(roles=[]), '搵唔到房間。'), '搵唔到房間。')
        both=member(); both.roles += member('hk').roles
        self.assertEqual(language(both), 'hk')
        self.assertEqual(text(both, '搵唔到房間。'), '搵唔到房間。')


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_ids_values_disabled_state_and_callbacks_preserved(self):
        view=discord.ui.View(timeout=None)
        button=discord.ui.Button(label='返回吧枱', custom_id='old:bar:123', disabled=True, row=1)
        callback=AsyncMock();button.callback=callback;view.add_item(button)
        select=discord.ui.Select(placeholder='揀一款遊戲取消通知', custom_id='old:select', options=[discord.SelectOption(label='返回吧枱',value='hk:user:data')])
        view.add_item(select)
        self.assertIs(view_copy(member(),view),view)
        self.assertEqual(button.label,'返回吧台')
        self.assertEqual((button.custom_id,button.disabled,button.row),('old:bar:123',True,1))
        self.assertIs(button.callback, callback)
        self.assertEqual(select.options[0].label,'返回吧枱')
        self.assertEqual(select.options[0].value,'hk:user:data')
        self.assertEqual(select.placeholder,'選擇要取消通知的遊戲')
        self.assertTrue(view.is_persistent())
        view_copy(member("hk"), view)
        self.assertEqual(button.label, "返回吧枱")

    async def test_modal_defaults_are_member_input_not_copy(self):
        modal=discord.ui.Modal(title='改小隊房名')
        field=discord.ui.TextInput(label='小隊 call 名稱',default='返回吧枱',custom_id='old:room')
        modal.add_item(field);modal_copy(member(),modal)
        self.assertEqual(modal.title,'重新命名語音房')
        self.assertEqual(field.label,'語音房名稱')
        self.assertEqual(field.default,'返回吧枱')
        self.assertEqual(field.custom_id,'old:room')

    async def test_subscription_preferences_and_game_names_preserved(self):
        rows=[dict(label='搵唔到房間。',id='unchanged',kind='once')]
        view=SubscriptionView(NS(),1,10,rows,member=member())
        embed=view.embed()
        self.assertIn('搵唔到房間。',embed.description)
        self.assertIn('選擇遊戲',embed.fields[0].value)
        self.assertNotIn('嘅',embed.footer.text)
        self.assertEqual(rows,[dict(label='搵唔到房間。',id='unchanged',kind='once')])

    async def test_old_public_card_ids_stay_dispatchable(self):
        from cogs.squad_cards import FootprintView
        value=dict(id='scope-old',guild_id=1,label='EA FC')
        view=FootprintView(None,value)
        self.assertEqual([b.custom_id for b in view.children],['squad-interest:scope-old','squad-interest-always:scope-old','squad-interest-roster:scope-old'])
        self.assertTrue(view.is_persistent())
        self.assertEqual(view.children[0].label,'🙋 下次通知我')
