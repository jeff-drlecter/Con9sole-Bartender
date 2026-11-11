"""Run against real discord.py in isolation from other tests' module stubs."""
import subprocess
import sys
import unittest


class DeliveryCogTests(unittest.TestCase):
    def test_disabled_and_delivery_outcomes(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import discord
import config
from cogs.rss_delivery import RSSDelivery
from core.rss_delivery import DeliveryStore

class Channel:
    guild = SimpleNamespace(id=config.GUILD_ID, me=object())
    error = None
    sent = 0
    def permissions_for(self, member):
        return SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    async def send(self, **kwargs):
        assert kwargs['allowed_mentions'].everyone is False
        if self.error: raise self.error
        self.sent += 1
        return SimpleNamespace(id=123)

async def main():
    channel = Channel()
    bot = SimpleNamespace(get_channel=lambda cid:channel)
    with patch.dict('os.environ', {'RSS_DELIVERY_SOURCES':''}):
        cog = RSSDelivery(bot)
    await cog.cog_load()
    assert cog.store is None and cog.session is None
    assert not cog.poll.is_running() and not cog.deliver.is_running()
    await cog.cog_unload()
    with tempfile.TemporaryDirectory() as tmp:
        cog.sources = {'ps'}
        cog.store = DeliveryStore(Path(tmp)/'queue.db')
        import time
        now=time.time()
        cog.store.ingest('ps',[],now)
        def article(key): return dict(key=key,title='news',summary='body',link='https://example.com/'+key,published=now)
        with patch('cogs.rss_delivery.discord.TextChannel', Channel):
            cog.store.ingest('ps',[article('one')],now)
            await cog.deliver.coro(cog)
            assert ('ps','sent',1) in cog.store.report()
            await cog.deliver.coro(cog)
            assert channel.sent == 1
            cog.store.ingest('ps',[article('two')],now)
            channel.error = asyncio.TimeoutError()
            await cog.deliver.coro(cog)
            assert ('ps','uncertain',1) in cog.store.report()
            await cog.deliver.coro(cog)
            assert channel.sent == 1
            cog.store.ingest('ps',[article('three')],now)
            channel.error = discord.HTTPException(SimpleNamespace(status=429,reason='rate limit'), 'slow down')
            await cog.deliver.coro(cog)
            assert ('ps','retry',1) in cog.store.report()
asyncio.run(main())
'''], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
