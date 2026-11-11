import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

spec = importlib.util.spec_from_file_location('container_entrypoint', Path(__file__).resolve().parents[1] / 'scripts/container_entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class ContainerEntrypointTests(unittest.TestCase):
    def test_root_drops_supplementary_groups_and_identity_before_exec(self):
        with patch.object(entrypoint, 'prepare_volume') as prepare, patch.object(entrypoint.os, 'getuid', side_effect=[0, 10001]), patch.object(entrypoint.os, 'getgid', return_value=10001), patch.object(entrypoint.sys, 'argv', ['entrypoint', 'python', 'bot.py']), patch.object(entrypoint.os, 'setgroups') as groups, patch.object(entrypoint.os, 'setgid') as gid, patch.object(entrypoint.os, 'setuid') as uid, patch.object(entrypoint.os, 'umask') as mask, patch.object(entrypoint.os, 'execvp') as execute:
            manager = unittest.mock.Mock()
            manager.attach_mock(groups, 'groups'); manager.attach_mock(gid, 'gid'); manager.attach_mock(uid, 'uid'); manager.attach_mock(execute, 'execute')
            entrypoint.main()
            prepare.assert_called_once_with(Path('/data'))
            self.assertEqual(manager.mock_calls, [call.groups([]), call.gid(10001), call.uid(10001), call.execute('python', ['python', 'bot.py'])])
            mask.assert_called_once_with(0o077)

    def test_unexpected_identity_fails_closed(self):
        with patch.object(entrypoint.os, 'getuid', return_value=1234), patch.object(entrypoint.os, 'execvp') as execute:
            with self.assertRaises(RuntimeError): entrypoint.main()
            execute.assert_not_called()

    def test_volume_migration_never_chowns_symlink_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            volume = root / 'data'; volume.mkdir()
            outside = root / 'private'; outside.mkdir()
            (outside / 'secret').write_text('outside volume')
            (volume / 'file-link').symlink_to(outside / 'secret')
            (volume / 'dir-link').symlink_to(outside, target_is_directory=True)
            (volume / 'existing').write_text('preserved')
            with patch.object(entrypoint.os, 'chown') as chown:
                entrypoint.prepare_volume(volume)
                touched = {c.args[0] for c in chown.call_args_list}
                self.assertNotIn(outside / 'secret', touched)
                self.assertNotIn(volume / 'file-link', touched)
                self.assertNotIn(volume / 'dir-link', touched)
            self.assertEqual((volume / 'existing').read_text(), 'preserved')
            with self.assertRaises(RuntimeError): entrypoint.prepare_volume(volume / 'dir-link')
