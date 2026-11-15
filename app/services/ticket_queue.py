from __future__ import annotations

import asyncio

_locks: dict[tuple[int, int], asyncio.Lock] = {}


def lock_for(chat_id: int, trip_id: int) -> asyncio.Lock:
    key = (chat_id, trip_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock
