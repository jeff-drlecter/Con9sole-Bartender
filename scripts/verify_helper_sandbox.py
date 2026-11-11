"""Read-only deployed verification of sandbox controls and limited role access."""
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.request


def main():
    if os.getenv('HELPER_SANDBOX')!='1': return
    path=Path('/data/helper_sandbox.sqlite3')
    for _ in range(24):
        settings={}
        if path.exists():
            with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
                try: settings=dict(db.execute('SELECT key,value FROM settings'))
                except sqlite3.OperationalError: pass
        if settings.get('panel','').isdigit() and settings.get('channel','').isdigit(): break
        time.sleep(5)
    else: raise RuntimeError('Helper sandbox channel/panel not confirmed')
    token=os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
    def get(route):
        request=urllib.request.Request('https://discord.com/api/v10/'+route,
            headers={'Authorization':'Bot '+token,'User-Agent':'Con9sole-Bartender/1.0'})
        with urllib.request.urlopen(request,timeout=20) as response: return json.load(response)
    channel=get('channels/'+settings['channel'])
    assert channel['guild_id']=='626378673523785731' and channel['name']=='helper-模擬區'
    overwrites={r['id']:r for r in channel['permission_overwrites']}
    assert int(overwrites[channel['guild_id']]['deny']) & 1024, 'Channel must remain private'
    for role in [settings['tester_role'],'1279071042249162856']:
        allowed=int(overwrites[role]['allow'])
        assert allowed & 1024 and allowed & 65536, 'Helper/Tester view/history missing'
    message=get(f"channels/{settings['channel']}/messages/{settings['panel']}")
    ids={c.get('custom_id') for row in message.get('components',[]) for c in row.get('components',[])}
    expected={f'helper:sandbox:{key}:v1' for key in ('live','create','manage','duty','history')}
    assert expected<=ids, 'Missing helper sandbox controls'
    assert '虛構示範' in message['embeds'][0]['title'], 'Demo must be clearly labeled'
    print(f"Verified helper sandbox https://discord.com/channels/{channel['guild_id']}/{channel['id']}/{message['id']}")
    print('Verified Helpers and Tester view/history permissions; everyone denied; five controls present.')


if __name__=='__main__': main()
