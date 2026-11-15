from copy import deepcopy
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch
import config
from core.channel_names import plain_channel_name, is_squad_chat_name
from scripts.apply_channel_emojis import build_plan,GUILD
from cogs.squad_plans import squad_channel
from cogs.member_entry import game_entry_moves,GUIDE_NAMES
from features.referrals import SOURCE_CHANNELS


def channel(cid,name,kind=0,parent='7'):
    return dict(id=str(cid),guild_id=GUILD,name=name,type=kind,parent_id=parent,position=0,
                permission_overwrites=[dict(id=GUILD,type=0,allow='0',deny='1024')])

class ChannelEmojiTests(unittest.TestCase):
    def test_squad_eligibility_old_and_new_names_keep_same_gates(self):
        class Text:
            def __init__(self,name,parent=7,category_name='game'):
                self.name=name;self.category_id=parent;self.category=N(name=category_name)
        with patch('cogs.squad_plans.discord.TextChannel',Text):
            for name in ('fc-吹水組隊','fc-吹水組隊💬','🏀nba-吹水組隊💬'):
                self.assertTrue(squad_channel(Text(name)))
                self.assertFalse(squad_channel(Text(name,config.TEMPLATE_CATEGORY_ID)))
            self.assertFalse(squad_channel(Text('fc-吹水組隊-archive')))
            self.assertFalse(squad_channel(Text('fc-吹水組隊🔒')))
            self.assertTrue(squad_channel(Text('體驗交流💬',category_name='功能測試區')))
            self.assertFalse(squad_channel(Text('體驗交流💬')))
    def test_game_order_and_existing_guides_remain_recognized(self):
        first=N(id=1,name='official',position=0,_sorting_bucket=0)
        chat=N(id=2,name='fc-吹水組隊💬',position=1,_sorting_bucket=0)
        cat=N(id=7,name='FC',text_channels=[first,chat],channels=[first,chat])
        self.assertEqual(game_entry_moves(N(categories=[cat])),[chat])
        for name in ('如何加入不同遊戲分區✅','如何加入不同遊戲分區🧭'):
            self.assertIn(plain_channel_name(name),GUIDE_NAMES)
        self.assertEqual(SOURCE_CHANNELS['rules'],SOURCE_CHANNELS['rules📜'])
        self.assertEqual(SOURCE_CHANNELS['🆔留game-tag（非聊天）'],SOURCE_CHANNELS['留game-tag（非聊天）🆔'])
    def test_name_only_idempotent_and_excludes_voice_template_archive(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(7,'game',4,None),channel(8,'存檔區',4,None),
            channel(1,'🏀nba-吹水組隊'),channel(2,'fc-吹水組隊💬'),channel(3,'voice-吹水組隊',2),
            channel(4,'template-吹水組隊',parent=str(config.TEMPLATE_CATEGORY_ID)),channel(5,'old-吹水組隊',parent='8')])
        before=deepcopy(snap);plan=build_plan(snap,'chats')
        self.assertEqual(snap,before)
        self.assertEqual((len(plan['actions']),plan['unchanged'],plan['matched_chats']),(1,1,2))
        self.assertEqual(plan['actions'][0]['body'],dict(name='🏀nba-吹水組隊💬'))
        snap['channels'][2]['name']='🏀nba-吹水組隊💬'
        self.assertEqual(build_plan(snap,'chats')['actions'],[])
    def test_fixed_names_need_unique_identity_and_never_rename_category(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(config.RULES_CHANNEL_ID,'rules'),
             channel(2,'📺成員直播',5),channel(3,'成員直播',4),channel(4,'🧪｜體驗交流'),channel(5,'體驗交流💬')])
        plan=build_plan(snap,'all');names={a['body']['name'] for a in plan['actions']}
        self.assertEqual(names,{'rules📜','成員直播📺'})
        self.assertIn('體驗交流: missing or ambiguous',plan['blocked'])
        snap['channels'][0]['id']='99'
        self.assertIn('rules: configured ID differs',build_plan(snap,'all')['blocked'])

    def test_suggestion_box_is_not_assumed_to_be_configured_support(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(123,'📩站務-意見箱📩'),
             channel(config.SUPPORT_CHANNEL_ID,'求助入口')])
        plan=build_plan(snap,'all')
        self.assertEqual([(a['channel'],a['body']) for a in plan['actions']],
                         [('123',dict(name='站務-意見箱📮'))])
        snap['channels'].append(channel(124,'站務-意見箱'))
        self.assertEqual(build_plan(snap,'all')['actions'],[])

    def test_information_emoji_has_letter_category_but_exact_target_is_idempotent(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(123,'官方資訊-discordℹ️')])
        plan=build_plan(snap,'all')
        self.assertEqual(plan['actions'],[])
        self.assertEqual(plan['unchanged'],1)
        self.assertFalse(any(x.startswith('官方資訊-discord:') for x in plan['blocked']))
        snap['channels'].append(channel(124,'官方資訊-discord'))
        self.assertIn('官方資訊-discord: missing or ambiguous',build_plan(snap,'all')['blocked'])

    def test_official_scope_preserves_game_text_and_excludes_other_channel_types(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(7,'FC',4,None),channel(8,'存檔區',4,None),
            channel(1,'官方更新-fc',5),channel(2,'官方更新-nba📢'),channel(3,'fc-吹水組隊'),
            channel(4,'官方更新-voice',2),channel(5,'官方更新-template',parent=str(config.TEMPLATE_CATEGORY_ID)),
            channel(6,'官方更新-archive',parent='8'),channel(9,'官方更新-forum',15),
            channel(10,'官方更新-orphan',parent=None),channel(11,'非官方更新-fc'),channel(12,'官方更新-')])
        before=deepcopy(snap);plan=build_plan(snap,'official')
        self.assertEqual(snap,before)
        self.assertEqual((plan['matched_official'],plan['matched_chats'],plan['unchanged']),(2,0,1))
        self.assertEqual([(a['channel'],a['body']) for a in plan['actions']], [('1',dict(name='官方更新-fc📢'))])
        self.assertEqual(plan['blocked'],[])
        snap['channels'][2]['name']='官方更新-fc📢'
        self.assertEqual(build_plan(snap,'official')['actions'],[])
        self.assertFalse(any(a['kind']=='official_update' for a in build_plan(snap,'chats')['actions']))

    def test_library_scope_includes_forums_but_preserves_other_scopes_and_exclusions(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(7,'game',4,None),channel(8,'存檔區',4,None),
            channel(1,'fc-情報庫',15),channel(2,'情報庫-nba',0),channel(3,'情報庫🗂️',5),
            channel(4,'官方更新-fc'),channel(5,'fc-吹水組隊💬'),channel(6,'情報庫-voice',2),
            channel(9,'情報庫-template',15,parent=str(config.TEMPLATE_CATEGORY_ID)),
            channel(10,'情報庫-archive',parent='8'),channel(11,'情報庫-orphan',parent=None),
            channel(12,'情報庫使用說明'),channel(13,'情報庫-',15)])
        original=deepcopy(snap);plan=build_plan(snap,'library')
        self.assertEqual(snap,original)
        self.assertEqual((plan['matched_library'],plan['matched_chats'],plan['matched_official'],plan['unchanged']),(3,0,0,1))
        self.assertEqual([(a['channel'],a['body']) for a in plan['actions']],
                         [('1',dict(name='fc-情報庫🗂️')),('2',dict(name='情報庫-nba🗂️'))])
        self.assertEqual(plan['blocked'],[])
        snap['channels'][2]['name']='fc-情報庫🗂️';snap['channels'][3]['name']='情報庫-nba🗂️'
        self.assertEqual(build_plan(snap,'library')['actions'],[])
        self.assertFalse(any(a['kind']=='library' for a in build_plan(snap,'official')['actions']))

    def test_clarified_guide_library_name_is_preserved_and_idempotent(self):
        snap=dict(guild=dict(id=GUILD),roles=[],channels=[channel(7,'game',4,None),
            channel(1,'攻略情報庫',15),channel(2,'攻略情報庫-fc'),channel(3,'nba-攻略情報庫'),
            channel(4,'攻略情報庫使用說明'),channel(5,'攻略情報庫-voice',2)])
        plan=build_plan(snap,'library')
        self.assertEqual(plan['matched_library'],3)
        self.assertEqual([a['body']['name'] for a in plan['actions']],
                         ['攻略情報庫🗂️','攻略情報庫-fc🗂️','nba-攻略情報庫🗂️'])
        for c in snap['channels'][1:4]:c['name']+='🗂️'
        again=build_plan(snap,'library')
        self.assertEqual(again['unchanged'],3)
        self.assertEqual(again['actions'],[])
