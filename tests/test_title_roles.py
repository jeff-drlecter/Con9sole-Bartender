import tempfile
import types
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from features import drink_storage as storage,title_roles as store
from features.collection_milestones import select_title,collection_snapshot
from cogs.title_roles import TitleRoles,ConfirmTitle,Titles,AdminTitles,catalog


class Role:
    def __init__(self,id,position=1):
        self.id=id;self.position=position;self.permissions=discord.Permissions.none();self.colour=discord.Colour.default()
        self.hoist=False;self.mentionable=False;self.managed=False;self.members=[]
    def is_default(self):return False
    def __lt__(self,other):return self.position<other.position
    def __ge__(self,other):return self.position>=other.position


class TitleRoleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=patch.object(storage,'STATS_DB',Path(self.temp.name)/'stats')
        self.p.start();store.initialize()
        with storage.connect_sqlite(storage.STATS_DB) as db:
            for key,label in [('count:1','初嚐一杯'),('count:5','吧枱熟客')]:
                db.execute('INSERT INTO drink_milestones VALUES(?,?,?,?,?,?,?)',('1',10,key,label,1,None,'2026-11-08'))
        self.roles={10:Role(10,3),11:Role(11,4),90:Role(90,2)}
        self.member=types.SimpleNamespace(id=10,bot=False,joined_at=datetime(2026,1,1,tzinfo=timezone.utc),roles=[self.roles[90]],top_role=self.roles[90])
        async def add(role,**kwargs):self.member.roles.append(role)
        async def remove(role,**kwargs):self.member.roles.remove(role)
        self.member.add_roles=AsyncMock(side_effect=add);self.member.remove_roles=AsyncMock(side_effect=remove)
        self.guild=types.SimpleNamespace(id=1,owner_id=999,me=types.SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True),top_role=Role(100,100)),
            get_role=lambda rid:self.roles.get(rid),get_member=lambda uid:self.member if uid==10 else None,fetch_member=AsyncMock(return_value=self.member),chunked=True,members=[self.member])
        self.member.guild=self.guild
        self.cog=TitleRoles(MagicMock());self.cog.bot.get_cog.return_value=None
        store.bind(1,'count:1',10,20);store.bind(1,'count:5',11,20)

    def tearDown(self):self.p.stop();self.temp.cleanup()

    async def test_select_change_and_hide_preserve_game_roles(self):
        self.assertTrue(select_title(1,10,'count:1'))
        await self.cog.sync_user(self.guild,10)
        self.assertEqual({r.id for r in self.member.roles},{90,10})
        self.assertTrue(select_title(1,10,'count:5'))
        await self.cog.sync_user(self.guild,10)
        self.assertEqual({r.id for r in self.member.roles},{90,11})
        self.assertTrue(select_title(1,10,'none'))
        await self.cog.sync_user(self.guild,10)
        self.assertEqual({r.id for r in self.member.roles},{90})
        self.assertIsNone(store.queue_status(1,10))

    async def test_locked_title_never_queues_or_grants(self):
        self.assertFalse(select_title(1,10,'count:1000'))
        self.assertIsNone(store.queue_status(1,10));self.member.add_roles.assert_not_awaited()

    async def test_selection_and_job_are_atomic(self):
        select_title(1,10,'count:1')
        with patch('features.title_roles.enqueue_in',side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):select_title(1,10,'count:5')
        self.assertEqual(store.selected(1,10),'count:1')

    async def test_stale_completion_does_not_remove_newer_job(self):
        select_title(1,10,'count:1');old=store.pending(1)[0][1]
        select_title(1,10,'count:5')
        store.finish(1,10,old)
        self.assertIsNotNone(store.queue_status(1,10))
        await self.cog.sync_user(self.guild,10)
        self.assertEqual({r.id for r in self.member.roles},{90,11})

    async def test_unsafe_or_missing_role_holds_before_removing_old_role(self):
        self.member.roles.append(self.roles[10]);select_title(1,10,'count:5')
        self.roles[11].permissions=discord.Permissions(administrator=True)
        await self.cog.sync_user(self.guild,10)
        self.member.remove_roles.assert_not_awaited();self.member.add_roles.assert_not_awaited()
        self.assertTrue(store.queue_status(1,10)[0])
        self.roles[11].permissions=discord.Permissions.none();store.enqueue(1,10)
        await self.cog.sync_user(self.guild,10)
        self.assertEqual({r.id for r in self.member.roles},{90,11})

    async def test_role_api_failure_keeps_retry_job(self):
        select_title(1,10,'count:1');self.member.add_roles.side_effect=RuntimeError('offline')
        await self.cog.sync_user(self.guild,10)
        self.assertIsNotNone(store.queue_status(1,10))

    async def test_bulk_preview_is_read_only_and_changes_digest_on_mapping(self):
        select_title(1,10,'count:1')
        before={r.id for r in self.member.roles}
        rows,digest=await self.cog.bulk_plan(self.guild)
        self.assertEqual(rows[0][0],10);self.assertEqual({r.id for r in self.member.roles},before)
        store.bind(1,'count:1',None,20)
        _,new=await self.cog.bulk_plan(self.guild);self.assertNotEqual(digest,new)

    async def test_status_does_not_claim_synced_before_assignment(self):
        select_title(1,10,'count:1');rev=store.pending(1)[0][1];store.finish(1,10,rev)
        self.assertIn('尚未同步',await self.cog.status(self.guild,10,collection_snapshot(1,10)))

    async def test_role_safety_includes_color_group_mentions_and_level_roles(self):
        role=self.roles[10]
        self.assertTrue(store.safe_role(self.guild,role))
        for field,value in [('colour',discord.Colour.red()),('hoist',True),('mentionable',True),('managed',True)]:
            old=getattr(role,field);setattr(role,field,value)
            self.assertFalse(store.safe_role(self.guild,role));setattr(role,field,old)
        self.assertFalse(store.safe_role(self.guild,role,{10}))

    async def test_uncertain_role_creation_cannot_be_duplicated(self):
        store.begin_provision(1,'count:1',20)
        with self.assertRaises(ValueError):store.begin_provision(1,'count:1',20)
        store.bind(1,'count:1',10,20)
        self.assertNotIn('count:1',store.settings(1).get('provisioning',{}))

    async def test_theme_catalog_uses_real_award_ids(self):
        from features.theme_collections import themes
        self.assertTrue(all(t.award_id(t.targets[-1]) in catalog() for t in themes()))

    async def test_user_picker_has_no_admin_provisioning_controls(self):
        snap=collection_snapshot(1,10)
        view=Titles(self.cog,10,snap)
        labels={getattr(item,'label',None) for item in view.children}
        self.assertNotIn('建立標準稱號 Roles',labels)
        select=next(item for item in view.children if isinstance(item,discord.ui.Select))
        self.assertEqual({o.value for o in select.options},{'none','count:1','count:5'})
        view.stop()

    async def test_bulk_queue_commits_audited_preview_without_granting(self):
        rows=[(10,'count:1',[],[10])]
        store.enqueue_batch(1,[10],20,dict(rows=rows,digest='reviewed'))
        self.assertEqual(store.pending(1)[0][0],10)
        self.member.add_roles.assert_not_awaited()
        with storage.connect_sqlite(storage.STATS_DB) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM title_role_audit WHERE action='bulk_sync'").fetchone()[0],1)

    async def test_bulk_preview_refuses_unsafe_role_before_any_queue(self):
        select_title(1,10,'count:1');old=store.pending(1)[0][1];store.finish(1,10,old)
        self.roles[10].mentionable=True
        with self.assertRaises(ValueError):await self.cog.bulk_plan(self.guild)
        self.assertIsNone(store.queue_status(1,10))

    async def test_confirmation_rechecks_unlocked_title_and_permission(self):
        view=ConfirmTitle(self.cog,10,'count:1000')
        inter=MagicMock();inter.guild_id=1;inter.user.id=10;inter.guild=self.guild
        inter.response.defer=AsyncMock();inter.followup.send=AsyncMock()
        with patch('config.GUILD_ID',1):await view.children[0].callback(inter)
        self.assertIsNone(store.selected(1,10));self.member.add_roles.assert_not_awaited()
        view.stop()
