import tempfile
import unittest
from pathlib import Path

from features.update_publisher import (
    record_published_version, version_guidance, parse_announcement_version,
    record_created_game, get_pending_games,
)


class PublisherVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'announcements.json'

    def record(self, value, mid, guild=1):
        record_published_version(guild, value, message_id=mid, path=self.path)

    def hint(self, guild=1):
        return version_guidance(guild, path=self.path)

    def test_no_history_does_not_invent_existing_version(self):
        self.assertIn('未有版本紀錄', self.hint())
        self.assertFalse(self.path.exists())

    def test_major_minor_and_numeric_order(self):
        self.record('v3.9.9', 1)
        self.record('3.10.2', 2)
        self.record('v3.8.0', 3)
        self.assertEqual(self.hint(), '已發布 v3.10.2｜小更新 v3.11.0｜大更新 v4.0.0')

    def test_two_part_versions_and_validation(self):
        self.assertEqual(parse_announcement_version(' V3.8 '), (3, 8, 0))
        for invalid in ('', 'hello', '1', '1.-2.0', '1.2.3.4', '1.2-beta'):
            self.assertIsNone(parse_announcement_version(invalid))
        self.record('v3.8', 1)
        self.assertIn('小更新 v3.9.0', self.hint())

    def test_persists_per_guild_and_preserves_pending_games(self):
        record_created_game(guild_id=1, name='Game', detail='Ready', path=self.path)
        self.record('v5.2.1', 1)
        self.record('v2.1.0', 2, guild=2)
        self.assertIn('已發布 v5.2.1', self.hint())
        self.assertIn('已發布 v2.1.0', self.hint(2))
        self.assertEqual(len(get_pending_games(1, path=self.path)), 1)

    def test_idempotent_message_and_invalid_value(self):
        self.record('v2.0.0', 1)
        self.record('v99.0.0', 1)
        self.record('invalid', 2)
        self.assertIn('已發布 v2.0.0', self.hint())


class HistoryImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_imports_old_v_dot_format_without_publishing(self):
        from unittest.mock import MagicMock, patch
        import discord
        from cogs.update_publisher import UpdatePublisher
        channel = MagicMock(spec=discord.TextChannel)
        async def history(**kwargs):
            yield MagicMock(id=123, content='📣 **Con9sole 更新公告 — v.3.9.0**\nexisting')
            yield MagicMock(id=124, content='unrelated v99.0.0')
        channel.history = history
        interaction = MagicMock()
        interaction.guild.get_channel.return_value = channel
        with patch('cogs.update_publisher.latest_announcement_version', return_value=None), \
             patch('cogs.update_publisher.record_published_version') as record:
            await UpdatePublisher(MagicMock())._import_version_history(interaction)
        record.assert_called_once_with(interaction.guild.id, 'v.3.9.0', message_id=123)
        channel.send.assert_not_called()
