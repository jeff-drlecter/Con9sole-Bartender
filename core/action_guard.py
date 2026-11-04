from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import asyncio
from weakref import WeakKeyDictionary

_ACTIVE: set[tuple[object, ...]] = set()


@contextmanager
def claim_action(*key: object) -> Iterator[bool]:
    """Reserve an action before any await; reject double clicks instead of queuing them.

    Shared outside cogs so a reload cannot open a second in-flight operation.
    This is a single-process guard, not a distributed lock.
    """
    if key in _ACTIVE:
        yield False
        return
    _ACTIVE.add(key)
    try:
        yield True
    finally:
        _ACTIVE.discard(key)


_LOOP_LOCKS = WeakKeyDictionary()


def shared_async_lock(*key):
    loop = asyncio.get_running_loop()
    locks = _LOOP_LOCKS.setdefault(loop, {})
    return locks.setdefault(key, asyncio.Lock())
