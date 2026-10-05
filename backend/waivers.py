"""Waiver-wire discovery: which rosterable players in the league are unowned,
how their value is trending, and whether picking one up actually beats what's
on your own bench."""
from __future__ import annotations

from . import valuation

RELEVANT_POSITIONS = ("QB", "RB", "WR", "TE")


def free_agent_ids(rosters: list[dict], all_players: dict) -> set[str]:
    rostered: set[str] = set()
    for r in rosters:
        rostered.update(r.get("players") or [])

    return {
        pid
        for pid, p in all_players.items()
        if pid not in rostered and p.get("position") in RELEVANT_POSITIONS and p.get("team")
    }


def valued_free_agents(
    rosters: list[dict],
    all_players: dict,
    value_map: dict,
    trending_adds: dict[str, int],
    position: str | None = None,
    limit: int = 50,
) -> list[dict]:
    ids = free_agent_ids(rosters, all_players)
    players = [valuation.valued_player(pid, all_players, value_map) for pid in ids]
    # Drop deep-irrelevant players with no FantasyCalc value at all — the
    # waiver wire is about rosterable depth, not the entire NFL player pool.
    players = [p for p in players if not p["unvalued"]]
    if position:
        players = [p for p in players if p["position"] == position]
    for p in players:
        p["trending_add_count"] = trending_adds.get(p["player_id"], 0)

    players.sort(key=lambda p: p["value"], reverse=True)
    return players[:limit]


def worth_it(my_players: list[dict], candidate: dict, min_edge_pct: float = 10.0) -> dict:
    """Compares a waiver candidate to the weakest player you roster at the
    same position — your realistic drop candidate — rather than to your
    whole roster, since that's the actual swap you'd be making."""
    same_pos = [p for p in my_players if p["position"] == candidate["position"]]
    reference = min(same_pos, key=lambda p: p["value"]) if same_pos else None

    if reference is None or reference["value"] <= 0:
        return {"verdict": "no bench reference", "edge_pct": None, "drop_candidate": reference}

    edge_pct = (candidate["value"] - reference["value"]) / reference["value"] * 100
    if edge_pct >= min_edge_pct:
        verdict = "worth it"
    elif edge_pct >= 0:
        verdict = "marginal"
    else:
        verdict = "skip"

    return {"verdict": verdict, "edge_pct": round(edge_pct, 1), "drop_candidate": reference}
