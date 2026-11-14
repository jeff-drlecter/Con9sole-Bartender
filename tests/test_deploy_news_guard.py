import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_news_category_state import CHANNELS, verify


class NewsDeploymentGuardTests(unittest.TestCase):
    def test_read_only_marker_validation_and_missing_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'applied.json'
            with self.assertRaises(FileNotFoundError):
                verify(path)
            state = dict(version=1, channel_ids=CHANNELS,
                         role_ids=dict(ps='100', xbox='101', pc='102'))
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            self.assertEqual(verify(path), state)
            self.assertEqual(path.read_bytes(), before)
            for bad in ({**state, 'version': 2}, {**state, 'channel_ids': {}},
                        {**state, 'role_ids': dict(ps='100', xbox='100', pc='102')},
                        {**state, 'role_ids': dict(ps='100', xbox='101', pc='0')}):
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    verify(path)

    def test_workflow_never_applies_permissions_and_preflights_before_deploy(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/fly-deploy.yml').read_text()
        self.assertNotIn('apply_news_channel_categories.py', workflow)
        self.assertLess(workflow.index('Verify existing news migration before deployment'),
                        workflow.index('- name: Deploy to Fly.io'))
