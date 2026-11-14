import copy
import unittest
from features.news_channel_categories import CHANNELS,LABELS,VIEW,category_prompts,category_overwrites,can_view,overwrite_signature,prompt_signature,required_questions_ready

class NewsCategoryTests(unittest.TestCase):
    def test_optional_area_expansion_preserves_other_choices_and_prompts(self):
        prompts=[dict(id='area',title='想開啟哪些區域？（選填，可複選）',single_select=False,required=False,in_onboarding=True,
            options=[dict(id='chat',title='綜合閒聊區',role_ids=['chat'],channel_ids=[]),dict(id='news',title='遊戲新聞區',role_ids=['old'],channel_ids=[]),dict(id='test',title='社群測試區',role_ids=['tester'],channel_ids=[])]),
            dict(id='1426676369567387826',title='legacy',options=[dict(title='顯示新聞區'),dict(title='暫時隱藏')]),
            dict(id='game',title='game',options=[dict(id='x',title='Game',role_ids=['game'],channel_ids=['vc'])])]
        original=copy.deepcopy(prompts)
        ids=dict(ps='101',xbox='102',pc='103')
        result=category_prompts(prompts,ids)
        self.assertEqual(prompts,original)
        self.assertEqual(len(result),2)
        self.assertEqual(result[1],original[2])
        self.assertEqual(result[0]['options'][0],original[0]['options'][0])
        self.assertEqual(result[0]['options'][-1],original[0]['options'][-1])
        for key,label in LABELS.items():
            option=next(o for o in result[0]['options'] if o['title']==label)
            self.assertEqual(option['role_ids'],[ids[key]])
            self.assertEqual(option['channel_ids'],[str(CHANNELS[key])])
        self.assertEqual(category_prompts(result,ids),result)
        original[0]['required']=True
        with self.assertRaises(ValueError):category_prompts(original,ids)

    def test_permission_comparison_ignores_order_but_rejects_changed_access(self):
        before=[dict(id='a',type=0,allow='1024',deny='0'),dict(id='b',type=1,allow='0',deny='1024')]
        self.assertEqual(overwrite_signature(before),overwrite_signature(list(reversed(before))))
        changed=copy.deepcopy(before);changed[0]['allow']='0'
        self.assertNotEqual(overwrite_signature(before),overwrite_signature(changed))

    def test_question_comparison_keeps_mappings_but_ignores_default_metadata(self):
        before=dict(id='q',title='Question',single_select=False,required=False,in_onboarding=False,
            options=[dict(id='o',title='Choice',description=None,role_ids=['b','a'],channel_ids=[],emoji=None)])
        after=copy.deepcopy(before);after['options'][0].update(description='',role_ids=['a','b'],emoji={})
        after['read_only_metadata']='new'
        self.assertEqual(prompt_signature(before),prompt_signature(after))
        after['options'][0]['role_ids']=['other']
        self.assertNotEqual(prompt_signature(before),prompt_signature(after))

    def test_current_required_questions_do_not_depend_on_historical_ids(self):
        prompts=[dict(id='new1',title='你使用哪些遊戲平台？（必選，可複選）',required=True,single_select=False,in_onboarding=True,options=[{},{}]),
                 dict(id='new2',title='選擇想玩的遊戲（必選，可複選；也可選「暫不選擇」）',required=True,single_select=False,in_onboarding=True,options=[{},{}])]
        self.assertTrue(required_questions_ready(prompts))
        prompts[1]['required']=False
        self.assertFalse(required_questions_ready(prompts))

    def test_roles_only_unlock_selected_channel_even_with_other_game_roles(self):
        roles=[dict(id='guild',permissions=str(VIEW)),dict(id='old',permissions='0'),dict(id='game',permissions='0'),
               dict(id='ps',permissions='0'),dict(id='xbox',permissions='0'),dict(id='pc',permissions='0'),dict(id='bot',permissions='0')]
        old=dict(permission_overwrites=[dict(id='guild',type=0,allow='0',deny=str(VIEW)),
            dict(id='old',type=0,allow=str(VIEW|2048),deny='0'),dict(id='game',type=0,allow=str(VIEW),deny='0')])
        new=dict(permission_overwrites=category_overwrites('guild',old,'ps',{'ps','xbox','pc'},set(),{'bot'}))
        def member(*ids):return dict(user={'id':'user'},roles=list(ids))
        self.assertTrue(can_view('guild',roles,member('old'),old))
        self.assertFalse(can_view('guild',roles,member('old','game'),new))
        self.assertTrue(can_view('guild',roles,member('old','game','ps'),new))
        self.assertFalse(can_view('guild',roles,member('xbox'),new))
        self.assertTrue(can_view('guild',roles,member('bot'),new))
        old_row=next(o for o in new['permission_overwrites'] if o['id']=='old')
        self.assertTrue(int(old_row['allow'])&2048) # other permission bits retained
        self.assertTrue(int(old['permission_overwrites'][1]['allow'])&VIEW) # input untouched

class NewsMemberControlTests(unittest.TestCase):
    def test_owner_guard_and_role_changes_keep_unrelated_roles(self):
        import subprocess,sys
        r=subprocess.run([sys.executable,'-c',r'''
import asyncio,tempfile,json
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock,patch
import config
from core.news_channel_ui import NewsChannelSelect,NewsChannelView
async def main():
    ps,xbox,pc,game=object(),object(),object(),object()
    roles=dict(ps=ps,xbox=xbox,pc=pc)
    member=S(id=1,roles=[ps,xbox,game],add_roles=AsyncMock(),remove_roles=AsyncMock())
    fresh=S(id=1,roles=[ps,game])
    guild=S(fetch_member=AsyncMock(side_effect=[member,fresh]))
    i=S(user=S(id=1),guild=guild,guild_id=config.GUILD_ID,
        response=S(defer=AsyncMock(),send_message=AsyncMock()),followup=S(send=AsyncMock()))
    view=NewsChannelView(1,{'ps','xbox'})
    assert await view.interaction_check(i)
    i.user.id=2
    assert not await view.interaction_check(i)
    i.user.id=1
    with patch('core.news_channel_ui.safe_roles',AsyncMock(return_value=roles)):
        await NewsChannelSelect.callback(S(values=['ps']),i)
    member.add_roles.assert_not_awaited()
    member.remove_roles.assert_awaited_once_with(xbox,reason='Member news channel choice')
    assert i.followup.send.call_args.kwargs['ephemeral']
    assert game in fresh.roles
asyncio.run(main())
'''],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
