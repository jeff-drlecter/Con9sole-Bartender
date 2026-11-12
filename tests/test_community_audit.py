import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import config
from core.community_audit import AuditStore, RETENTION_SECONDS
from cogs.community_audit import CommunityAudit, ROUTES, EXCLUDED, preview


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'audit.sqlite3'; self.store=AuditStore(self.path)

    def test_duplicate_key_claim_receipt_and_restart(self):
        self.store.append('message',{'title':'a'},key='delete:1')
        self.store.append('message',{'title':'b'},key='delete:1')
        self.assertEqual(len(self.store.pending('message')),1)
        self.assertTrue(self.store.claim(['delete:1']))
        self.assertFalse(self.store.claim(['delete:1']))
        other=AuditStore(self.path)
        self.assertEqual(other.summary()[0],{'uncertain':1})
        self.assertEqual(other.pending('message'),[])
        self.assertFalse(other.resolve('missing','retry'))
        self.assertTrue(other.resolve('delete:1','retry'))
        self.assertTrue(other.claim(['delete:1']))
        other.finish(['delete:1'],'sent',message_id=123)
        self.assertFalse(other.resolve('delete:1','retry'))
        self.assertEqual(AuditStore(self.path).summary()[0],{'sent':1})

    def test_pending_backoff_and_retention_preserve_unresolved(self):
        old=time.time()-RETENTION_SECONDS-100
        for key in ('pending','sent','uncertain'):
            self.store.append('voice',{'title':key},key=key,now=old)
        self.store.claim(['sent']); self.store.finish(['sent'],'sent')
        self.store.claim(['uncertain']); self.store.finish(['uncertain'],'uncertain')
        self.store.prune()
        self.assertEqual(self.store.summary()[0],{'pending':1,'uncertain':1})
        self.store.claim(['pending']); self.store.finish(['pending'],'pending',error='HTTP 403')
        self.assertEqual(self.store.pending('voice'),[])
        self.assertEqual(len(self.store.pending('voice',now=time.time()+100)),1)


class CogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.cog=CommunityAudit(NS())
        self.cog.store=AuditStore(Path(self.tmp.name)/'audit.sqlite3')
        self.channel=MagicMock(spec=discord.TextChannel)
        self.channel.send=AsyncMock(return_value=NS(id=123))
        self.cog.destination=MagicMock(return_value=self.channel)

    async def test_batched_silent_delivery_and_network_uncertainty(self):
        for i in range(3): await self.cog.emit('voice','測試',str(i))
        await CommunityAudit.deliver.coro(self.cog)
        self.channel.send.assert_awaited_once()
        kwargs=self.channel.send.await_args.kwargs
        self.assertEqual(len(kwargs['embeds']),3)
        self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'],[])
        self.assertTrue(kwargs['silent'])
        self.assertEqual(self.cog.store.summary()[0],{'sent':3})
        await self.cog.emit('message','測試','timeout')
        self.channel.send.side_effect=TimeoutError()
        await CommunityAudit.deliver.coro(self.cog)
        self.assertEqual(self.cog.store.summary()[0],{'sent':3,'uncertain':1})
        calls=self.channel.send.await_count
        await CommunityAudit.deliver.coro(self.cog)
        self.assertEqual(self.channel.send.await_count,calls)

    async def test_permissions_fail_closed_and_other_routes_continue(self):
        await self.cog.emit('voice','a','b'); await self.cog.emit('member','a','b')
        self.cog.destination.side_effect=lambda cat: (_ for _ in ()).throw(RuntimeError('bad route')) if cat=='voice' else self.channel
        await CommunityAudit.deliver.coro(self.cog)
        self.assertEqual(self.cog.store.summary()[0],{'pending':1,'sent':1})

    async def test_payload_without_cache_is_logged_without_inventing_content(self):
        self.cog.bot=NS(get_guild=lambda _:NS(get_channel_or_thread=lambda _:None))
        payload=NS(guild_id=config.GUILD_ID,channel_id=9,message_id=10,cached_message=None,data={'content':'new','edited_timestamp':'t'})
        await self.cog.on_raw_message_edit(payload)
        await self.cog.on_raw_message_edit(payload)
        rows=self.cog.store.pending('message'); self.assertEqual(len(rows),1)
        self.assertIn('未快取原文',rows[0][2]['description'])
        payload.data={'embeds':[]}; await self.cog.on_raw_message_edit(payload)
        self.assertEqual(len(self.cog.store.pending('message')),1)
        payload.data={'content':'new'}; payload.channel_id=next(iter(EXCLUDED))
        await self.cog.on_raw_message_edit(payload)
        self.assertEqual(len(self.cog.store.pending('message')),1)
        payload.channel_id=9; payload.guild_id=123
        await self.cog.on_raw_message_edit(payload)
        self.assertEqual(len(self.cog.store.pending('message')),1)

    async def test_bulk_is_one_event_and_delete_unknown_actor(self):
        payload=NS(guild_id=config.GUILD_ID,channel_id=9,message_ids={10,11},cached_messages=[])
        await self.cog.on_raw_bulk_message_delete(payload)
        self.assertEqual(len(self.cog.store.pending('message')),1)
        await self.cog.on_raw_message_delete(NS(guild_id=config.GUILD_ID,channel_id=9,message_id=12,cached_message=None))
        rows=self.cog.store.pending('message'); self.assertEqual(len(rows),2)
        self.assertIn('刪除操作者未確認',next(p['description'] for _,_,p in rows if p['title']=='訊息刪除'))

    async def test_embed_batch_stays_within_discord_limit(self):
        for i in range(5): await self.cog.emit('server','a','x'*3500)
        await CommunityAudit.deliver.coro(self.cog)
        self.assertLess(sum(len(e) for e in self.channel.send.await_args.kwargs['embeds']),6000)
        self.assertEqual(self.cog.store.summary()[0],{'pending':4,'sent':1})

    async def test_nsfw_preview_and_bot_messages_are_not_copied(self):
        message=NS(content='sensitive',channel=NS(is_nsfw=lambda:True),author=NS(bot=True))
        self.assertNotIn('sensitive',preview(message))
        await self.cog.on_raw_message_delete(NS(guild_id=config.GUILD_ID,channel_id=9,message_id=12,cached_message=message))
        self.assertEqual(self.cog.store.summary()[0],{})

    async def test_status_rejects_other_guild_before_reading_store(self):
        inter=NS(guild_id=1,guild=None,response=NS(send_message=AsyncMock()))
        self.assertFalse(await self.cog.authorized(inter))
        inter.response.send_message.assert_awaited_once()

    async def test_actual_destination_requires_private_channel_and_permissions(self):
        cog=CommunityAudit(NS())
        guild=NS(default_role=object(),me=object())
        channel=MagicMock(spec=discord.TextChannel)
        guild.get_channel=lambda _:channel
        cog.bot=NS(get_guild=lambda _:guild)
        channel.permissions_for.side_effect=lambda who:NS(view_channel=who is guild.me,send_messages=True,embed_links=True)
        self.assertIs(cog.destination('voice'),channel)
        channel.permissions_for.side_effect=None
        channel.permissions_for.return_value=NS(view_channel=True,send_messages=True,embed_links=True)
        with self.assertRaises(RuntimeError): cog.destination('voice')
