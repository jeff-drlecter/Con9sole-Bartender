import hashlib, json, os, sqlite3, subprocess, sys, tempfile, urllib.request
from pathlib import Path
os.chdir('/app')
from core.storage_paths import STATS_DB
expected = {"assets/theme_collections_v1.json":"0fc8d7391c52b1e6c852d9f6d83aeb4c6d1dbcb09673727c8f23ddbeb93048c8","cogs/drink.py":"8b235f5aa424edbf8b25cffd890f2a3121845cdabcd1b2afd12dbc2c0b573745","data/drink_data.py":"4bc86bbbf3a4c65afde7b25ea68416976fa92ebfdfcf5981a1f2b860f4153727","features/collection_milestones.py":"75dfb34b9d04c3705811fdcbffaff0cd30238c0a1bc3361deb732b9392a4070d","features/drink_catalog.py":"265c14c2fa83c24676b392fcfa78f38596f274b3d9a85dcd8e52caf1d6f1d9b9","features/drink_embeds.py":"48978f14a78cad9112bafa531ccbf0b3a9e536529eeb67234f9cb3b5813c6325","features/drink_storage.py":"367a94bf757e16b5a1976e257fb07f081be13ba40ff6d6542f05027562994168","features/drink_views.py":"fb568ed70d3b25a17df4760cdd3110aca88c1dba2e3e95ef9bfc34557df0dfbc","features/theme_collections.py":"b5da6f7f1528f4713aec78b29aa7be080dd683d945f571ea8c2cb2a576b30e3d","features/theme_views.py":"e1cb017350ab1218c59a5e904874bc074b75a06d396007653397b18ad2c33940"}
assert all(Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p,h in expected.items()), 'Deployed source mismatch'
baseline_path = Path('/data/backups/theme-collections-v1-20261019T092932470435Z/community_stats.sqlite3')
assert baseline_path.exists(), 'Missing pre-release backup'
live_path = Path(STATS_DB).resolve()
tables = ['drink_events','drink_collection','drink_milestones','drink_collection_titles']
with tempfile.TemporaryDirectory(prefix='theme-release-verification-') as tmp:
    snapshot_path = Path(tmp) / 'live-snapshot.sqlite3'
    with sqlite3.connect(live_path.as_uri() + '?mode=ro', uri=True) as live:
        with sqlite3.connect(snapshot_path) as snap:
            live.backup(snap)
    report = {'code_files_verified':len(expected), 'missing_old_rows':{}, 'live_counts':{}}
    with sqlite3.connect(baseline_path.as_uri() + '?mode=ro', uri=True) as before, sqlite3.connect(snapshot_path) as after:
        assert after.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        found = {r[0] for r in after.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'drink_theme_awards','drink_theme_preferences'} <= found
        for table in tables:
            old = set(before.execute('SELECT * FROM ' + table))
            new = set(after.execute('SELECT * FROM ' + table))
            report['missing_old_rows'][table] = len(old - new)
            report['live_counts'][table] = len(new)
            assert not old - new, 'Old rows changed or lost: ' + table
        report['sqlite_integrity'] = 'ok'
        report['live_theme_awards'] = after.execute('SELECT COUNT(*) FROM drink_theme_awards').fetchone()[0]
        report['live_selected_title_labels'] = [r[0] for r in after.execute('SELECT m.label FROM drink_collection_titles t JOIN drink_milestones m USING(guild_key,user_id,milestone_id)')]
    child = r'''
import json, sqlite3, sys
from pathlib import Path
from features import drink_storage as storage
from features import theme_collections as tc
from features.collection_milestones import collection_snapshot, select_title
mode = sys.argv[1]
with storage.connect_sqlite(storage.STATS_DB) as conn:
    profiles = conn.execute("SELECT DISTINCT guild_key,user_id FROM drink_collection ORDER BY guild_key,user_id").fetchall()
manifest = json.loads(Path('/app/assets/theme_collections_v1.json').read_text())['drinks']
result = []
for key,user in profiles:
    guild = None if key == 'dm' else int(key)
    old = collection_snapshot(guild,user)
    state = tc.snapshot(guild,user)
    names = state['names']
    styles = {d[2] for d in manifest if d[0] in names and d[2] in {'short','tropical','sparkling','beer','whisky'}}
    tropical = sum(d[0] in names and d[2] == 'tropical' for d in manifest)
    classics = sum(d[0] in names and d[4] for d in manifest)
    expected = set()
    for theme,count,targets in [('starter',len(styles),(3,5)),('tropical',tropical,(3,10,25)),('classics',classics,(1,3,10))]:
        expected.update('theme:v1:%s:%s' % (theme,n) for n in targets if count >= n)
    assert expected == {a['award_id'] for a in state['awards']}
    assert old['names'] == names
    if mode == 'prepare':
        eligible = [a['milestone_id'] for a in old['awards']]
        preferred = next((a for a in eligible if a.startswith('theme:')), eligible[0] if eligible else None)
        if preferred:
            assert select_title(guild,user,preferred)
        assert tc.track(guild,user,'tropical')
    state = tc.snapshot(guild,user)
    selected = collection_snapshot(guild,user)['selected']
    result.append({'key':key,'user':user,'names':sorted(names),'awards':state['awards'],'tracked':state['tracked'],'selected':selected})
print(json.dumps(result,ensure_ascii=False))
'''
    env = dict(os.environ)
    for key in ('DISCORD_TOKEN','DISCORD_BOT_TOKEN','TWITCH_BOT_OAUTH'):
        env.pop(key,None)
    env.update(DRINK_DATA_DIR=tmp, STATS_DB_PATH=str(snapshot_path), DRINK_STATE_PATH=str(Path(tmp)/'drink_state.json'))
    def fresh(mode):
        p = subprocess.run([sys.executable,'-c',child,mode],env=env,check=True,capture_output=True,text=True,timeout=60,cwd='/app')
        return json.loads(p.stdout)
    prepared = fresh('prepare')
    for _ in range(2):
        assert fresh('verify') == prepared, 'Persistence differs in fresh process'
    report['copy_profiles_verified'] = len(prepared)
    report['copy_theme_stages_verified'] = sum(len(p['awards']) for p in prepared)
    report['copy_theme_titles_verified'] = sum(bool(p['selected'] and p['selected'].startswith('theme:')) for p in prepared)
    report['fresh_process_reads'] = 2
    report['copy_only_writes'] = True
    import config
    token = os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
    def get(path):
        req = urllib.request.Request('https://discord.com/api/v10'+path,headers={'Authorization':'Bot '+token,'User-Agent':'Con9soleThemeRelease/1.0'})
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.load(response)
    me = get('/users/@me')
    commands = get('/applications/'+me['id']+'/guilds/'+str(config.GUILD_ID)+'/commands')
    assert {'menu','drink','drink_collection','cheers','vc_new'} <= {c['name'] for c in commands}
    report['discord_auth_ok'] = True
    report['guild_commands'] = len(commands)
    print(json.dumps(report,ensure_ascii=False))
