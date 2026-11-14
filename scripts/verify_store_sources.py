"""Read-only source acceptance. No Discord messages, preferences or queue writes."""
import json
import os
from pathlib import Path
import sqlite3
import time


def main():
    path=os.getenv('STORE_NEWS_CONFIG','')
    if not path: return
    conf=json.loads(Path(path).read_text())
    required={'epic:hk','epic:tw'}|{'steam:'+str(a) for a in conf['steam_appids']}
    db_path=Path('/data/store_news.sqlite3')
    for _ in range(24):
        if db_path.exists():
            with sqlite3.connect(f'file:{db_path}?mode=ro',uri=True) as db:
                try:
                    snapshots=dict(db.execute('SELECT bucket,checked FROM store_snapshots'))
                    rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM store_items')]
                except sqlite3.OperationalError:
                    snapshots={};rows=[]
            if required<=snapshots.keys() and all(0<=time.time()-snapshots[b]<3600 for b in required): break
        time.sleep(5)
    else: raise RuntimeError('Store collection not confirmed for every configured source/region')
    now=time.time()
    current=[a for a in rows if a.get('offer') and a['offer']['starts']<=now<a['offer']['deadline']]
    assert all(a['offer']['verified'] is True and a['offer']['regions'] for a in current)
    assert all(a['offer']['kind']=='keep' for a in current if a['source']=='epic')
    print(json.dumps({'store_sources':'ready','sources':sorted(snapshots),
        'current_verified_offers':len(current),'news':sum(a.get('offer') is None for a in rows),
        'public_browsing_enabled':os.getenv('STORE_NEWS_PUBLIC')=='1',
        'automatic_store_notifications':False},ensure_ascii=False))


if __name__=='__main__': main()
