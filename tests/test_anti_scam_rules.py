from types import SimpleNamespace as NS
import unittest
from features.anti_scam_rules import draft,ALERT_CHANNEL

class RuleDraftTests(unittest.TestCase):
    def make(self,rules=(),roles=None,channels=None):
        return draft(roles if roles is not None else [NS(id=10)],channels if channels is not None else [NS(id=ALERT_CHANNEL)], [NS(to_dict=lambda r=r:r) for r in rules],10)

    def test_preview_only_with_distinct_exemptions_and_no_punishment(self):
        plan=self.make()
        self.assertEqual(plan['mode'],'preview_only')
        self.assertEqual(plan['blockers'],[])
        link,spam=plan['proposals']
        self.assertEqual(link['payload']['exempt_roles'],['10'])
        self.assertEqual(spam['payload']['exempt_roles'],[])
        for p in plan['proposals']:
            self.assertFalse(p['payload']['enabled'])
            self.assertEqual([a['type'] for a in p['payload']['actions']],[2])

    def test_documented_examples_match_and_gaps_stay_visible(self):
        plan=self.make()
        self.assertTrue(all(e['expected_match']==e['local_match'] for e in plan['examples']))
        self.assertTrue(any('裸域名' in note for note in plan['notes']))

    def test_existing_spam_preserved_no_duplicate(self):
        row=dict(id='old',trigger_type=3,name='existing',enabled=False,actions=[])
        plan=self.make([row])
        self.assertEqual(len(plan['proposals']),1)
        self.assertEqual(plan['current_rules'],[row])

    def test_missing_role_channel_and_quota_are_blockers(self):
        plan=self.make([dict(trigger_type=1,name=str(i)) for i in range(6)],roles=[],channels=[])
        self.assertEqual(len(plan['blockers']),3)

    def test_duplicate_name_requires_review(self):
        plan=self.make([dict(trigger_type=1,name='Anti-scam | Unverified links')])
        self.assertTrue(plan['blockers'])


class RuleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_actor_does_not_read_settings(self):
        from unittest.mock import AsyncMock,patch
        from cogs.permission_audit import PermissionAudit
        guild=NS(fetch_roles=AsyncMock(),fetch_channels=AsyncMock(),fetch_automod_rules=AsyncMock())
        inter=NS(guild=guild,response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        cog=PermissionAudit(None)
        with patch.object(cog,'authorized',AsyncMock(return_value=False)):
            await PermissionAudit.rules.callback(cog,inter)
        guild.fetch_roles.assert_not_awaited();guild.fetch_automod_rules.assert_not_awaited()
        self.assertTrue(inter.followup.send.call_args.kwargs['ephemeral'])

    async def test_revoked_actor_cannot_receive_draft(self):
        from unittest.mock import AsyncMock,patch
        from cogs.permission_audit import PermissionAudit
        guild=NS(fetch_roles=AsyncMock(return_value=[]),fetch_channels=AsyncMock(return_value=[]),fetch_automod_rules=AsyncMock(return_value=[]))
        inter=NS(guild=guild,response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        cog=PermissionAudit(None)
        with patch.object(cog,'authorized',AsyncMock(side_effect=[True,False])):
            await PermissionAudit.rules.callback(cog,inter)
        self.assertNotIn('file',inter.followup.send.call_args.kwargs)
