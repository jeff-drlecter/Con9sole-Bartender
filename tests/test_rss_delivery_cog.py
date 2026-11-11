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
    guild = SimpleNamespace(id=config.GUILD_ID, me=object(), default_role=object())
    name = "rss-模擬區"
    public = False
    error = None
    sent = 0
    def permissions_for(self, member):
        return SimpleNamespace(view_channel=self.public if member is self.guild.default_role else True, send_messages=True, embed_links=True)
    async def send(self, *args, **kwargs):
        assert kwargs['allowed_mentions'].everyone is False
        if 'embed' in kwargs:
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
            channel.public = True
            assert cog.target_channel() is None
            channel.public = False
            channel.name = 'production-news'
            assert cog.target_channel() is None
            channel.name = 'rss-模擬區'
            assert cog.target_channel() is channel
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
            channel.error = None
            async def noop(*args, **kwargs): pass
            interaction = SimpleNamespace(channel_id=123,response=SimpleNamespace(defer=noop),followup=SimpleNamespace(send=noop))
            before = channel.sent
            await RSSDelivery.simulate.callback(cog,interaction)
            assert channel.sent >= before+3
            before = channel.sent
            await RSSDelivery.simulate.callback(cog,interaction)
            assert channel.sent == before  # manual command cooldown

asyncio.run(main())
'''], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_personal_panel_controls_and_guards(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import config
from cogs.rss_delivery import RSSDelivery
from core.rss_personal_ui import PersonalPanel, PreferencesView, KeywordModal, show_news
from core.rss_preferences import PreferenceStore,DEFAULT
from core.rss_digest import DigestStore
async def main():
    with patch.dict('os.environ',{'RSS_DELIVERY_SOURCES':'','RSS_DIGEST_CONFIG':''}):
        cog=RSSDelivery(SimpleNamespace())
    with tempfile.TemporaryDirectory() as tmp:
        cog.preferences=PreferenceStore(Path(tmp)/'prefs.db')
        cog.store=DigestStore(Path(tmp)/'rss.db')
        cog.digest_config.channel_id=123
        channel=SimpleNamespace(permissions_for=lambda user:SimpleNamespace(view_channel=True))
        cog.target_channel=lambda:channel
        i=SimpleNamespace(user=SimpleNamespace(id=1),guild_id=config.GUILD_ID,channel_id=123,
            response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        assert await cog.personal_access(i)
        panel=PersonalPanel(cog)
        assert panel.is_persistent()
        assert len(panel.children)==5
        from core.rss_featured_ui import render_featured
        import time
        worst=[dict(title='*'*1000,link='https://example.com/'+('x'*470),published=time.time(),reason='更新',offer=None)]*5
        cards=[render_featured(kind,worst,time.time(),compact=True) for kind in ('today','month')]
        cards.append(render_featured('hot',[],time.time(),compact=True))
        assert sum(len(c) for c in cards)<6000
        assert all(len(c.description)<=1500 for c in cards)
        view=PreferencesView(cog,1,DEFAULT)
        assert len(view.children)==6
        assert await view.interaction_check(i)
        i.user.id=2
        assert not await view.interaction_check(i)
        i.user.id=1
        i.channel_id=456
        assert not await cog.personal_access(i)
        i.channel_id=123
        cog.digest_config.simulation=False
        assert not await cog.personal_access(i)
        cog.digest_config.simulation=True
        cog.preferences.put(1,dict(DEFAULT,platforms=['pc'],stores=['epic'],kinds=['keep']))
        await show_news(cog,i,True)
        sent=i.followup.send.call_args.kwargs
        assert sent['ephemeral'] is True and len(sent['embed'].fields)==1
        assert 'Epic' in sent['embed'].fields[0].name
        assert sent['allowed_mentions'].everyone is False
        await show_news(cog,i)
        assert i.followup.send.call_args.kwargs['embed'] is None
        KeywordModal(cog,1,DEFAULT)
        cog.chart_ready=cog.feed_ready=True
        now=time.time()
        cog.preferences.put_chart(dict(asof=now,fetched=now,rows=[dict(rank=1,appid=730,name='Counter-Strike 2')]))
        channel.id=123
        channel.send=AsyncMock(return_value=SimpleNamespace(id=456))
        await cog.publish_featured(channel)
        await cog.publish_featured(channel)
        assert channel.send.await_count==1
        assert len(channel.send.call_args.kwargs['embeds'])==3
        assert cog.preferences.latest_featured()[1:] == ('posted',456)
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
