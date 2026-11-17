"""One network POST for voice invites, pinned to discord.py 2.7.1/aiohttp 3.14.5.

HTTPClient.request retries ambiguous unique-invite creations. This narrow adapter
shares its authentication, session, proxy, bucket and global gates, but never calls
that retrying method. No other Discord endpoint is changed. Private APIs below
must be re-reviewed (and transport tests updated) before dependency upgrades.
"""
from __future__ import annotations

import asyncio
import math
import time
import weakref
from urllib.parse import quote

import aiohttp
import discord
from discord.http import Route, json_or_text

REQUEST_TIMEOUT = 30
SUPPORTED = ('2.7.1', '3.14.5')
_background = set()
_refreshing = {}
_global_deadlines = weakref.WeakKeyDictionary()


class InviteRateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        self.retry_at = time.time() + retry_after
        super().__init__('Voice invite rate limited')


class TransportUnavailable(RuntimeError):
    pass


def _release_bucket(bucket):
    # Same accounting as Ratelimit.__aexit__, with refresh in a retained task:
    # publishing/cleanup must not hold the squad lock for the entire quota window.
    bucket.outgoing -= 1
    tokens = bucket.remaining - bucket.outgoing
    if bucket._sleeping.locked() or bucket in _refreshing:
        return
    if tokens <= 0:
        task = asyncio.create_task(bucket._refresh())
        _background.add(task)
        _refreshing[bucket] = task
        def done(task):
            _background.discard(task)
            _refreshing.pop(bucket, None)
            if not task.cancelled():
                task.exception()  # Retrieve exceptions; never log auth/response data.
        task.add_done_callback(done)
    elif bucket._pending_requests:
        error = (discord.RateLimited(bucket.reset_after)
                 if bucket._max_ratelimit_timeout and bucket.reset_after > bucket._max_ratelimit_timeout else None)
        bucket._wake(tokens, exception=error)


def _global_backoff(http, delay):
    loop = asyncio.get_running_loop()
    deadline = max(_global_deadlines.get(http, 0), loop.time() + delay)
    _global_deadlines[http] = deadline
    http._global_over.clear()
    def release():
        if _global_deadlines.get(http, 0) <= loop.time():
            _global_deadlines.pop(http, None)
            http._global_over.set()
    loop.call_at(deadline, release)


async def create_once(voice, *, max_age, reason, before_send):
    """Run before_send synchronously after all gates and immediately before POST.

    5xx/reset/timeout/cancel/redirect/invalid success are ambiguous and never retried.
    A validated 429 is a definitive non-create with its own persisted retry deadline.
    """
    if (discord.__version__, aiohttp.__version__) != SUPPORTED:
        raise TransportUnavailable('Voice invite transport dependency version needs review')
    http = voice._state.http
    route = Route('POST', '/channels/{channel_id}/invites', channel_id=voice.id)
    bucket_hash = http._bucket_hashes.get(route.key)
    key = f'{bucket_hash or route.key}:{route.major_parameters}'
    bucket = http.get_ratelimit(key)
    await http._global_over.wait()
    try:
        await bucket.acquire()
    except discord.RateLimited as exc:
        raise InviteRateLimited(exc.retry_after) from None
    try:
        # The global gate may have closed while waiting for this route's bucket.
        await http._global_over.wait()
        session = http._HTTPClient__session
        headers = {'User-Agent': http.user_agent, 'Content-Type': 'application/json'}
        if http.token is not None:
            headers['Authorization'] = 'Bot ' + http.token
        if reason:
            headers['X-Audit-Log-Reason'] = quote(reason, safe='/ ')
        base = getattr(session, 'timeout', aiohttp.ClientTimeout())
        timeout = aiohttp.ClientTimeout(total=min(base.total or REQUEST_TIMEOUT, REQUEST_TIMEOUT),
            connect=base.connect, sock_connect=base.sock_connect, sock_read=base.sock_read,
            ceil_threshold=base.ceil_threshold)
        kwargs = dict(headers=headers, timeout=timeout, allow_redirects=False,
            data=discord.utils._to_json(dict(max_age=max_age,max_uses=0,temporary=False,unique=True)))
        if http.proxy is not None:
            kwargs['proxy'] = http.proxy
        if http.proxy_auth is not None:
            kwargs['proxy_auth'] = http.proxy_auth
        before_send()  # Presence fence + durable uncertain journal; no awaits before POST.
        async with session.request(route.method, route.url, **kwargs) as response:
            data = await json_or_text(response)
            returned_hash = response.headers.get('X-Ratelimit-Bucket')
            if returned_hash and returned_hash != bucket_hash:
                http._bucket_hashes[route.key] = returned_hash
                http._buckets[f'{returned_hash}:{route.major_parameters}'] = bucket
                if bucket_hash:
                    http._buckets.pop(key, None)
            if response.status != 429 and 'X-Ratelimit-Remaining' in response.headers:
                bucket.update(response, use_clock=http.use_clock)
            if 200 <= response.status < 300:
                if not isinstance(data, dict) or not isinstance(data.get('code'), str) or not data['code']:
                    raise TransportUnavailable('Unrecognised invite success; result remains uncertain')
                return data
            if response.status == 429 and response.headers.get('Via') and isinstance(data, dict):
                try:
                    delay = float(data.get('retry_after', response.headers.get('Retry-After')))
                    if not math.isfinite(delay) or delay < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    raise discord.HTTPException(response, data) from None
                bucket.remaining = 0
                bucket.reset_after = delay
                bucket.expires = asyncio.get_running_loop().time() + delay
                if data.get('global'):
                    _global_backoff(http, delay)
                raise InviteRateLimited(delay)
            if response.status == 403:
                raise discord.Forbidden(response, data)
            if response.status == 404:
                raise discord.NotFound(response, data)
            if response.status >= 500:
                raise discord.DiscordServerError(response, data)
            raise discord.HTTPException(response, data)
    finally:
        _release_bucket(bucket)
