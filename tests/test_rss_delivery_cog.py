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
from core.rss_digest import DigestStore, DigestConfig, HK
from datetime import datetime

class Channel:
    guild = SimpleNamespace(id=config.GUILD_ID, me=object())
    error = None
    sent = 0
    def permissions_for(self, member):
        return SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    async def send(self, **kwargs):
        assert kwargs['allowed_mentions'].everyone is False
        assert len(kwargs['embed']) <= 6000
        assert all(len(f.value)<=1024 for f in kwargs['embed'].fields)
        if self.error: raise self.error
        self.sent += 1
        return SimpleNamespace(id=123)

async def main():
    # Worst-case eight-item rendering stays within Discord's aggregate budget.
    huge = dict(title='*'*1000, summary='*'*8000, link='https://example.com/'+('a'*470), source='ps',
                offer=dict(kind='keep',region='*'*80,deadline=2000000000))
    rendered = RSSDelivery.render(dict(kind='digest',articles=[huge]*8),2000000000)
    assert len(rendered)<=6000
    assert all(len(f.value)<=1024 for f in rendered.fields)
    channel = Channel()
    bot = SimpleNamespace(get_channel=lambda cid:channel)
    with patch.dict('os.environ', {'RSS_DELIVERY_SOURCES':'', 'RSS_DIGEST_CONFIG':''}):
        cog = RSSDelivery(bot)
    await cog.cog_load()
    assert cog.store is None and cog.session is None
    assert not cog.poll.is_running() and not cog.deliver.is_running()
    await cog.cog_unload()
    with tempfile.TemporaryDirectory() as tmp:
        cog.sources = {'ps'}
        cog.store = DigestStore(Path(tmp)/'queue.db')
        cog.digest_config = DigestConfig.from_dict({'enabled':True,'channel_id':123})
        import time
        now=datetime(2026,11,12,19,0,tzinfo=HK).timestamp()
        cog.store.ingest('ps',[],now)
        def article(key): return dict(key=key,title='news',summary='body',link='https://example.com/'+key,published=now)
        with patch('cogs.rss_delivery.discord.TextChannel', Channel), patch('cogs.rss_delivery.time.time', return_value=now) as clock:
            cog.store.ingest('ps',[article('one')],now)
            await cog.deliver.coro(cog)
            assert ('ps','sent',1) in cog.store.report()
            await cog.deliver.coro(cog)
            assert channel.sent == 1
            now += 86400
            clock.return_value = now
            cog.store.ingest('ps',[article('two')],now)
            channel.error = asyncio.TimeoutError()
            await cog.deliver.coro(cog)
            assert ('ps','uncertain',1) in cog.store.report()
            await cog.deliver.coro(cog)
            assert channel.sent == 1
            now += 86400
            clock.return_value = now
            cog.store.ingest('ps',[article('three')],now)
            channel.error = discord.HTTPException(SimpleNamespace(status=429,reason='rate limit'), 'slow down')
            await cog.deliver.coro(cog)
            assert cog.store.batch_report()[0][1] == 'retry'
asyncio.run(main())
'''], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
