"""Read-only production verification. Never prints secrets or stream titles."""
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aiohttp
import config
from cogs.stream_alerts import TwitchAPI


async def main():
    path = Path('/data/twitch_alerts.sqlite3')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        state = json.loads(db.execute('SELECT body FROM twitch_alert_state WHERE id=1').fetchone()[0])
    assert state['version'] == 1
    assert state['partner_minutes'] >= 30
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        api = TwitchAPI(session, os.environ['TWITCH_CLIENT_ID'], os.environ['TWITCH_CLIENT_SECRET'])
        names = [k for k, v in state['entries'].items() if v['enabled']]
        streams = await api.streams(names) if names else {}
        token = os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
        headers = {'Authorization': 'Bot ' + token}
        async with session.get('https://discord.com/api/v10/users/@me', headers=headers) as r:
            assert r.status == 200, f'Discord identity check: {r.status}'
            identity = await r.json()
        async with session.get(f"https://discord.com/api/v10/applications/{identity['id']}/guilds/{config.GUILD_ID}/commands", headers=headers) as r:
            assert r.status == 200, f'Discord commands check: {r.status}'
            commands = {item['name'] for item in await r.json()}
        assert {'stream_admin', 'stream_channels', 'stream_panel'} <= commands
        for key in ('member_channel', 'partner_channel'):
            async with session.get(f"https://discord.com/api/v10/channels/{state[key]}/messages?limit=1", headers=headers) as r:
                assert r.status == 200, f'{key} history access: {r.status}'
    print(json.dumps({'stream_alerts': 'ready', 'enabled': state['enabled'], 'roster': len(names),
                      'live_now': len(streams), 'member_minutes': 5, 'partner_minutes': state['partner_minutes'],
                      'commands_synced': True, 'channel_history_access': True}))


if __name__ == '__main__':
    asyncio.run(main())
