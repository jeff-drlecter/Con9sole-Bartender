import types
import unittest
from features.community_levels import build_level_notice_embed, DEFAULTS


class LevelNoticeBoxTests(unittest.TestCase):
    def test_matches_reference_box_and_keeps_guild_identity(self):
        member=types.SimpleNamespace(global_name='GaryKCT',name='gary',display_name='家用夠の加利',mention='<@10>',
            guild=types.SimpleNamespace(name='Con9sole【家用夠】',icon=types.SimpleNamespace(url='https://example.com/icon.png')))
        cfg={**DEFAULTS,'level_templates':{},'announcement_template':'恭喜 {user.ping} 升級! 依家你係 等級{level}'}
        embed=build_level_notice_embed(cfg,member,57,57)
        self.assertEqual(embed.title,'GaryKCT leveled up!')
        self.assertEqual(embed.description,'恭喜 <@10> 升級! 依家你係 等級57')
        self.assertEqual(embed.footer.text,'Con9sole【家用夠】')
        self.assertEqual(embed.footer.icon_url,'https://example.com/icon.png')
        self.assertEqual(embed.color.value,0xFFF0B3)

    def test_existing_milestone_templates_and_missing_icon_are_supported(self):
        member=types.SimpleNamespace(display_name='Jeff',mention='<@10>',guild=types.SimpleNamespace(name='Con9sole',icon=None))
        cfg={**DEFAULTS,'level_templates':{'15':'{user} 成為活躍會員，Lv.{level}'}}
        embed=build_level_notice_embed(cfg,member,15,15)
        self.assertEqual(embed.description,'Jeff 成為活躍會員，Lv.15')
        self.assertIsNone(embed.footer.icon_url)
