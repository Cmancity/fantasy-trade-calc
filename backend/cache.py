"""Tiny TTL cache backed by on-disk JSON, so repeated runs don't re-fetch
large/slow-changing payloads (the Sleeper player catalog, FantasyCalc values)
on every request or every app restart."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

_MEM: dict[str, tuple[float, Any]] = {}


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


async def get_or_fetch(key: str, ttl_seconds: int, fetch: Callable[[], Any]) -> Any:
    now = time.time()

    if key in _MEM:
        expires_at, value = _MEM[key]
        if expires_at > now:
            return value

    path = _path(key)
    if path.exists():
        try:
            payload = json.loads(path.read_text())
            if payload["expires_at"] > now:
                _MEM[key] = (payload["expires_at"], payload["value"])
                return payload["value"]
        except (json.JSONDecodeError, KeyError):
            pass

    value = await fetch()
    expires_at = now + ttl_seconds
    _MEM[key] = (expires_at, value)
    path.write_text(json.dumps({"expires_at": expires_at, "value": value}))
    return value
