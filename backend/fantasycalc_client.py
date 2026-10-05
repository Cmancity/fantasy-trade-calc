"""Thin async client for the free, public FantasyCalc trade-value feed.
https://api.fantasycalc.com/values/current

Each returned player entry includes a `sleeperId`, so values join directly
onto Sleeper roster data with no name-matching needed."""
from __future__ import annotations

import httpx

from . import cache

BASE = "https://api.fantasycalc.com/values/current"

# FantasyCalc recomputes periodically through the week; a few hours of
# staleness is an acceptable trade for not re-fetching on every request.
VALUES_TTL = 6 * 60 * 60

_SUPPORTED_TEAM_COUNTS = (8, 10, 12, 14)
_SUPPORTED_PPR = (0, 0.5, 1)


def _nearest(value: float, options: tuple[float, ...]) -> float:
    return min(options, key=lambda opt: abs(opt - value))


def params_from_league(league: dict, rosters: list[dict]) -> dict:
    """Map a Sleeper league's settings onto FantasyCalc's value-feed params."""
    roster_positions = league.get("roster_positions", [])
    num_qbs = 2 if "SUPER_FLEX" in roster_positions else 1

    scoring = league.get("scoring_settings", {})
    ppr = _nearest(float(scoring.get("rec", 0)), _SUPPORTED_PPR)

    num_teams = int(_nearest(len(rosters) or league.get("total_rosters", 12), _SUPPORTED_TEAM_COUNTS))

    settings = league.get("settings", {})
    # Sleeper doesn't have one clean "is this dynasty" flag; these are the
    # best available signals. The UI exposes a manual override as a fallback.
    is_dynasty = bool(settings.get("taxi_slots")) or bool(league.get("previous_league_id")) or settings.get("type") == 2

    return {"isDynasty": is_dynasty, "numQbs": num_qbs, "numTeams": num_teams, "ppr": ppr}


async def get_values(params: dict) -> list[dict]:
    cache_key = "values_" + "_".join(f"{k}={v}" for k, v in sorted(params.items()))

    async def fetch():
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(BASE, params=params)
            resp.raise_for_status()
            return resp.json()

    return await cache.get_or_fetch(cache_key, VALUES_TTL, fetch)
