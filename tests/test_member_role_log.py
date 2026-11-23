import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import discord

import config
from cogs.community_audit import CommunityAudit
from core.community_audit import AuditStore, ROLE_AUDIT_WAIT
from features.role_audit_reason import encode_role_audit_reason


class MemberRoleLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'audit.sqlite3'
        self.role = NS(id=config.VERIFIED_ROLE_ID, name='Verified')
        self.bot = NS(id=11, name='Bartender', bot=True)
        self.target = NS(id=22, name='Player', bot=False)
        self.staff = Mock(spec=discord.Member)
        self.staff.id, self.staff.name, self.staff.display_name, self.staff.bot = 33, 'staff', 'Staff', False
        self.staff.guild_permissions = discord.Permissions(administrator=True)
        self.staff.roles = []
        self.people = {m.id: m for m in (self.bot, self.target, self.staff)}
        self.guild = NS(id=config.GUILD_ID, get_member=self.people.get)
        self.cog = CommunityAudit(NS(user=self.bot))
        self.cog.store = AuditStore(self.path)

    async def audit(self, executor, reason=None, *, key=100, remove=False):
        added, removed = ([], [self.role]) if remove else ([self.role], [])
        event = NS(id=key, action=discord.AuditLogAction.member_role_update, guild=self.guild,
                   user=executor, user_id=getattr(executor, 'id', None), target=self.target,
                   reason=reason, extra=None, before=NS(roles=removed), after=NS(roles=added))
        await self.cog.on_audit_log_entry_create(event)

    async def observe(self, *, remove=False):
        base = dict(id=self.target.id, name=self.target.name, guild=self.guild)
        before, after = ([], [self.role]) if not remove else ([self.role], [])
        await self.cog.on_member_update(NS(**base, roles=before), NS(**base, roles=after))

    def cards(self, category='member', later=False):
        now = time.time() + (ROLE_AUDIT_WAIT + 1 if later else 0)
        return {key: payload['description'] for key, _, payload in self.cog.store.pending(category, now=now, limit=20)}

    async def test_welcome_self_and_staff_actions_name_the_initiator_and_bot(self):
        for key, (actor, kind, op, label) in enumerate([
            (self.target, 'self', 'verification_grant', '會員自助（我是人類）'),
            (self.staff, 'helper', 'verification_revoke', 'Helper 經 Bot'),
            (self.staff, 'admin', 'role_grant', '管理員經 Bot'),
        ], 1):
            await self.audit(self.bot, encode_role_audit_reason(actor.id, kind, op),
                             key=key, remove=op.endswith('revoke'))
            card = self.cards()[f'member-role-audit:{key}']
            for expected in (label, f'**發起人**　{actor.name.title()}', '**執行帳戶**　Bartender',
                             '**受影響會員**　Player', '移除身份組' if op.endswith('revoke') else '新增身份組'):
                self.assertIn(expected, card)

    async def test_native_admin_and_other_bot_cannot_spoof_our_reason(self):
        reason = encode_role_audit_reason(self.target.id, 'self', 'verification_grant')
        await self.audit(self.staff, reason)
        self.assertIn('Discord 直接操作（記錄時為管理員）', self.cards()['member-role-audit:100'])
        other = NS(id=88, name='Other Bot', bot=True)
        await self.audit(other, reason, key=101)
        self.assertIn('其他 Bot 執行', self.cards()['member-role-audit:101'])
        self.assertNotIn('會員自助', self.cards()['member-role-audit:101'])

    async def test_missing_context_stays_unknown_and_private_reasons_stay_in_server_log(self):
        await self.audit(self.bot, 'Private staff reconciliation')
        self.assertIn('未有可核實的發起人紀錄', self.cards()['member-role-audit:100'])
        self.assertNotIn('Private staff', self.cards()['member-role-audit:100'])
        self.assertIn('Private staff', self.cards('server')['audit:100'])
        await self.audit(self.bot, encode_role_audit_reason(99, 'self', 'verification_grant'), key=101)
        self.assertNotIn('會員自助', self.cards()['member-role-audit:101'])
        await self.audit(None, key=102)
        self.assertIn('來源未確認', self.cards()['member-role-audit:102'])
        reason = encode_role_audit_reason(self.target.id, 'self', 'verification_grant')
        await self.audit(self.bot, reason, key=103, remove=True)
        self.assertNotIn('會員自助', self.cards()['member-role-audit:103'])
        self.role = NS(id=71, name='Game')
        await self.audit(self.bot, reason, key=104)
        self.assertNotIn('會員自助', self.cards()['member-role-audit:104'])

    async def test_audit_before_or_after_observation_and_restart(self):
        await self.observe()
        self.assertEqual(self.cards(), {})
        self.cog.store = AuditStore(self.path)
        await self.audit(self.staff)
        await self.audit(self.staff)  # Duplicate Discord entry.
        await self.audit(self.staff, key=101, remove=True)
        await self.observe(remove=True)
        self.assertEqual(set(self.cards(later=True)), {'member-role-audit:100','member-role-audit:101'})
        self.assertEqual(set(self.cards('server')), {'audit:100','audit:101'})

    async def test_missing_or_different_audit_preserves_unattributed_observation(self):
        await self.observe()
        await self.audit(self.staff, remove=True)
        self.assertEqual(len(self.cards(later=True)), 2)
        observed = next(text for text in self.cards(later=True).values() if '操作來源未確認' in text)
        self.assertIn('新增身份組', observed)
        self.assertNotIn('Staff', observed)

    async def test_late_audit_preserves_already_dispatched_observation(self):
        await self.observe()
        key, = self.cards(later=True)
        self.assertTrue(self.cog.store.claim([key]))
        self.cog.store.finish([key], 'sent', message_id=700)
        await self.audit(self.staff)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT state,message_id FROM audit_events WHERE id=?', (key,)).fetchone(), ('sent',700))
        self.assertEqual(set(self.cards()), {'member-role-audit:100'})
