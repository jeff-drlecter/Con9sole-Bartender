"""Read-only deployment check for the opt-in member browser; never sends messages."""
import json
import os
from pathlib import Path
import sqlite3
import urllib.request


def effective_permissions(guild_id, roles, member, channel):
    ids = set(member['roles']) | {str(guild_id)}
    permissions = 0
    for role in roles:
        if role['id'] in ids:
            permissions |= int(role['permissions'])
    if permissions & 8:
        return permissions
    overwrites = channel.get('permission_overwrites', [])
    base = next((o for o in overwrites if o['id'] == str(guild_id) and o['type'] == 0), {})
    permissions = (permissions & ~int(base.get('deny', 0))) | int(base.get('allow', 0))
    allow = deny = 0
    for overwrite in overwrites:
        if overwrite['type'] == 0 and overwrite['id'] in ids - {str(guild_id)}:
            allow |= int(overwrite['allow'])
            deny |= int(overwrite['deny'])
    permissions = (permissions & ~deny) | allow
    personal = next((o for o in overwrites if o['type'] == 1 and o['id'] == member['user']['id']), {})
    return (permissions & ~int(personal.get('deny', 0))) | int(personal.get('allow', 0))


def main():
    if os.getenv('RSS_PERSONAL_PUBLIC') != '1':
        return
    config = json.loads(Path(os.environ['RSS_DIGEST_CONFIG']).read_text())
    categories = os.getenv('RSS_CATEGORY_DELIVERY') == '1'
    if categories:
        assert config['simulation'] is False
        assert config['channel_id'] == 1364201334798290994
    else:
        assert config['simulation'] is True
        assert config['channel_id'] == 1570054214850183289
    with sqlite3.connect('file:/data/rss_sandbox_preferences.sqlite3?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        db.execute('SELECT user_id,payload FROM preferences LIMIT 0')
    token = os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
    def get(path):
        request = urllib.request.Request('https://discord.com/api/v10/' + path,
            headers={'Authorization': 'Bot ' + token, 'User-Agent': 'Con9sole-Bartender/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    app = get('users/@me')
    commands = get(f"applications/{app['id']}/guilds/626378673523785731/commands")
    news = next(c for c in commands if c['name'] == 'news')
    assert news.get('default_member_permissions') is None, 'News command unexpectedly restricted'
    news_channels = next(c for c in commands if c['name'] == 'news_channels')
    assert news_channels.get('default_member_permissions') is None
    if categories:
        guild_id = 626378673523785731
        roles = get(f'guilds/{guild_id}/roles')
        member = get(f"guilds/{guild_id}/members/{app['id']}")
        for route, channel_id in {'ps':1364201334798290994, 'xbox':1379699174668505098, 'pc':1364210080043630612}.items():
            channel = get(f'channels/{channel_id}')
            assert int(channel['guild_id']) == guild_id and channel['type'] in (0, 5)
            perms = effective_permissions(guild_id, roles, member, channel)
            required = (1 << 10) | (1 << 11) | (1 << 14)
            assert perms & 8 or perms & required == required, f'{route} missing publisher permissions'
            with sqlite3.connect(f'file:/data/rss_route_{route}.sqlite3?mode=ro', uri=True) as db:
                assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                db.execute('SELECT slot,state FROM digest_batches LIMIT 0')
        print('Verified categorized publisher destinations, bot permissions, durable queues and member command registrations.')
    else:
        print('Verified sandbox destination and member command registrations.')
    print('Preference database intact. No messages sent; ordinary-member UI interaction remains a separate check.')


if __name__ == '__main__':
    main()
