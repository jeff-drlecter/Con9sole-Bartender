"""Public controls exist without a scheduled article; retries cannot spam."""
import subprocess
import sys
import unittest


class NewsEntryTests(unittest.TestCase):
    def test_empty_queue_restart_and_uncertain_send(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio, tempfile
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, patch
from cogs.rss_delivery import RSSDelivery
from core.rss_digest import DigestConfig, DigestStore
from core.rss_preferences import PreferenceStore
from core.rss_routes import ROUTES

async def main():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {
        'RSS_DELIVERY_SOURCES':'', 'RSS_DIGEST_CONFIG':'',
        'RSS_CATEGORY_DELIVERY':'0', 'RSS_PERSONAL_PUBLIC':'1'}):
        cog = RSSDelivery(S())
        cog.category_delivery = True
        cog.digest_config = DigestConfig.from_dict(dict(channel_id=123, enabled=True, simulation=False))
        cog.sources = {'ps', 'xbox', '4gamers'}
        path = Path(tmp)/'prefs.db'
        cog.preferences = PreferenceStore(path)
        cog.route_stores = {k:DigestStore(Path(tmp)/(k+'.db')) for k in ROUTES}
        channels = {cid:S(id=cid, send=AsyncMock(return_value=S(id=cid+1)),
                         fetch_message=AsyncMock()) for _,cid,_ in ROUTES.values()}
        cog.target_channel = lambda cid=None: channels.get(cid)
        # Disabled delivery does not create public entries.
        cog.digest_config.enabled = False
        await cog.deliver.coro(cog)
        assert all(c.send.await_count == 0 for c in channels.values())
        cog.digest_config.enabled = True
        # Empty queues still get controls, outside any digest time window.
        with patch('cogs.rss_delivery.time.time', return_value=1805126400):
            await cog.deliver.coro(cog)
            for cid, channel in channels.items():
                assert channel.send.await_count == 1
                kwargs = channel.send.call_args.kwargs
                assert kwargs['silent'] and kwargs['allowed_mentions'].everyone is False
                assert kwargs['view'].is_persistent() and len(kwargs['view'].children) == 3
                assert cog.preferences.panel_status(cid) == ('posted', cid+1)
                assert '無需輸入指令' in channel.send.call_args.args[0]
            await cog.deliver.coro(cog)
            # Reopening persisted state must use the original card after restart.
            cog.preferences = PreferenceStore(path)
            cog.public_panels_checked.clear()
            await cog.deliver.coro(cog)
            assert all(c.send.await_count == 1 for c in channels.values())
            for cid,c in channels.items(): c.fetch_message.assert_awaited_once_with(cid+1)
        # An ambiguous send must not be repeated, even after restart.
        failed = S(id=88,send=AsyncMock(side_effect=TimeoutError()),fetch_message=AsyncMock())
        await cog.ensure_news_panel(failed,'Test')
        cog.preferences = PreferenceStore(path)
        cog.public_panels_checked.clear()
        await cog.ensure_news_panel(failed,'Test')
        assert failed.send.await_count == 1 and 'entry:88' in cog.errors
        # Existing but inaccessible/deleted entries are reported, never duplicated.
        cid = next(iter(channels))
        channels[cid].fetch_message.side_effect = RuntimeError('missing')
        await cog.ensure_news_panel(channels[cid],'Test')
        assert 'entry:'+str(cid) in cog.errors and channels[cid].send.await_count == 1
        # Missing destination permissions cannot create an entry.
        cog.target_channel = lambda cid=None: None
        await cog.deliver.coro(cog)
        assert all(c.send.await_count == 1 for c in channels.values())
asyncio.run(main())
'''], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
