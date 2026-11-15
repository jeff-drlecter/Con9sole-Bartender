import tempfile
import unittest
from pathlib import Path
from core.delivery_health import record, snapshot, source_condition
from core.rss_digest import DigestStore, DigestConfig
from test_rss_digest import ts

class DeliveryHealthTests(unittest.TestCase):
    def test_restart_failure_recovery_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rss.db'
            store=DigestStore(path)
            self.assertEqual(snapshot(store),{})
            record(store,'ps','empty',obtained=True,now=10)
            record(store,'ps','source_failed',failed=True,now=20)
            record(store,'ps','attempting',now=30)
            row=snapshot(DigestStore(path))['ps']
            self.assertEqual(row['obtained'],10)
            self.assertEqual(row['failures'],1)
            self.assertNotIn('delivered',row)
            self.assertEqual(source_condition({'ps':row},['ps'],40,100),'failed')
            record(store,'xbox','empty',obtained=True,now=35)
            self.assertEqual(source_condition(snapshot(store),['ps','xbox'],40,100),'partial')
            record(store,'ps','obtained',obtained=True,now=40)
            self.assertEqual(snapshot(store)['ps']['last_failure'],20)
            self.assertEqual(snapshot(store)['ps']['failures'],0)
            self.assertEqual(source_condition(snapshot(store),['ps'],200,100),'stale')
            self.assertEqual(source_condition({},['ps'],200,100),'unknown')

    def test_empty_slot_does_not_reserve_later_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DigestStore(Path(tmp)/'rss.db'); cfg=DigestConfig.from_dict({})
            store.ingest('ps',[],ts(hour=10))
            self.assertEqual(store.schedule_result(cfg,{'ps'},ts(hour=18)),'outside_window')
            self.assertEqual(store.schedule_result(cfg,{'ps'},ts()),'empty')
            record(store,'schedule','empty',now=ts())
            self.assertIsNone(store.claim_batch(cfg,{'ps'},ts()))
            article=dict(key='a',title='PC update',summary='news',link='https://example.com/a',published=ts(minute=2))
            store.ingest('ps',[article],ts(minute=2))
            cfg.exclude_any=['PC']
            self.assertEqual(store.schedule_result(cfg,{'ps'},ts(minute=3)),'filtered_empty')
            cfg.exclude_any=[]
            batch=store.claim_batch(cfg,{'ps'},ts(minute=3))
            store.finish_batch(batch['slot'],'retry',ts(minute=3))
            self.assertEqual(store.schedule_result(cfg,{'ps'},ts(minute=3)),'retry')
            self.assertIsNone(store.claim_batch(cfg,{'ps'},ts(minute=3)))
            self.assertIsNotNone(store.claim_batch(cfg,{'ps'},ts(minute=5)))

class DeliveryPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_and_receipt_failure_never_resend(self):
        from types import SimpleNamespace as S
        from unittest.mock import AsyncMock, patch
        from cogs.rss_delivery import RSSDelivery
        import config
        with tempfile.TemporaryDirectory() as tmp:
            for failure in ('timeout','receipt'):
                store=DigestStore(Path(tmp)/(failure+'.db'));cfg=DigestConfig.from_dict({})
                store.ingest('ps',[],ts(hour=10))
                store.ingest('ps',[dict(key='a',title='news',summary='news',link='https://example.com/a',published=ts(hour=11))],ts(hour=11))
                cog=RSSDelivery(S());cog.errors={}
                channel=S(send=AsyncMock(side_effect=TimeoutError()) if failure=='timeout' else AsyncMock(return_value=S(id=7)))
                original=store.finish_batch
                if failure=='receipt': store.finish_batch=lambda *a: (_ for _ in ()).throw(OSError('fixture'))
                with patch('cogs.rss_delivery.time.time',return_value=ts()):
                    await cog.send_digest(channel,store,cfg,{'ps'},'',None)
                    await cog.send_digest(channel,store,cfg,{'ps'},'',None)
                self.assertEqual(channel.send.await_count,1)
                self.assertIn(store.batch_report()[0][1],('uncertain','sending'))
                if failure=='receipt': self.assertIn('health_write',cog.errors)

    async def test_stream_api_success_delivery_failure_then_recovery(self):
        from types import SimpleNamespace as S
        from unittest.mock import AsyncMock, patch
        from cogs.stream_alerts import StreamAlerts
        from core.twitch_alerts import AlertStore
        import asyncio
        with tempfile.TemporaryDirectory() as tmp:
            cog=StreamAlerts(S());cog.store=AlertStore(Path(tmp)/'streams.db')
            cog.store.add('tester','member');cog.store.state['enabled']=True
            entry=cog.store.state['entries']['tester'];entry['initialized']=True
            stream=dict(id='1',started_at='2026-11-15T00:00:00Z')
            cog.api=S(streams=AsyncMock(return_value={'tester':stream}),requests=1)
            cog.channel=lambda group:None
            cog.send_live=AsyncMock(side_effect=RuntimeError('fixture'))
            with patch('cogs.stream_alerts.time.time',return_value=1000):
                await cog.poll.coro(cog)
            health=cog.health_snapshot()['observations']
            self.assertEqual(health['api']['obtained'],1000)
            self.assertEqual(health['delivery']['result'],'partial_failure')
            cog.send_live=AsyncMock()
            with patch('cogs.stream_alerts.time.time',return_value=1400):
                await cog.poll.coro(cog)
            self.assertEqual(cog.health_snapshot()['observations']['delivery']['result'],'checked')
            self.assertEqual(cog.last_error,'')
            self.assertEqual(snapshot(AlertStore(cog.store.path))['account:tester']['last_failure'],1000)

    async def test_observation_failure_does_not_control_receipts(self):
        from types import SimpleNamespace as S
        from unittest.mock import AsyncMock, patch
        from cogs.rss_delivery import RSSDelivery
        with tempfile.TemporaryDirectory() as tmp:
            store=DigestStore(Path(tmp)/'rss.db');cfg=DigestConfig.from_dict({})
            store.ingest('ps',[],ts(hour=10))
            store.ingest('ps',[dict(key='a',title='news',summary='news',link='https://example.com/a',published=ts(hour=11))],ts(hour=11))
            cog=RSSDelivery(S());channel=S(send=AsyncMock(return_value=S(id=9)))
            with patch('cogs.rss_delivery.record',side_effect=OSError('fixture')), patch('cogs.rss_delivery.time.time',return_value=ts()):
                await cog.send_digest(channel,store,cfg,{'ps'},'',None)
            self.assertEqual(store.batch_report()[0][1],'sent')
            self.assertIn('health_write',cog.errors)
