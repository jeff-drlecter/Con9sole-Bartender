import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import discord
import config
from cogs.community_audit import CommunityAudit
from core.community_audit import AuditStore
from features.audit_format import who, role_label, changes, identity_footer, safe


class ReadableTests(unittest.IsolatedAsyncioTestCase):
    def member(self):
        return NS(id=574555428403281940,name='jeff_drlecter',display_name='家用夠のAdmin',display_avatar='https://cdn.discordapp.com/embed/avatars/0.png')

    def test_identity_keeps_snapshot_clickable_reference_and_small_footer(self):
        user=self.member(); role=NS(id=1417493340819292360,name='Con9sole-Bartender')
        label=who(user)+'\n'+role_label(role)
        self.assertIn('**家用夠のAdmin**',label)
        self.assertIn('<@574555428403281940>',label)
        self.assertIn('**Con9sole-Bartender**',label)
        self.assertIn('<@&1417493340819292360>',label)
        self.assertIn('成員 574555428403281940',identity_footer(label))
        self.assertIn('身份組 1417493340819292360',identity_footer(label))
        self.assertNotIn('<@&',role_label(role,deleted=True))
        self.assertIn('Con9sole-Bartender',role_label(role,deleted=True))

    def test_permission_diff_and_role_changes_are_readable(self):
        old=discord.Permissions(send_messages=True)
        new=discord.Permissions(view_audit_log=True)
        before=NS(permissions=old,roles=[])
        after=NS(permissions=new,roles=[NS(id=123,name='Helpers')])
        text='\n'.join(changes(before,after,[('permissions','權限'),('roles','身份組')]))
        self.assertIn('允許：查看審核紀錄',text)
        self.assertIn('取消：發送訊息',text)
        self.assertIn('Helpers',text)
        self.assertIn('<@&123>',text)
        self.assertNotIn('Permissions value',text)

    def test_snapshot_names_cannot_inject_mentions(self):
        text=who(NS(id=7,display_name='@everyone <@&888> **Admin**'))
        self.assertIn('<@7>',text)
        self.assertNotIn('@everyone',text)
        self.assertNotIn('<@&888>',text)
        self.assertEqual(identity_footer(text),'成員 7')
        self.assertNotIn('<@999>',safe('copied <@999>'))

    async def test_avatar_persists_and_rendering_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cog=CommunityAudit(NS()); cog.store=AuditStore(Path(tmp)/'outbox.sqlite3')
            user=self.member(); channel=NS(send=AsyncMock(return_value=NS(id=123)))
            cog.destination=lambda _:channel
            await cog.emit('member','成員資料變更',who(user),subject=user)
            # Simulate restart while retaining the stored subject snapshot.
            cog.store=AuditStore(cog.store.path)
            await CommunityAudit.deliver.coro(cog)
            kwargs=channel.send.await_args.kwargs
            card=kwargs['embeds'][0].to_dict()
            self.assertEqual(card['author']['name'],'家用夠のAdmin')
            self.assertIn('icon_url',card['author'])
            self.assertIn(str(user.id),card['footer']['text'])
            self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'],[])
            self.assertTrue(kwargs['silent'])

    async def test_audit_actor_and_role_target_use_names_and_references(self):
        user=self.member(); role=NS(id=123,name='Helpers')
        guild=NS(id=config.GUILD_ID,get_member=lambda id:user if id==user.id else None,get_role=lambda id:role)
        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        entry=NS(id=99,guild=guild,user=user,user_id=user.id,target=role,
                 action=discord.AuditLogAction.role_update,reason=None,extra=None,
                 before=NS(permissions=discord.Permissions.none()),after=NS(permissions=discord.Permissions(view_audit_log=True)))
        await cog.on_audit_log_entry_create(entry)
        args=cog.emit.await_args.args
        self.assertEqual(args[1],'官方審核｜修改身份組')
        self.assertIn('家用夠のAdmin',args[2])
        self.assertIn('Helpers',args[2]); self.assertIn('<@&123>',args[2])
        self.assertIn('允許：查看審核紀錄',args[2])
        self.assertEqual(cog.emit.await_args.kwargs['key'],'audit:99')

    async def test_deleted_role_audit_keeps_last_name_when_cache_is_missing(self):
        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        guild=NS(id=config.GUILD_ID,get_member=lambda _:None,get_role=lambda _:None)
        entry=NS(id=99,guild=guild,user=None,user_id=None,target=discord.Object(id=123),
                 action=discord.AuditLogAction.role_delete,reason=None,extra=None,
                 before=NS(name='舊身份組'),after=NS())
        await cog.on_audit_log_entry_create(entry)
        text=cog.emit.await_args.args[2]
        self.assertIn('舊身份組',text); self.assertIn('已刪除',text)
        self.assertNotIn('<@&123>',text)
