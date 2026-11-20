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

    def test_identity_keeps_readable_snapshot_and_role_reference(self):
        user=self.member(); role=NS(id=1417493340819292360,name='Con9sole-Bartender')
        label=who(user)+'\n'+role_label(role)
        self.assertIn(f'家用夠のAdmin（{safe(user.name)}）\n用戶 ID：`{user.id}`',label)
        self.assertNotIn(f'<@{user.id}>',label)
        self.assertIn('**Con9sole-Bartender**',label)
        self.assertIn('<@&1417493340819292360>',label)
        # Queued descriptions created by older releases still retain their ID footer.
        self.assertIn(f'成員 {user.id}',identity_footer(f'<@{user.id}>'))
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
        self.assertIn('用戶 ID：`7`',text)
        self.assertNotIn('@everyone',text)
        self.assertNotIn('<@&888>',text)
        self.assertEqual(identity_footer(text),'')
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
            self.assertIn(f'用戶 ID：`{user.id}`',card['description'])
            self.assertNotIn('url',card['author'])
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

    async def test_audit_actor_and_target_with_ids_only(self):
        guild=NS(id=config.GUILD_ID,get_member=lambda _:None)
        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        entry=NS(id=99,guild=guild,user=None,user_id=7,target=discord.Object(id=8),
                 action=discord.AuditLogAction.kick,reason=None,extra=None,before=NS(),after=NS())
        await cog.on_audit_log_entry_create(entry)
        description=cog.emit.await_args.args[2]
        for uid in (7, 8):
            self.assertIn(f'名稱未取得\n用戶 ID：`{uid}`',description)

    async def test_uncached_edit_snapshots_names_or_records_known_id(self):
        member=NS(id=7,name='player7',display_name='隊長')
        guild=NS(get_channel_or_thread=lambda _:None,get_member=lambda uid:member if uid==7 else None)
        cog=CommunityAudit(NS(get_guild=lambda _:guild)); cog.emit=AsyncMock()
        for raw, label in [
            ({'id':'7'}, '隊長（player7）'),
            ({'id':'8','global_name':'玩家','username':'player8'}, '玩家（player8）'),
            ({'id':'9','username':'player9'}, 'player9'),
            ({'id':'10'}, '名稱未取得'),
        ]:
            with self.subTest(raw=raw):
                event=NS(guild_id=config.GUILD_ID,channel_id=9,message_id=42,cached_message=None,
                         data={'author':raw,'content':'updated'})
                await cog.on_raw_message_edit(event)
                self.assertIn(f"作者：{label}\n用戶 ID：`{raw['id']}`",cog.emit.await_args.args[2])

    async def test_uncached_message_delete_audit_identifies_target_as_user(self):
        guild=NS(id=config.GUILD_ID,_state=NS(),get_member=lambda _:None)
        entry=discord.AuditLogEntry(
            guild=guild,users={},integrations={},app_commands={},automod_rules={},webhooks={},
            data={'id':'99','action_type':discord.AuditLogAction.message_delete.value,
                  'user_id':None,'target_id':'8'})
        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        await cog.on_audit_log_entry_create(entry)
        self.assertIn('**對象**\n名稱未取得\n用戶 ID：`8`',cog.emit.await_args.args[2])

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

    async def test_sdk_channel_audit_without_target_still_emits_known_details(self):
        guild=NS(id=config.GUILD_ID,_state=NS(),get_member=lambda _:None,get_channel=lambda _:None)
        for target_fields in ({'target_id':None},{}):
            with self.subTest(target_fields=target_fields):
                entry=discord.AuditLogEntry(
                    guild=guild,users={},integrations={},app_commands={},automod_rules={},webhooks={},
                    data={'id':'123456','action_type':11,'user_id':None,'reason':'synthetic reason',
                          'changes':[{'key':'name','old_value':'old','new_value':'new'}],**target_fields})
                # Exercise the actual locked SDK converter, not a mocked target.
                with self.assertRaises(TypeError):
                    _=entry.target
                cog=CommunityAudit(NS()); cog.emit=AsyncMock()
                await cog.on_audit_log_entry_create(entry)
                cog.emit.assert_awaited_once()
                args=cog.emit.await_args.args
                self.assertEqual(args[:2],('server','官方審核｜修改頻道'))
                self.assertIn('**對象**\n未提供',args[2])
                self.assertIn('synthetic reason',args[2])
                self.assertIn('old',args[2]); self.assertIn('new',args[2])
                self.assertNotIn('<#',args[2])
                self.assertEqual(cog.emit.await_args.kwargs['key'],'audit:123456')

    async def test_non_null_target_conversion_error_is_not_swallowed(self):
        class BrokenEntry:
            guild=NS(id=config.GUILD_ID)
            user=None
            user_id=None
            _target_id=123

            @property
            def target(self):
                raise TypeError('unrelated converter error')

        cog=CommunityAudit(NS()); cog.emit=AsyncMock()
        with self.assertRaisesRegex(TypeError,'unrelated converter error'):
            await cog.on_audit_log_entry_create(BrokenEntry())
        cog.emit.assert_not_awaited()
