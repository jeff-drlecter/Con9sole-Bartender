"""Check the deployed bot's effective identity without reading its environment."""
import os
from pathlib import Path
import sys


def main():
    if '--self-test' in sys.argv:
        assert os.getuid() == 10001 and os.getgid() == 10001
        assert os.getgroups() == []
        existing = Path('/data/existing.txt')
        assert existing.read_text() == 'preserve me'
        existing.write_text('still writable')
        probe = Path('/data/identity-probe')
        probe.write_text('ok')
        assert probe.stat().st_mode & 0o077 == 0
        probe.unlink()
        print('Verified non-root identity, existing volume access, and private file mode')
        return
    matches = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            args = (directory / 'cmdline').read_bytes().split(b'\0')
            if b'bot.py' not in args:
                continue
            status = dict(line.split(':', 1) for line in (directory / 'status').read_text().splitlines() if ':' in line)
            assert all(int(v) == 10001 for v in status['Uid'].split()), 'Bot retains root/other UID'
            assert all(int(v) == 10001 for v in status['Gid'].split()), 'Unexpected bot GID'
            matches.append(directory.name)
        except FileNotFoundError:
            continue
    assert matches, 'No bot.py process found'
    print('Verified bot runs as UID/GID 10001:', ', '.join(matches))


if __name__ == '__main__':
    main()
