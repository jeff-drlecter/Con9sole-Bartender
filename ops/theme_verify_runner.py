import datetime, json, re, shlex, subprocess, time
from pathlib import Path
expected_sha = 'a129d615f473eb3059ee8627c0496f05b7a55363'
cutoff = datetime.datetime.fromisoformat('2026-10-19T09:30:15Z'.replace('Z','+00:00'))
for attempt in range(24):
    p = subprocess.run(['flyctl','status','--app','con9sole-bartender','--json'],check=True,capture_output=True,text=True)
    status = json.loads(p.stdout)
    machines = [m for m in status.get('Machines',[]) if m.get('state') == 'started' and m.get('image_ref',{}).get('labels',{}).get('GH_SHA') == expected_sha]
    if len(machines) == 1:
        break
    time.sleep(10)
else:
    raise SystemExit('Expected release not running')
print(json.dumps({'release':status.get('Version'),'state':'started','sha':expected_sha,'image':machines[0]['image_ref'].get('tag')}))
script = Path('ops/theme_verify.py').read_text()
subprocess.run(['flyctl','ssh','console','--app','con9sole-bartender','-C','python -c '+shlex.quote(script)],check=True,timeout=180)
def fields(value):
    if isinstance(value,dict):
        for key,item in value.items():
            yield key.lower(),item
            yield from fields(item)
    elif isinstance(value,list):
        for item in value:
            yield from fields(item)
for attempt in range(6):
    p = subprocess.run(['flyctl','logs','--app','con9sole-bartender','--json','--no-tail'],check=True,capture_output=True,text=True)
    raw = re.sub(r'\x1b\[[0-9;]*m','',p.stdout)
    records=[]; index=0; decoder=json.JSONDecoder()
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index+=1
        try:
            value,index=decoder.raw_decode(raw,index)
            records.extend(value if isinstance(value,list) else [value])
        except ValueError:
            index=raw.find('{',index+1)
            if index<0:
                break
    messages=[]
    for record in records:
        pairs=list(fields(record)); stamps=[]
        for key,value in pairs:
            if key not in ('timestamp','time','@timestamp'):
                continue
            try:
                if isinstance(value,str):
                    stamp=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
                    if stamp.tzinfo is None:
                        stamp=stamp.replace(tzinfo=datetime.timezone.utc)
                elif isinstance(value,(float,int)):
                    while value>100000000000:
                        value/=1000
                    stamp=datetime.datetime.fromtimestamp(value,datetime.timezone.utc)
                else:
                    continue
                stamps.append(stamp)
            except (ValueError,OverflowError):
                continue
        if any(stamp>=cutoff for stamp in stamps):
            messages.extend(v for k,v in pairs if k in ('message','msg') and isinstance(v,str))
    joined='\n'.join(messages)
    cogs=sorted(set(re.findall(r'Loaded extension: cogs\.([a-z_]+)',joined)))
    report={'loaded_cogs':len(cogs),'discord_ready':'Logged in as' in joined,'guild_sync':'App commands synced to guild' in joined,'vc_sweeper':'Temp VC safety sweeper started' in joined,'failed_loading':'Failed loading' in joined,'error_lines':sum(' ERROR ' in m for m in messages),'parsed_records':len(records)}
    if len(cogs)==17 and all(report[k] for k in ('discord_ready','guild_sync','vc_sweeper')):
        break
    time.sleep(10)
print(json.dumps(report))
assert len(cogs)==17 and all(report[k] for k in ('discord_ready','guild_sync','vc_sweeper'))
assert not report['failed_loading'] and report['error_lines']==0
