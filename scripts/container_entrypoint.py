"""Prepare the persistent volume, then permanently drop privileges before startup."""
from __future__ import annotations

import os
from pathlib import Path
import sys

APP_UID = APP_GID = 10001


def prepare_volume(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError('Persistent data directory must not be a symlink')
    path.mkdir(parents=True, exist_ok=True)
    # Do not follow links or traverse other filesystems while migrating old root-owned data.
    device = path.stat().st_dev
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()
                   and (Path(root) / name).stat().st_dev == device]
        for target in [Path(root), *(Path(root) / name for name in files)]:
            if target.is_symlink():
                continue
            info = target.stat()
            if info.st_dev == device and (info.st_uid, info.st_gid) != (APP_UID, APP_GID):
                os.chown(target, APP_UID, APP_GID, follow_symlinks=False)


def main() -> None:
    if os.getuid() == 0:
        prepare_volume(Path('/data'))
        os.setgroups([])
        os.setgid(APP_GID)
        os.setuid(APP_UID)
    if os.getuid() != APP_UID or os.getgid() != APP_GID:
        raise RuntimeError('Unexpected application identity')
    os.umask(0o077)
    if len(sys.argv) < 2:
        raise RuntimeError('Missing application command')
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
