from copy import deepcopy
import unittest
from scripts.apply_approved_community import build_plan, apply, digest, GUILD,CATEGORY,BOARD,DEMO,GUIDE,WELCOME,SUPPORT,NEWS,VIEW_HISTORY,SUPPORT_BITS,channel_guard
import config


def fixture():
    def channel(cid,name='room',**kw):
        return dict(id=cid,guild_id=GUILD,name=name,type=0,position=0,nsfw=False,permission_overwrites=[],**kw)
    cat=channel(CATEGORY,'📡📡 - 即時情報站 - 📡📡');cat['type']=4
    board=channel(BOARD);board['permission_overwrites']=[dict(id=GUILD,type=0,allow='0',deny='1024'),
        dict(id='55',type=0,allow=str(VIEW_HISTORY|2048),deny='8192'),dict(id=str(config.HELPER_ROLE_IDS[0]),type=0,allow=str(VIEW_HISTORY),deny='0')]
    support=channel(SUPPORT,'問題回報');support['nsfw']=True
    channels=[cat,board,support,channel(GUIDE),channel(WELCOME),channel(DEMO)]+[channel(k) for k in NEWS]
    roles=[dict(id=GUILD,name='@everyone',permissions='0'),dict(id='55',name='🧪 Tester',managed=False,permissions='0'),
           dict(id=str(config.HELPER_ROLE_IDS[0]),name='Helpers',permissions='0'),dict(id=str(config.VERIFIED_ROLE_ID),name='Verified',permissions='0')]
    msgs={};panels={}
    for i,cid in enumerate(NEWS):
        mid=str(100+i);panels[cid]=mid
        msgs[cid]=[dict(id=mid,channel_id=cid,author=dict(id='999'),content='old',components=[dict(type=1,components=[dict(type=2,style=2,label='old',custom_id=x) for x in ('rss:card:news:v1','rss:card:preferences:v1','rss:card:channels:v1')])])]
    return dict(guild=dict(id=GUILD),roles=roles,channels=channels),msgs,panels


class MaintenanceTests(unittest.TestCase):
    def test_plan_minimal_bits_age_and_no_new_posts(self):
        snap,msgs,panels=fixture();before=deepcopy(snap)
        plan=build_plan(snap,'999',msgs,panels)
        self.assertEqual(snap,before)
        scope=next(a for a in plan['actions'] if a['kind']=='tester_scope')
        self.assertEqual(scope['body'],dict(type=0,allow='2048',deny='8192'))
        age=next(a for a in plan['actions'] if a['kind']=='problem_age')
        self.assertEqual(age['body'],dict(nsfw=False))
        self.assertFalse(plan['checks']['tester_board_after'])
        self.assertTrue(plan['checks']['helper_tester_board_after'])
        self.assertFalse(any(a['kind']=='support' for a in plan['actions']))
        for a in plan['actions']:
            if 'message' in a:self.assertEqual(a['body']['allowed_mentions']['parse'],[])
        self.assertTrue(any('entry:' in b for b in plan['blocked']))
    def test_only_verified_support_three_bits_and_not_unverified(self):
        snap,msgs,panels=fixture();c=next(c for c in snap['channels'] if c['id']==SUPPORT);c['nsfw']=False
        c['permission_overwrites']=[dict(id=str(config.VERIFIED_ROLE_ID),type=0,allow='8192',deny=str(SUPPORT_BITS|16384))]
        plan=build_plan(snap,'999',msgs,panels)
        a=next(a for a in plan['actions'] if a['kind']=='support')
        self.assertEqual(a['overwrite'],str(config.VERIFIED_ROLE_ID))
        self.assertEqual(a['body'],dict(type=0,allow=str(8192|SUPPORT_BITS),deny='16384'))
    def test_historical_maintenance_skips_new_endpoint_and_new_entry_card(self):
        snap,msgs,panels=fixture()
        old=next(c for c in snap['channels'] if c['id']==SUPPORT)
        new=deepcopy(old)
        new.update(id=str(config.SUPPORT_CHANNEL_ID),name='搵 Helper',nsfw=False)
        snap['channels'].append(new)
        for cid in (GUIDE,WELCOME):
            msgs[cid]=[dict(id='888',channel_id=cid,author=dict(id='999'),pinned=True,
                            components=[dict(components=[dict(custom_id='entry:menu:v2')])])]
        plan=build_plan(snap,'999',msgs,panels)
        self.assertNotEqual(new['id'],SUPPORT)
        self.assertFalse(any(a['channel']==new['id'] or a['kind']=='entry' for a in plan['actions']))

    def test_ambiguous_age_and_unowned_card_are_blocked(self):
        snap,msgs,panels=fixture();other=deepcopy(next(c for c in snap['channels'] if c['id']==SUPPORT));other['id']='777';snap['channels'].append(other)
        cid=next(iter(NEWS));msgs[cid][0]['author']['id']='outsider'
        plan=build_plan(snap,'999',msgs,panels)
        self.assertFalse(any(a['kind']=='problem_age' for a in plan['actions']))
        self.assertFalse(any(a['kind']=='news_panel' and a['channel']==cid for a in plan['actions']))
    def test_apply_refuses_drift_and_journals_before_single_field_write(self):
        snap,msgs,panels=fixture();plan=build_plan(snap,'999',msgs,panels)
        plan['actions']=[a for a in plan['actions'] if a['kind']=='news_name']
        c=next(c for c in snap['channels'] if c['id']==CATEGORY)
        calls=[];saved=[]
        class API:
            def call(self,method,path,body=None):
                calls.append((method,path,body))
                if path.endswith('/roles'):return snap['roles']
                if method=='PATCH':
                    assert saved[-1][-1]['state']=='uncertain'
                    assert set(body)=={'name'}
                    c.update(body)
                return deepcopy(c)
        results=apply(API(),plan,lambda r:saved.append(deepcopy(r)))
        self.assertEqual(results,[dict(kind='news_name',state='verified')])
        self.assertEqual(sum(m=='PATCH' for m,_,_ in calls),1)
        calls.clear();results=apply(API(),plan,lambda r:None)
        self.assertTrue(results[0]['state'].startswith('blocked'))
        self.assertFalse(any(m!='GET' for m,_,_ in calls))
    def test_roles_change_stops_before_any_write(self):
        snap,msgs,panels=fixture();plan=build_plan(snap,'999',msgs,panels)
        class API:
            def call(self,*args):return []
        with self.assertRaisesRegex(ValueError,'Roles changed'):apply(API(),plan,lambda _:None)

    def test_do_not_remove_only_helper_visibility_path(self):
        snap,msgs,panels=fixture()
        board=next(c for c in snap['channels'] if c['id']==BOARD)
        board['permission_overwrites']=board['permission_overwrites'][:2]
        plan=build_plan(snap,'999',msgs,panels)
        self.assertFalse(any(a['kind']=='tester_scope' for a in plan['actions']))
        self.assertIn('tester_scope: Helper visibility would be lost',plan['blocked'])

    def test_unrelated_change_in_readback_stops_with_uncertain_journal(self):
        snap,msgs,panels=fixture();plan=build_plan(snap,'999',msgs,panels)
        plan['actions']=[a for a in plan['actions'] if a['kind']=='news_name']
        c=next(c for c in snap['channels'] if c['id']==CATEGORY);saved=[]
        class API:
            def call(self,method,path,body=None):
                if path.endswith('/roles'):return snap['roles']
                if method=='PATCH':c.update(body);c['position']=99
                return deepcopy(c)
        with self.assertRaisesRegex(RuntimeError,'Readback differs'):
            apply(API(),plan,lambda r:saved.append(deepcopy(r)))
        self.assertEqual(saved[-1][-1]['state'],'uncertain')

    def test_owned_panel_edit_preserves_attachments_and_embeds_without_pings(self):
        snap,msgs,panels=fixture();cid=next(iter(NEWS));message=msgs[cid][0]
        message.update(embeds=[{'title':'retain'}],attachments=[{'id':'88'}],flags=0)
        plan=build_plan(snap,'999',msgs,panels)
        plan['actions']=[a for a in plan['actions'] if a['kind']=='news_panel' and a['channel']==cid]
        channel=next(c for c in snap['channels'] if c['id']==cid)
        writes=[]
        class API:
            def call(self,method,path,body=None):
                if path.endswith('/roles'):return snap['roles']
                if '/messages/' not in path:return deepcopy(channel)
                if method=='PATCH':
                    writes.append(body)
                    message.update({k:v for k,v in body.items() if k!='allowed_mentions'})
                    for row in message['components']:
                        for button in row['components']:button.update(id=123,disabled=False)
                return deepcopy(message)
        self.assertEqual(apply(API(),plan,lambda _:None)[0]['state'],'verified')
        self.assertEqual(writes[0]['allowed_mentions']['parse'],[])
        self.assertEqual(message['embeds'],[{'title':'retain'}])
        self.assertEqual(message['attachments'],[{'id':'88'}])
