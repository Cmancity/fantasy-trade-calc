from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import fantasycalc_client, recommend, sleeper_client, trade_engine, valuation, waivers
from .models import PackageRequest, ShopRequest, TradeRequest

app = FastAPI(title="Fantasy Trade Calculator")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def team_label(roster: dict, users_by_id: dict[str, dict]) -> str:
    user = users_by_id.get(roster.get("owner_id"), {})
    metadata = user.get("metadata") or {}
    return metadata.get("team_name") or user.get("display_name") or f"Team {roster.get('roster_id')}"


async def load_league_context(league_id: str, force_dynasty: bool | None = None):
    league = await sleeper_client.get_league(league_id)
    if not league:
        raise HTTPException(404, "League not found")
    rosters = await sleeper_client.get_rosters(league_id)
    users = await sleeper_client.get_league_users(league_id)
    users_by_id = {u["user_id"]: u for u in users}

    all_players = await sleeper_client.get_all_players()
    fc_params = fantasycalc_client.params_from_league(league, rosters)
    if force_dynasty is not None:
        fc_params["isDynasty"] = force_dynasty
    fc_values = await fantasycalc_client.get_values(fc_params)
    value_map = valuation.build_value_map(fc_values)

    return league, rosters, users_by_id, all_players, value_map, fc_params


def find_roster(rosters: list[dict], roster_id: int):
    for r in rosters:
        if r["roster_id"] == roster_id:
            return r
    raise HTTPException(404, "Roster not found in this league")


def compute_needs(league: dict, rosters: list[dict], all_players: dict, value_map: dict):
    """Shared by /recommendations, /analysis, and /suggest-package so all three
    agree on what counts as a need or a surplus for a given roster."""
    roster_positions = league.get("roster_positions", [])
    starters_needed = recommend.starters_needed_by_position(roster_positions)

    strengths_by_roster = {}
    for r in rosters:
        valued = valuation.valued_roster(r, all_players, value_map)
        strengths_by_roster[r["roster_id"]] = recommend.position_strength(valued, starters_needed)

    league_avg = recommend.league_position_averages(list(strengths_by_roster.values()))
    needs_by_roster = {
        rid: recommend.roster_needs_and_surplus(strength, league_avg)
        for rid, strength in strengths_by_roster.items()
    }
    return strengths_by_roster, needs_by_roster


@app.get("/api/user/{username}/leagues")
async def user_leagues(username: str, season: str = "2026"):
    try:
        user = await sleeper_client.get_user(username)
    except sleeper_client.SleeperNotFound:
        raise HTTPException(404, f"Sleeper user '{username}' not found")

    leagues = await sleeper_client.get_user_leagues(user["user_id"], season)
    return {
        "user_id": user["user_id"],
        "username": user.get("username", username),
        "leagues": [
            {"league_id": lg["league_id"], "name": lg["name"], "season": lg["season"]}
            for lg in leagues
        ],
    }


@app.get("/api/league/{league_id}")
async def league_overview(league_id: str):
    league, rosters, users_by_id, *_ = await load_league_context(league_id)
    teams = [
        {
            "roster_id": r["roster_id"],
            "owner_id": r.get("owner_id"),
            "team_name": team_label(r, users_by_id),
            "player_count": len(r.get("players") or []),
        }
        for r in rosters
    ]
    return {
        "league_id": league["league_id"],
        "name": league["name"],
        "season": league["season"],
        "roster_positions": league.get("roster_positions", []),
        "teams": teams,
    }


@app.get("/api/league/{league_id}/roster/{roster_id}/valued")
async def roster_valued(league_id: str, roster_id: int, force_dynasty: bool | None = None):
    _, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    roster = find_roster(rosters, roster_id)
    players = valuation.valued_roster(roster, all_players, value_map)
    players.sort(key=lambda p: p["value"], reverse=True)
    return {
        "roster_id": roster_id,
        "team_name": team_label(roster, users_by_id),
        "players": players,
        "total_value": sum(p["value"] for p in players),
    }


@app.post("/api/league/{league_id}/trade")
async def evaluate_trade(league_id: str, trade: TradeRequest, force_dynasty: bool | None = None):
    _, _, _, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    side_a = [valuation.valued_player(pid, all_players, value_map) for pid in trade.side_a]
    side_b = [valuation.valued_player(pid, all_players, value_map) for pid in trade.side_b]
    verdict = trade_engine.evaluate_trade(side_a, side_b)
    return {"side_a": side_a, "side_b": side_b, **verdict}


@app.get("/api/league/{league_id}/roster/{roster_id}/recommendations")
async def recommendations(league_id: str, roster_id: int, force_dynasty: bool | None = None):
    league, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    strengths_by_roster, needs_by_roster = compute_needs(league, rosters, all_players, value_map)

    if roster_id not in strengths_by_roster:
        raise HTTPException(404, "Roster not found in this league")

    my_strength = strengths_by_roster[roster_id]
    my_needs = needs_by_roster[roster_id]

    other_rosters = [
        (team_label(r, users_by_id), strengths_by_roster[r["roster_id"]], needs_by_roster[r["roster_id"]])
        for r in rosters
        if r["roster_id"] != roster_id
    ]

    suggestions = recommend.suggest_trades(my_strength, my_needs, other_rosters)

    return {
        "needs_summary": {
            pos: {
                "need_score": round(my_needs[pos]["need_score"]),
                "surplus_score": round(my_needs[pos]["surplus_score"]),
            }
            for pos in my_needs
        },
        "suggestions": suggestions,
    }


@app.get("/api/league/{league_id}/analysis")
async def league_analysis(league_id: str, force_dynasty: bool | None = None):
    league, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    _, needs_by_roster = compute_needs(league, rosters, all_players, value_map)
    totals_by_roster = {
        r["roster_id"]: sum(p["value"] for p in valuation.valued_roster(r, all_players, value_map))
        for r in rosters
    }

    teams = [
        {
            "roster_id": r["roster_id"],
            "team_name": team_label(r, users_by_id),
            "total_value": totals_by_roster[r["roster_id"]],
            "needs": {
                pos: {
                    "need_score": round(needs_by_roster[r["roster_id"]][pos]["need_score"]),
                    "surplus_score": round(needs_by_roster[r["roster_id"]][pos]["surplus_score"]),
                }
                for pos in needs_by_roster[r["roster_id"]]
            },
        }
        for r in rosters
    ]
    teams.sort(key=lambda t: t["total_value"], reverse=True)

    return {"teams": teams}


@app.get("/api/league/{league_id}/roster/{roster_id}/waivers")
async def league_waivers(
    league_id: str,
    roster_id: int,
    position: str | None = None,
    limit: int = 50,
    force_dynasty: bool | None = None,
):
    _, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    if roster_id not in {r["roster_id"] for r in rosters}:
        raise HTTPException(404, "Roster not found in this league")

    my_roster = find_roster(rosters, roster_id)
    my_players = valuation.valued_roster(my_roster, all_players, value_map)

    trending_adds = await sleeper_client.get_trending_players("add")
    candidates = waivers.valued_free_agents(rosters, all_players, value_map, trending_adds, position, limit)
    for c in candidates:
        c["worth_it"] = waivers.worth_it(my_players, c)

    return {"candidates": candidates}


@app.post("/api/league/{league_id}/roster/{roster_id}/shop")
async def shop_players(league_id: str, roster_id: int, shop: ShopRequest, force_dynasty: bool | None = None):
    _, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    if roster_id not in {r["roster_id"] for r in rosters}:
        raise HTTPException(404, "Roster not found in this league")

    my_selected = [valuation.valued_player(pid, all_players, value_map) for pid in shop.player_ids]
    other_rosters = [
        (team_label(r, users_by_id), valuation.valued_roster(r, all_players, value_map))
        for r in rosters
        if r["roster_id"] != roster_id
    ]

    matches = recommend.find_shop_matches(my_selected, other_rosters, shop.favor_min_pct, shop.favor_max_pct)
    return {"matches": matches}


@app.post("/api/league/{league_id}/roster/{roster_id}/suggest-package")
async def suggest_package(league_id: str, roster_id: int, req: PackageRequest, force_dynasty: bool | None = None):
    league, rosters, users_by_id, all_players, value_map, _ = await load_league_context(league_id, force_dynasty)
    if roster_id not in {r["roster_id"] for r in rosters}:
        raise HTTPException(404, "Roster not found in this league")

    if req.target_roster_id is not None:
        if req.target_roster_id == roster_id:
            raise HTTPException(400, "Target team can't be the same as your own team")
        if req.target_roster_id not in {r["roster_id"] for r in rosters}:
            raise HTTPException(404, "Target team not found in this league")

    _, needs_by_roster = compute_needs(league, rosters, all_players, value_map)
    my_needs = needs_by_roster[roster_id]
    my_package = [valuation.valued_player(pid, all_players, value_map) for pid in req.player_ids]

    other_rosters = [
        (team_label(r, users_by_id), valuation.valued_roster(r, all_players, value_map))
        for r in rosters
        if r["roster_id"] != roster_id and (req.target_roster_id is None or r["roster_id"] == req.target_roster_id)
    ]

    # Scoped to a single team: no cross-team flooding risk, so allow more
    # variety back from that one roster.
    max_per_team = 12 if req.target_roster_id is not None else 2
    max_results = 12 if req.target_roster_id is not None else 20

    matches = recommend.find_package_matches(
        my_package,
        my_needs,
        other_rosters,
        req.favor_min_pct,
        req.favor_max_pct,
        max_per_team=max_per_team,
        max_results=max_results,
        positions=req.positions,
    )

    return {
        "give_total_raw": sum(p["value"] for p in my_package),
        "give_total_effective": round(recommend.effective_give_value(my_needs, my_package)),
        "matches": matches,
    }


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
