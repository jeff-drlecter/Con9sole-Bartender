import asyncio
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from quick_bar_fakes import interaction
from core.action_guard import shared_async_lock
from core.sqlite_storage import connect_sqlite
from cogs.confession import Confession
from cogs.update_publisher import DraftReviewView, EditDraftModal
from cogs.teams import Teams, TeamState
from cogs import duplicate
from features.update_publisher import AnnouncementDraft
from features import drink_storage as storage, drink_leaderboard as leaderboard, menu_stats
from cogs.twitch_relay import split_payload
from cogs import activity_reminder as ar


class FullAuditFixes(unittest.IsolatedAsyncioTestCase):
    async def test_readonly_confession_is_rejected_before_posting(self):
        cog=Confession(MagicMock()); cog._target_channel=AsyncMock()
        i=interaction(can_send=False)
        await cog.submit_confession(i,'test')
        cog._target_channel.assert_not_awaited()
        i.response.send_message.assert_awaited_once()

    async def test_fixed_confession_destination_does_not_fall_back(self):
        cog=Confession(MagicMock()); i=interaction()
        i.client.get_channel.return_value=None
        i.client.fetch_channel=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404,reason='gone'),'gone'))
        with patch('cogs.confession.CONFESSION_CHANNEL_ID',123):
            self.assertIsNone(await cog._target_channel(i))

    async def test_cancel_cannot_claim_unpublished_while_publishing(self):
        view=DraftReviewView(owner_id=10,guild_id=1,draft=AnnouncementDraft('feature','title','body'),games=[])
        view.publishing=True; i=interaction()
        await view.cancel_draft.callback(i)
        self.assertFalse(view.cancelled)
        i.response.edit_message.assert_not_awaited()
        i.response.send_message.assert_awaited_once()
        view.stop()

    async def test_stale_modal_cannot_edit_after_cancellation(self):
        view=DraftReviewView(owner_id=10,guild_id=1,draft=AnnouncementDraft('feature','title','body'),games=[])
        modal=EditDraftModal(view); view.cancelled=True
        i=interaction()
        with patch('cogs.update_publisher._publisher_access_allowed',return_value=True):
            await modal.on_submit(i)
        self.assertEqual(view.draft.body,'body')
        i.response.send_message.assert_awaited_once(); view.stop()

    async def test_legacy_collection_counts_on_collection_board(self):
        with tempfile.TemporaryDirectory() as d,patch.object(storage,'STATS_DB',Path(d)/'db'),patch.object(leaderboard,'STATS_DB',Path(d)/'db'):
            storage.init_drink_events_db()
            with connect_sqlite(storage.STATS_DB) as conn:
                conn.execute("INSERT INTO drink_collection VALUES ('1',7,'Old','舊','R','2026-01-01')")
                conn.execute("INSERT INTO drink_collection VALUES ('2',9,'Other','其他','R','2026-01-01')")
            rows=leaderboard.fetch_top_collectors(1)
            self.assertEqual([(r.member_id,r.total) for r in rows],[(7,1)])

    async def test_stats_do_not_wait_for_database(self):
        started=__import__('threading').Event(); release=__import__('threading').Event()
        def slow(*args):
            started.set(); release.wait(2)
        try:
            with patch.object(menu_stats,'record_usage_sync',side_effect=slow):
                await asyncio.wait_for(menu_stats.record_usage('menu'),0.2)
                await asyncio.sleep(0.01)
                self.assertTrue(started.is_set())
                release.set()
                await menu_stats.run_stats(lambda:None)
        finally:
            release.set()

    async def test_voice_lock_is_shared_across_instances(self):
        self.assertIs(shared_async_lock('vc',1),shared_async_lock('vc',1))
        self.assertIsNot(shared_async_lock('vc',1),shared_async_lock('vc',2))

    async def test_dirty_team_is_refreshed_without_expiring(self):
        cog=object.__new__(Teams); state=TeamState(1,2,'game',3,4,message_id=5)
        message=types.SimpleNamespace(edit=AsyncMock())
        channel=types.SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        cog.bot=types.SimpleNamespace(wait_until_ready=AsyncMock(),is_closed=MagicMock(side_effect=[False,True]),get_channel=lambda _:channel)
        cog.states={5:state}; cog.views={5:types.SimpleNamespace(lock=asyncio.Lock())}; cog.dirty={5}
        with patch('cogs.teams.asyncio.sleep',AsyncMock()):
            await cog._sweeper_loop()
        message.edit.assert_awaited_once()
        self.assertIn(5,cog.states); self.assertFalse(cog.dirty)

    async def test_game_duplicate_is_rejected_before_creating_resources(self):
        guild=MagicMock(); guild.id=1; guild.categories=[types.SimpleNamespace(name='FC')]
        guild.create_category=AsyncMock(); guild.create_role=AsyncMock()
        with self.assertLogs(duplicate.log,level='ERROR'),self.assertRaises(RuntimeError):
            await duplicate.add_new_game(MagicMock(),guild,'fc')
        guild.create_category.assert_not_awaited(); guild.create_role.assert_not_awaited()

    async def test_removed_schedule_snapshot_is_ignored(self):
        cog=object.__new__(ar.ActivityReminder); cog.sent_cache={}
        schedule=ar.Schedule([2],'12:00'); activity=ar.Activity('a','game',1,2,[])
        channel=types.SimpleNamespace(send=AsyncMock())
        await cog._send_if_needed(None,channel,types.SimpleNamespace(id=2),activity,schedule,ar._now(),'start')
        channel.send.assert_not_awaited()

    async def test_unicode_chunks_preserve_text_and_byte_limit(self):
        text='廣東話🎮'*1000
        chunks=split_payload(text,300)
        self.assertEqual(''.join(chunks),text)
        self.assertTrue(all(len(c.encode('utf-8'))<=300 for c in chunks))

    async def test_new_category_is_created_with_permissions_already_applied(self):
        guild=MagicMock(); guild.id=1; guild.roles=[]; guild.categories=[]
        guild.fetch_channels=AsyncMock(return_value=[])
        role=MagicMock(); role.id=7; role.mention='<@&7>'
        category=MagicMock(); category.id=8
        guild.create_role=AsyncMock(return_value=role)
        guild.create_category=AsyncMock(return_value=category)
        template=types.SimpleNamespace(id=50)
        with patch.object(duplicate,'_get_template_category',AsyncMock(return_value=template)),patch.object(duplicate,'_record_game_announcement'):
            await duplicate.add_new_game(MagicMock(),guild,'FC')
        self.assertIn('overwrites',guild.create_category.call_args.kwargs)
        self.assertFalse(guild.create_category.call_args.kwargs['overwrites'][guild.default_role].view_channel)
        category.edit.assert_not_called()

    async def test_collection_rarity_second_page_exposes_previously_hidden_row(self):
        from features import drink_embeds as embeds
        rows=[{'drink_eng':f'Unique{i}', 'drink_zh':f'酒{i}','rarity':'R', 'self_count':1,'given_count':0,'received_count':0} for i in range(13)]
        with patch.object(embeds,'fetch_collection_rows',return_value=rows):
            embed=embeds.build_drink_collection_rarity_embed(types.SimpleNamespace(id=1),types.SimpleNamespace(id=7,display_name='Jeff'),'R',1)
        self.assertIn('Unique12',embed.description)
        self.assertNotIn('Unique0',embed.description)
        self.assertIn('2/2',embed.footer.text)

    async def test_invalid_cooldown_is_backed_up_without_losing_valid_user(self):
        from features import drink_state
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            original=b'{"cooldowns":{"1":123,"2":"oops"},"gift_cooldowns":{}}'
            path.write_bytes(original)
            with patch.object(drink_state,'DRINK_STATE_PATH',path),self.assertLogs(drink_state.log,level='ERROR'):
                state=drink_state._load_drink_state()
            self.assertEqual(state['cooldowns'],{'1':123.0})
            self.assertEqual(next(Path(d).glob('*.invalid-schema.*')).read_bytes(),original)

    async def test_role_slash_bulk_requires_confirmation(self):
        from cogs.role import RoleManager
        cog=RoleManager(MagicMock()); cog._apply_role_change=AsyncMock()
        cog.bot.get_cog.return_value=MagicMock()
        role=MagicMock(spec=discord.Role); role.id=123; role.members=[]
        i=interaction(); i.guild.get_role.return_value=role
        with patch('features.role_tools.RoleConfirmView') as view,patch('features.role_tools.build_confirm_embed'):
            await RoleManager.role_grant.callback(cog,i,'123',None,role,False)
        view.assert_called_once(); cog._apply_role_change.assert_not_awaited()
