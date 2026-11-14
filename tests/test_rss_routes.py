"""Production routing and message controls tested without live Discord writes."""
import subprocess
import sys
import unittest


class ProductionRoutesTests(unittest.TestCase):
    def test_routing_and_delivery(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio, tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch, AsyncMock
import config
from cogs.rss_delivery import RSSDelivery
from core.rss_digest import DigestConfig, DigestStore, HK
from core.rss_routes import ROUTES, RouteConfig
from core.rss_personal_ui import NewsCardPanel, PreferencesView
from core.rss_preferences import DEFAULT, PreferenceStore

async def main():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'RSS_DELIVERY_SOURCES':'', 'RSS_DIGEST_CONFIG':'', 'RSS_CATEGORY_DELIVERY':'0', 'RSS_PERSONAL_PUBLIC':'1'}):
        cog = RSSDelivery(S())
        cog.category_delivery = True
        cog.digest_config = DigestConfig.from_dict(dict(channel_id=123, simulation=False, enabled=True))
        cog.sources = {'ps','xbox','4gamers'}
        cog.store_news = object()
        cog.store_news_public = False
        assert not cog.store_news_available(S(channel_id=123))
        cog.store_news = None
        cog.preferences = PreferenceStore(Path(tmp)/'prefs.db')
        cog.store = DigestStore(Path(tmp)/'all.db')
        cog.route_stores = {k:DigestStore(Path(tmp)/(k+'.db')) for k in ROUTES}
        channels = {cid:S(send=AsyncMock(return_value=S(id=cid))) for _,cid,_ in ROUTES.values()}
        cog.target_channel = lambda cid=None: channels.get(cid)
        now = datetime(2026,11,14,19,0,tzinfo=HK).timestamp()
        def article(key, title='new game'):
            return dict(key=key,title=title,summary='game update',link='https://example.com/'+key,published=now)
        for key, (_, cid, sources) in ROUTES.items():
            source = next(iter(sources))
            store = cog.route_stores[key]
            store.ingest(source,[article('baseline-'+key)],now)
            assert store.preview(RouteConfig(cog.digest_config,key),sources,now) == []
            store.ingest(source,[article('new-'+key,'PC Steam update' if key=='pc' else 'new game '+key)],now)
        # Mixed-source console/mobile news must not be sent to PC.
        pc = RouteConfig(cog.digest_config,'pc')
        assert pc.score(dict(article('mobile','手機新遊戲'),source='4gamers')) is None
        assert pc.score(dict(article('ps','PS5 新遊戲'),source='ps')) is None
        # One bad destination does not block the others.
        psid = ROUTES['ps'][1]
        channels[psid].send.side_effect = TimeoutError()
        with patch('cogs.rss_delivery.time.time',return_value=now):
            await cog.deliver.coro(cog)
            for channel in channels.values():
                assert channel.send.await_count == 1
                kwargs = channel.send.call_args.kwargs
                assert isinstance(kwargs['view'],NewsCardPanel)
                assert kwargs['view'].is_persistent()
                assert kwargs['allowed_mentions'].everyone is False
                assert len(kwargs['view'].children)==3
            assert cog.route_stores['ps'].batch_report()[0][1]=='uncertain'
            # Reopen the databases as on restart: no duplicate sends.
            cog.route_stores = {k:DigestStore(Path(tmp)/(k+'.db')) for k in ROUTES}
            await cog.deliver.coro(cog)
            assert all(c.send.await_count==1 for c in channels.values())
            cog.digest_config.enabled=False
            await cog.deliver.coro(cog)
            assert all(c.send.await_count==1 for c in channels.values())
        # Production preference panels never offer fictional news.
        assert len(PreferencesView(cog,7,DEFAULT).children)==6
        # Button entry delegates to the normal member/channel visibility guard.
        cog.personal_access=AsyncMock(return_value=False)
        panel=NewsCardPanel(cog)
        assert not await panel.interaction_check(S())
        cog.personal_access.assert_awaited_once()
        cog.personal_access=AsyncMock(return_value=True)
        cog.channel_preferences_entry=AsyncMock()
        i=S(user=S(id=7),response=S(send_message=AsyncMock()))
        await panel.children[1].callback(i)
        assert i.response.send_message.call_args.kwargs['ephemeral']
        await panel.children[2].callback(i)
        cog.channel_preferences_entry.assert_awaited_once_with(i)
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
