"""Thin async client for the public, read-only, no-auth Sleeper API.
Docs: https://docs.sleeper.com/"""
from __future__ import annotations

import httpx

from . import cache

BASE = "https://api.sleeper.app/v1"

# The full player catalog is ~5MB and changes rarely intraday.
PLAYERS_TTL = 24 * 60 * 60
# Leagues/rosters/users change as the season progresses (trades, waivers).
LEAGUE_TTL = 5 * 60


class SleeperNotFound(Exception):
    pass


async def _get(client: httpx.AsyncClient, path: str) -> dict | list:
    resp = await client.get(f"{BASE}{path}")
    if resp.status_code == 404:
        raise SleeperNotFound(path)
    resp.raise_for_status()
    return resp.json()


async def get_user(username: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        data = await _get(client, f"/user/{username}")
    if not data:
        raise SleeperNotFound(username)
    return data


async def get_user_leagues(user_id: str, season: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        return await _get(client, f"/user/{user_id}/leagues/nfl/{season}")


async def get_league(league_id: str) -> dict:
    async def fetch():
        async with httpx.AsyncClient(timeout=10) as client:
            return await _get(client, f"/league/{league_id}")

    return await cache.get_or_fetch(f"league_{league_id}", LEAGUE_TTL, fetch)


async def get_rosters(league_id: str) -> list[dict]:
    async def fetch():
        async with httpx.AsyncClient(timeout=10) as client:
            return await _get(client, f"/league/{league_id}/rosters")

    return await cache.get_or_fetch(f"rosters_{league_id}", LEAGUE_TTL, fetch)


async def get_league_users(league_id: str) -> list[dict]:
    async def fetch():
        async with httpx.AsyncClient(timeout=10) as client:
            return await _get(client, f"/league/{league_id}/users")

    return await cache.get_or_fetch(f"users_{league_id}", LEAGUE_TTL, fetch)


async def get_all_players() -> dict:
    async def fetch():
        async with httpx.AsyncClient(timeout=30) as client:
            return await _get(client, "/players/nfl")

    return await cache.get_or_fetch("players_nfl", PLAYERS_TTL, fetch)


# Sitewide (not league-scoped) add/drop activity over the lookback window.
TRENDING_TTL = 30 * 60


async def get_trending_players(kind: str = "add", lookback_hours: int = 24, limit: int = 100) -> dict[str, int]:
    async def fetch():
        async with httpx.AsyncClient(timeout=10) as client:
            data = await _get(
                client, f"/players/nfl/trending/{kind}?lookback_hours={lookback_hours}&limit={limit}"
            )
        return {item["player_id"]: item["count"] for item in data}

    return await cache.get_or_fetch(f"trending_{kind}_{lookback_hours}_{limit}", TRENDING_TTL, fetch)
