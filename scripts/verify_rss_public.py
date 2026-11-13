"""Read-only deployment check for the opt-in member browser; never sends messages."""
import json
import os
from pathlib import Path
import sqlite3
import urllib.request


def main():
    if os.getenv('RSS_PERSONAL_PUBLIC') != '1':
        return
    config = json.loads(Path(os.environ['RSS_DIGEST_CONFIG']).read_text())
    # This rollout deliberately keeps scheduled output inside the existing sandbox.
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
    print('Verified /news registration, preference database integrity and sandbox-only scheduled output. Member interaction is not UI-tested by this check.')


if __name__ == '__main__':
    main()
