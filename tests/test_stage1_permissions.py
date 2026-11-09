import unittest
import discord
from features.stage1_permissions import build, simulate, verify, VIP_CHANNELS, CAP_MASK
from features.permission_audit import permissions


def row(rid,allow=0,deny=0):return dict(id=str(rid),type='role',allow=permissions(allow),deny=permissions(deny))

def fixture():
    gid='1';vid='2'
    roles=[dict(id=gid,name='everyone',permissions=permissions(discord.Permissions(view_channel=True,send_messages=True,connect=True,speak=True,use_voice_activation=True).value),managed=False,bot_managed=False),
           dict(id=vid,name='Verified',permissions=permissions(0),managed=False,bot_managed=False),
           dict(id='3',name='Game',permissions=permissions(CAP_MASK),managed=False,bot_managed=False),
           dict(id='4',name='Booster',permissions=permissions(0),managed=True,bot_managed=False)]
    channels=[dict(id='10',name='game category',type='category',category_id=None,overwrites=[row(gid),row('3',CAP_MASK)]),
              dict(id='11',name='game chat',type='text',category_id='10',overwrites=[row(gid),row('3',CAP_MASK)]),
              dict(id='12',name='custom chat',type='text',category_id='10',overwrites=[row(gid),row('4',CAP_MASK)]),
              dict(id='20',name='VIP',type='category',category_id=None,overwrites=[row(vid,deny=CAP_MASK),row('4',CAP_MASK)])]
    channels += [dict(id=cid,name='VIP child',type='text',category_id='20',overwrites=[row(vid,deny=CAP_MASK),row('4',CAP_MASK)]) for cid in sorted(VIP_CHANNELS)]
    return dict(guild=dict(id=gid),roles=roles,channels=channels)


class Stage1Tests(unittest.TestCase):
    def test_mask_only_and_union_proof(self):
        snapshot=fixture();plan=build(snapshot,99,2)
        self.assertFalse(plan['verification']['unexpected_unverified_caps'])
        for op in plan['ops']:
            self.assertFalse(((op['before'][0]^op['after'][0])|(op['before'][1]^op['after'][1])) & ~CAP_MASK)
        self.assertFalse(verify(simulate(snapshot,plan),2)['unexpected_unverified_caps'])
        self.assertTrue(verify(snapshot,2)['unexpected_unverified_caps'])

    def test_vip_and_synced_children_untouched_directly(self):
        snapshot=fixture();plan=build(snapshot,99,2)
        self.assertEqual(len(plan['accepted_exceptions']),4)
        self.assertTrue(all(str(op['channel']) not in VIP_CHANNELS|{'20','11'} for op in plan['ops']))
        simulated=simulate(snapshot,plan)
        for cid in VIP_CHANNELS|{'20'}:
            self.assertEqual(next(c for c in snapshot['channels'] if c['id']==cid),next(c for c in simulated['channels'] if c['id']==cid))
        channels={c['id']:c for c in simulated['channels']}
        self.assertEqual(channels['10']['overwrites'],channels['11']['overwrites'])

    def test_managed_human_overwrite_removed(self):
        plan=build(fixture(),99,2)
        self.assertTrue(any(op['target']==4 and op['channel']==12 for op in plan['ops']))

    def test_privileged_bots_reported_not_changed(self):
        s=fixture();s['roles'].append(dict(id='5',name='bot',permissions=permissions(8),managed=True,bot_managed=True))
        p=build(s,99,2)
        self.assertEqual(len(p['blockers']),1)
        self.assertTrue(all(op['target']!=5 for op in p['ops']))

    def test_changed_vip_and_member_grants_abort(self):
        s=fixture();s['channels'][-1]['overwrites']=[]
        with self.assertRaises(ValueError):build(s,99,2)
        s=fixture();m=row('member',CAP_MASK);m['type']='member';s['channels'][2]['overwrites'].append(m)
        with self.assertRaises(ValueError):build(s,99,2)

    def test_union_deny_cannot_hide_subset_grant(self):
        s=fixture()
        s['channels'][2]['overwrites']=[row('4',deny=CAP_MASK)]
        self.assertIn('12',verify(s,2)['unexpected_unverified_caps'])

    def test_nonadmin_feed_bot_and_helper_preserved(self):
        from features.stage1_permissions import service_capability_losses
        s=fixture()
        s['roles'] += [dict(id='5',name='feed',permissions=permissions(CAP_MASK),managed=True,bot_managed=True),
                       dict(id='626379227473903632',name='Mod',permissions=permissions(CAP_MASK),managed=False,bot_managed=False)]
        p=build(s,99,2)
        self.assertFalse(service_capability_losses(s,simulate(s,p)))
        self.assertTrue(any(op['target']==5 and op.get('preserve_service') for op in p['ops']))

    def test_bot_using_game_role_preserved(self):
        from features.stage1_permissions import service_capability_losses
        s=fixture();s['roles'].append(dict(id='5',name='feed',permissions=permissions(0),managed=True,bot_managed=True))
        s['service_members']={'5':['5','3']}
        p=build(s,99,2)
        self.assertFalse(service_capability_losses(s,simulate(s,p)))
        self.assertTrue(any(op['target']==5 for op in p['ops']))

    def test_actual_helper_with_game_capability_preserved(self):
        from features.stage1_permissions import service_capability_losses
        s=fixture();helper='1279071042249162856'
        s['roles'].append(dict(id=helper,name='Helpers',permissions=permissions(0),managed=False,bot_managed=False))
        s['staff_members']={'900':[helper,'3']}
        p=build(s,99,2)
        self.assertFalse(service_capability_losses(s,simulate(s,p)))
        self.assertTrue(any(op['target']==int(helper) and op.get('preserve_service') for op in p['ops']))
