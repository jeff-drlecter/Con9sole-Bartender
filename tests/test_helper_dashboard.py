import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock
import discord
import config
from cogs.helper_sandbox import HelperSandbox, ROOM_ID, RSS_ROOM
from core.helper_detection import DetectionStore
from core.helper_dashboard import dashboard_embed


class DashboardTests(unittest.TestCase):
    def test_bootstrap_accepts_renamed_channel_but_rejects_identity_and_access(self):
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                cog=HelperSandbox(NS())
                cog.store=DetectionStore(Path(tmp)/'helper.db')
                helper=NS(id=config.HELPER_ROLE_IDS[0])
                tester=NS(id=55,name='🧪 Tester')
                everyone=NS(id=config.GUILD_ID)
                guild=NS(id=config.GUILD_ID,default_role=everyone,roles=[tester],me=NS())
                channel=MagicMock(spec=discord.TextChannel)
                channel.id,channel.guild=ROOM_ID,guild
                channel.name,channel.topic='renamed dashboard','new display description'
                channel.permissions_for=lambda role:NS(view_channel=role is not everyone,read_message_history=True)
                rss=NS(category=NS())
                guild.get_channel=lambda cid:channel if cid==ROOM_ID else rss if cid==RSS_ROOM else None
                guild.get_role=lambda rid:helper
                cog.bot=NS(get_guild=lambda gid:guild)
                cog.refresh=AsyncMock()
                cog.store.set('dashboard_panel','999')
                # The old panel belongs to a different channel and must remain untouched.
                cog.store.set('channel',1570093470666854411)
                cog.store.set('panel',123)
                await cog.bootstrap()
                self.assertIs(cog.channel,channel)
                self.assertEqual(cog.store.get('panel'),'123')
                self.assertEqual(cog.store.get('dashboard_channel'),str(ROOM_ID))
                cog.refresh.assert_awaited_once()
                channel.send.assert_not_called()
                channel.edit.assert_not_called()
                for change in ('saved_identity','guild','public','helper_history'):
                    cog.store.set('dashboard_channel',ROOM_ID)
                    guild.id=config.GUILD_ID
                    channel.permissions_for=lambda role:NS(view_channel=role is not everyone,read_message_history=True)
                    if change=='saved_identity': cog.store.set('dashboard_channel',123)
                    if change=='guild': guild.id=123
                    if change=='public': channel.permissions_for=lambda role:NS(view_channel=True,read_message_history=True)
                    if change=='helper_history': channel.permissions_for=lambda role:NS(view_channel=role is not everyone,read_message_history=role is not helper)
                    with self.assertRaises(RuntimeError): await cog.bootstrap()
        asyncio.run(run())

    def test_aggregates_only_eligible_sources_and_no_member_names(self):
        category=NS(id=1,name='Monster Hunter')
        hidden=NS(id=2,name='private staff')
        user=NS(id=99,name='DO NOT SHOW THIS',bot=False)
        text=NS(category_id=1)
        private=NS(category_id=2)
        rooms=[NS(category_id=c.id,category=c,name='room',members=[user]) for c in (category,hidden)]
        channels={1:category,2:hidden,10:text,20:private}
        guild=NS(get_channel=lambda cid:channels.get(cid),voice_channels=rooms)
        cog=NS(channel=NS(guild=guild),game_categories=lambda g:{1,2},pulse_source=lambda source:source is text,
               window=NS(counts=lambda now:{10:dict(users={99},messages=3),20:dict(users={99},messages=10)}))
        embed=dashboard_embed(cog)
        body=str(embed.to_dict())
        self.assertIn('1 人／3 則',body)
        self.assertIn('1 間／1 人',body)
        self.assertNotIn('DO NOT SHOW THIS',body)
        self.assertNotIn('private staff',body)
        self.assertNotIn('<@',body)
        self.assertLess(len(embed),6000)
