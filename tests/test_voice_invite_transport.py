"""Exercise the pinned adapter with real HTTPClient buckets and a synthetic wire."""
import asyncio
import json
import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch

import aiohttp
import discord
from discord.http import HTTPClient, Route
from features import voice_invites as invites, voice_invite_transport as transport


class Response:
    def __init__(self, status=200, data=None, error=None, headers=None):
        self.status, self.data, self.error = status, data, error
        self.headers={'content-type':'application/json', **(headers or {})}
        self.reason='synthetic'
    async def __aenter__(self):
        if self.error: raise self.error
        return self
    async def __aexit__(self,*args): pass
    async def text(self,**kwargs): return json.dumps(self.data)


class Wire:
    timeout=aiohttp.ClientTimeout(total=60)
    def __init__(self,response): self.response=response; self.posts=[]
    def request(self,method,url,**kwargs):
        # Model a server commit before loss of the response. A second call would
        # create another unique code; assertions count calls at this boundary.
        self.posts.append((method,url,kwargs))
        return self.response


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self,response):
        self.http=HTTPClient(asyncio.get_running_loop())
        self.http._global_over=asyncio.Event(); self.http._global_over.set()
        self.wire=Wire(response); self.http._HTTPClient__session=self.wire
        self.voice=N(id=10,guild=N(id=1),category_id=20,_state=N(http=self.http))
        self.destination=N(id=30,guild=self.voice.guild,category_id=20)
        self.session={'id':'synthetic','destination':30,
                      'voice_invite':{'state':'requested','requester':7,'voice':10,'trial_revision':'a'*32}}
        self.saved=[]
        self.cog=N(bot=N(user=N(id=42),get_channel=lambda cid:self.voice if cid==10 else self.destination),
            state={'settings':{'routes':{'20':30}},'voice_invite_trial':dict(schema=1,enabled=True,guild=1,category=20,destination=30,testers=[7],revision='a'*32)},
            save=lambda:self.saved.append(dict(self.session['voice_invite'])))

    async def prepare(self):
        with patch.object(invites,'authorize',new=AsyncMock(return_value=(self.voice,self.destination))):
            await invites.prepare(self.cog,self.voice,self.session)

    async def asyncTearDown(self):
        for task in tuple(transport._background): task.cancel()
        await asyncio.gather(*tuple(transport._background),return_exceptions=True)

    async def test_ambiguous_committed_responses_never_retry_post(self):
        for failure in [500,502,504,524,OSError(54,'reset'),asyncio.TimeoutError(),asyncio.CancelledError(),307]:
            with self.subTest(failure=type(failure).__name__ if not isinstance(failure,int) else failure):
                response=Response(status=failure if isinstance(failure,int) else 200,
                    data={'message':'committed response lost'},error=None if isinstance(failure,int) else failure)
                self.fixture(response)
                with self.assertRaises((discord.HTTPException,OSError,asyncio.CancelledError)):
                    await self.prepare()
                self.assertEqual(len(self.wire.posts),1)
                self.assertEqual(self.session['voice_invite']['state'],'uncertain')
                self.assertNotIn('code',self.session['voice_invite'])
                await self.prepare()  # A later tick or restarted journal must not replay.
                self.assertEqual(len(self.wire.posts),1)

    async def test_success_uses_shared_auth_proxy_bucket_and_no_redirects(self):
        self.fixture(Response(data={'code':'only-code'},headers={
            'X-Ratelimit-Bucket':'voice-bucket','X-Ratelimit-Remaining':'4',
            'X-Ratelimit-Limit':'5','X-Ratelimit-Reset-After':'0.01'}))
        self.http.proxy='http://synthetic.invalid'
        self.http.proxy_auth=aiohttp.BasicAuth('fixture','fixture')
        await self.prepare()
        method,url,kwargs=self.wire.posts[0]
        self.assertEqual(method,'POST'); self.assertTrue(url.endswith('/channels/10/invites'))
        self.assertEqual(json.loads(kwargs['data']),dict(max_age=3600,max_uses=0,temporary=False,unique=True))
        self.assertFalse(kwargs['allow_redirects']); self.assertEqual(kwargs['timeout'].total,30)
        self.assertIs(kwargs['proxy_auth'],self.http.proxy_auth)
        self.assertEqual(kwargs['proxy'],self.http.proxy)
        self.assertEqual(self.saved[-2]['state'],'uncertain')
        self.assertEqual(self.session['voice_invite']['code'],'only-code')
        route=Route('POST','/channels/{channel_id}/invites',channel_id=10)
        self.assertEqual(self.http._bucket_hashes[route.key],'voice-bucket')
        self.assertEqual(self.http._buckets['voice-bucket:10'].remaining,4)

    async def test_journal_and_presence_fence_are_after_global_and_route_gates(self):
        self.fixture(Response(data={'code':'only-code'}))
        self.http._global_over.clear()
        route=Route('POST','/channels/{channel_id}/invites',channel_id=10)
        bucket=self.http.get_ratelimit(f'{route.key}:{route.major_parameters}')
        bucket.remaining=0; bucket.reset_after=0.01
        bucket.expires=asyncio.get_running_loop().time()+0.01
        check_calls=[]
        def check(): check_calls.append('checked')
        with patch.object(invites,'authorize',new=AsyncMock(return_value=(self.voice,self.destination))):
            task=asyncio.create_task(invites.prepare(self.cog,self.voice,self.session,check=check))
            await asyncio.sleep(0)
            self.assertEqual(self.session['voice_invite']['state'],'requested')
            self.assertFalse(self.wire.posts)
            self.http._global_over.set()
            await task
        self.assertGreaterEqual(len(check_calls),3)
        self.assertEqual(len(self.wire.posts),1)

    async def test_presence_change_while_gate_waits_prevents_any_post(self):
        self.fixture(Response(data={'code':'must-not-create'}))
        self.http._global_over.clear(); changed=False
        def check():
            if changed: raise invites.PresenceChanged('changed')
        with patch.object(invites,'authorize',new=AsyncMock(return_value=(self.voice,self.destination))):
            task=asyncio.create_task(invites.prepare(self.cog,self.voice,self.session,check=check))
            await asyncio.sleep(0); changed=True; self.http._global_over.set()
            with self.assertRaises(invites.PresenceChanged): await task
        self.assertFalse(self.wire.posts)
        self.assertEqual(self.session['voice_invite']['state'],'requested')

    async def test_trial_disabled_while_global_gate_waits_never_posts(self):
        self.fixture(Response(data={'code':'must-not-create'}))
        self.http._global_over.clear()
        with patch.object(invites,'authorize',new=AsyncMock(return_value=(self.voice,self.destination))):
            task=asyncio.create_task(invites.prepare(self.cog,self.voice,self.session))
            await asyncio.sleep(0)
            self.cog.state['voice_invite_trial']={'schema':1,'enabled':False}
            self.http._global_over.set()
            await task
        self.assertFalse(self.wire.posts)
        self.assertTrue(self.session['voice_invite']['scope_stopped'])

    async def test_definitive_forbidden_and_validated_global_429_are_distinct(self):
        self.fixture(Response(status=403,data={'message':'denied'}))
        with self.assertRaises(discord.Forbidden): await self.prepare()
        self.assertEqual(self.session['voice_invite']['state'],'denied')
        self.assertEqual(len(self.wire.posts),1)
        self.fixture(Response(status=429,data={'retry_after':0.05,'global':True},headers={'Via':'synthetic'}))
        await self.prepare()
        self.assertEqual(self.session['voice_invite']['state'],'rate_limited')
        self.assertGreater(self.session['voice_invite']['retry_at'],0)
        self.assertFalse(self.http._global_over.is_set())
        await self.prepare(); self.assertEqual(len(self.wire.posts),1)
        await asyncio.sleep(0.06); self.assertTrue(self.http._global_over.is_set())

    async def test_unsupported_version_fails_before_any_post(self):
        self.fixture(Response(data={'code':'must-not-create'}))
        with patch.object(transport.discord,'__version__','future'):
            with self.assertRaises(transport.TransportUnavailable): await self.prepare()
        self.assertFalse(self.wire.posts)
