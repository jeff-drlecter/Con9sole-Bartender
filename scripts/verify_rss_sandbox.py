"""Deployment smoke check; uses the existing bot identity without logging secrets."""
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.request


def main():
    config_path=os.getenv('RSS_DIGEST_CONFIG','')
    if not config_path: return
    config=json.loads(Path(config_path).read_text())
    if not (config.get('simulation') and config.get('enabled') and os.getenv('RSS_DELIVERY_SOURCES')): return
    path=Path('/data/rss_sandbox_preferences.sqlite3')
    for _ in range(18):
        if path.exists():
            with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
                try: row=db.execute('SELECT state,message_id FROM panels WHERE channel_id=?',(config['channel_id'],)).fetchone()
                except sqlite3.OperationalError: row=None
            if row and row[0]=='posted': break
        time.sleep(5)
    else: raise RuntimeError('Sandbox panel not confirmed posted within startup window')
    token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
    request=urllib.request.Request(f"https://discord.com/api/v10/channels/{config['channel_id']}/messages/{row[1]}",
                                   headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/1.0'})
    with urllib.request.urlopen(request,timeout=20) as response: message=json.load(response)
    ids={c.get('custom_id') for r in message.get('components',[]) for c in r.get('components',[])}
    assert {'rss:sandbox:personal:v1','rss:sandbox:preferences:v1'} <= ids, 'Missing sandbox controls'
    print(f"Verified sandbox panel https://discord.com/channels/{message['guild_id'] if 'guild_id' in message else '626378673523785731'}/{config['channel_id']}/{row[1]}")


if __name__=='__main__': main()
