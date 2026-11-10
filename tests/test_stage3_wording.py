import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from features.language_preferences import ROLE_NAMES, language, localize_menu, wording
from features.menu_embeds import build_help_embed
from core.safe_send import send_or_followup
from core.app_command_errors import _user_message
from cogs.tempvc import _build_control_panel_message
from cogs.squad_cards import add_interest_fields, FootprintView


def member(code):
    return NS(id=10, roles=[NS(name=ROLE_NAMES[code], managed=False, permissions=discord.Permissions.none())])


class CopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_fields_footer_select_and_ids(self):
        view=discord.ui.View()
        button=discord.ui.Button(label='返回吧枱', custom_id='legacy:menu')
        select=discord.ui.Select(custom_id='legacy:select', placeholder='搵人玩', options=[discord.SelectOption(label='唔展示稱號',value='none')])
        view.add_item(button);view.add_item(select)
        embed=discord.Embed(title='🍸 Con9sole 吧枱')
        embed.add_field(name='小隊 call', value='飲一杯')  # arbitrary member-owned value
        embed.set_footer(text='返回吧枱')
        result,_=localize_menu(member('tw'),embed,view)
        self.assertEqual(result.title,'🍸 Con9sole 吧台')
        self.assertEqual(result.fields[0].name,'小隊語音')
        self.assertEqual(result.fields[0].value,'飲一杯')
        self.assertEqual(result.footer.text,'返回吧台')
        self.assertEqual(button.custom_id,'legacy:menu')
        self.assertEqual(button.label,'返回吧台')
        self.assertEqual(select.custom_id,'legacy:select')
        self.assertEqual(select.options[0].value,'none')
        self.assertEqual(select.options[0].label,'不顯示稱號')
        self.assertEqual(embed.title,'🍸 Con9sole 吧枱')

    async def test_safe_private_reply_and_followup_use_clicker(self):
        for done in (False,True):
            inter=NS(user=member('tw'),response=NS(is_done=lambda:done,send_message=AsyncMock()),followup=NS(send=AsyncMock()))
            await send_or_followup(inter,content='❌ 你冇足夠權限使用呢個指令。',ephemeral=True)
            sent=inter.followup.send if done else inter.response.send_message
            self.assertIn('你沒有足夠權限',sent.await_args.kwargs['content'])

    async def test_public_messages_not_viewer_localized(self):
        inter=NS(user=member('tw'),response=NS(is_done=lambda:False,send_message=AsyncMock()))
        await send_or_followup(inter,content='飲一杯',ephemeral=False)
        self.assertEqual(inter.response.send_message.await_args.kwargs['content'],'飲一杯')

    async def test_templates_do_not_translate_dynamic_names(self):
        self.assertEqual(wording(member('tw'),'房：{name}','房間：{name}',name='搵人玩'), '房間：搵人玩')
        room=NS(mention='<#1>',name='搵人玩',members=[],user_limit=5)
        self.assertIn('`搵人玩`',_build_control_panel_message(room,member('tw')))
        self.assertIn('小隊語音管理',_build_control_panel_message(room,member('tw')))

    async def test_shared_card_ids_and_legacy_field_cleanup(self):
        view=FootprintView(None,dict(id='scope',guild_id=1,label='Game'))
        self.assertEqual([c.custom_id for c in view.children],['squad-interest:scope','squad-interest-always:scope','squad-interest-roster:scope'])
        embed=discord.Embed()
        for name in ('🙋 下次叫埋 · 1 人','🔔 每次都叫 · 1 人','🙋 下次通知 · 1 人','參與玩家'):
            embed.add_field(name=name,value='test')
        add_interest_fields(embed,[],{})
        self.assertEqual([f.name for f in embed.fields],['參與玩家'])

    async def test_help_parity_and_mobile_copy_limits(self):
        for code in ('hk','tw'):
            embed=build_help_embed(member(code))
            self.assertLess(len(embed.description),1600)
            for entry in ('我的會員卡','我的稱號','今日小任務','管理工具','語境設定','冷卻'):
                self.assertIn(entry,embed.description)
        error=discord.app_commands.CommandOnCooldown(discord.app_commands.Cooldown(1,30),retry_after=4.6)
        self.assertIn('此指令',_user_message(error,member('tw')))
        self.assertIn('呢個指令',_user_message(error,member('hk')))
