import copy
import unittest
from scripts.release_machine import validate


class ReleaseMachine(unittest.TestCase):
    def setUp(self):
        self.machine = {'id':'9080d6d9a9d168','state':'started','config':{
            'image':'registry.fly.io/con9sole-bartender:deployment-example',
            'env':{'SECRET':'never print'},
            'mounts':[{'path':'/data','volume':'vol_example'}]}}

    def test_existing_identity_without_secret_config(self):
        result = validate([self.machine])
        self.assertEqual(result['machine'], self.machine['id'])
        self.assertEqual(result['rollback_image'], self.machine['config']['image'])
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('never print', str(result))

    def test_missing_second_or_stopped_machine_refuses_deployment(self):
        for values in ([],[self.machine,self.machine],{},[dict(self.machine,state='stopped')]):
            with self.subTest(values=values),self.assertRaises(ValueError):validate(values)

    def test_wrong_volume_or_rollback_identity_refuses_deployment(self):
        for key,value in (('mounts',[]),('mounts',[{'path':'/other','volume':'v'}]),
                          ('mounts',[{'path':'/data'}]),('image',''),
                          ('image','registry.fly.io/other:latest'),
                          ('image','registry.fly.io/con9sole-bartender:tag\nmalformed')):
            changed=copy.deepcopy(self.machine);changed['config'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate([changed])
