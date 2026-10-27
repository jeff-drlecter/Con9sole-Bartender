import ast
import asyncio
import pathlib
import types
import unittest
from unittest.mock import AsyncMock, Mock

source = pathlib.Path(__file__).resolve().parents[1] / 'cogs' / 'update_publisher.py'


class PublisherResponse(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        method = next(n for c in ast.parse(source.read_text()).body
                      if isinstance(c, ast.ClassDef) and c.name == 'DraftReviewView'
                      for n in c.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'publish_draft')
        method.decorator_list = []
        method.returns = None
        for arg in method.args.args:
            arg.annotation = None
        class Channel:
            id = 30
            mention = '<#30>'
            guild = types.SimpleNamespace(id=1)
        self.error = type('DiscordException', (Exception,), {})
        self.channel = Channel()
        self.channel.send = AsyncMock(return_value=types.SimpleNamespace(id=99, jump_url='https://discord.com/message'))
        self.scope = dict(config=types.SimpleNamespace(ANNOUNCEMENT_CHANNEL_ID=30),
                          discord=types.SimpleNamespace(TextChannel=Channel, DiscordException=self.error),
                          log=types.SimpleNamespace(exception=Mock()), mark_games_published=Mock())
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), self.scope)
        self.view = types.SimpleNamespace(publishing=False, published_message=None, children=[],
            draft=types.SimpleNamespace(kind='game', game_ids=('game',)),
            announcement_text=lambda: 'announcement', stop=Mock())
        self.inter = types.SimpleNamespace(
            guild=types.SimpleNamespace(id=1, get_channel=lambda _: self.channel),
            client=types.SimpleNamespace(fetch_channel=AsyncMock(return_value=self.channel)),
            response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def run_publish(self):
        await self.scope['publish_draft'](self.view, self.inter, None)

    async def test_acknowledges_before_fetch_and_send(self):
        self.inter.guild.get_channel = lambda _: None
        async def fetch(_):
            self.inter.response.defer.assert_awaited_once()
            return self.channel
        async def send(**kwargs):
            self.inter.response.defer.assert_awaited_once()
            return types.SimpleNamespace(id=99, jump_url='url')
        self.inter.client.fetch_channel.side_effect = fetch
        self.channel.send.side_effect = send
        await self.run_publish()
        self.inter.edit_original_response.assert_awaited_once()
        self.assertFalse(self.view.publishing)
        await self.run_publish()
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_confirmation_failure_does_not_republish(self):
        self.inter.edit_original_response.side_effect = self.error('confirmation failed')
        with self.assertRaises(self.error):
            await self.run_publish()
        self.assertFalse(self.view.publishing)
        await self.run_publish()
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_concurrent_click_does_not_duplicate(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def send(**kwargs):
            started.set()
            await release.wait()
            return types.SimpleNamespace(id=99, jump_url='url')
        self.channel.send.side_effect = send
        first = asyncio.create_task(self.run_publish())
        await started.wait()
        await self.run_publish()
        release.set()
        await first
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_send_failure_uses_followup_and_clears_busy_state(self):
        self.channel.send.side_effect = self.error('send failed')
        await self.run_publish()
        self.inter.followup.send.assert_awaited_once()
        self.assertIsNone(self.view.published_message)
        self.assertFalse(self.view.publishing)
        self.inter.edit_original_response.assert_not_awaited()
