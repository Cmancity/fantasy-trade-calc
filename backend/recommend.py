"""Heuristic roster needs/surplus analysis and trade-target suggestions.

This is intentionally simple (not a full optimizer): it ranks each position's
starter strength and bench depth against the league average, flags the
weakest/deepest positions, then looks for other rosters whose surplus lines
up with your need (and vice versa) to propose roughly fair swaps.
"""
from __future__ import annotations

from itertools import combinations

from . import trade_engine

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# A package including a surplus-position player should need less back for it
# to look good; one including a needed-position player should need more.
PACKAGE_SURPLUS_DISCOUNT = 0.85
PACKAGE_NEED_PREMIUM = 1.15
PACKAGE_POOL_CAP = 12
PACKAGE_NOTICEABLE_UPGRADE_PCT = 15.0


def starters_needed_by_position(roster_positions: list[str]) -> dict[str, float]:
    needed = {pos: float(roster_positions.count(pos)) for pos in SKILL_POSITIONS}
    # FLEX/SUPER_FLEX add fuzzy extra demand split across the positions
    # that typically fill those slots. This is an approximation, not a
    # league-rule-accurate count.
    flex_count = roster_positions.count("FLEX")
    needed["RB"] += 0.5 * flex_count
    needed["WR"] += 0.5 * flex_count

    super_flex_count = roster_positions.count("SUPER_FLEX")
    needed["QB"] += 0.7 * super_flex_count
    needed["RB"] += 0.15 * super_flex_count
    needed["WR"] += 0.15 * super_flex_count

    return needed


def position_strength(players: list[dict], starters_needed: dict[str, float]) -> dict[str, dict]:
    by_position: dict[str, list[dict]] = {pos: [] for pos in SKILL_POSITIONS}
    for p in players:
        if p["position"] in by_position:
            by_position[p["position"]].append(p)

    strength = {}
    for pos, pos_players in by_position.items():
        ranked = sorted(pos_players, key=lambda p: p["value"], reverse=True)
        n_starters = round(starters_needed.get(pos, 0))
        starters = ranked[:n_starters]
        bench = ranked[n_starters:]
        strength[pos] = {
            "starter_value": sum(p["value"] for p in starters),
            "bench_value": sum(p["value"] for p in bench),
            "bench": bench,
            "starters": starters,
        }
    return strength


def league_position_averages(all_strengths: list[dict[str, dict]]) -> dict[str, dict]:
    averages = {}
    n = len(all_strengths) or 1
    for pos in SKILL_POSITIONS:
        averages[pos] = {
            "starter_value": sum(s[pos]["starter_value"] for s in all_strengths) / n,
            "bench_value": sum(s[pos]["bench_value"] for s in all_strengths) / n,
        }
    return averages


def roster_needs_and_surplus(strength: dict[str, dict], league_avg: dict[str, dict]) -> dict[str, dict]:
    """Positive need_score => below-average starters (weak spot).
    Positive surplus_score => above-average bench depth (tradeable chip)."""
    result = {}
    for pos in SKILL_POSITIONS:
        result[pos] = {
            "need_score": league_avg[pos]["starter_value"] - strength[pos]["starter_value"],
            "surplus_score": strength[pos]["bench_value"] - league_avg[pos]["bench_value"],
        }
    return result


def suggest_trades(
    my_strength: dict[str, dict],
    my_needs: dict[str, dict],
    other_rosters: list[tuple[str, dict[str, dict], dict[str, dict]]],
    max_per_team: int = 3,
) -> list[dict]:
    """other_rosters: list of (team_label, their_strength, their_needs)"""
    suggestions = []

    my_surplus_positions = [pos for pos, n in my_needs.items() if n["surplus_score"] > 0]
    my_need_positions = [pos for pos, n in my_needs.items() if n["need_score"] > 0]

    for team_label, their_strength, their_needs in other_rosters:
        their_surplus_positions = [pos for pos, n in their_needs.items() if n["surplus_score"] > 0]
        their_need_positions = [pos for pos, n in their_needs.items() if n["need_score"] > 0]

        found_for_team = 0
        # I give from a position where I have surplus AND they have need.
        # I get from a position where they have surplus AND I have need.
        give_positions = [p for p in my_surplus_positions if p in their_need_positions]
        get_positions = [p for p in their_surplus_positions if p in my_need_positions]

        for give_pos in give_positions:
            for get_pos in get_positions:
                give_candidates = my_strength[give_pos]["bench"]
                get_candidates = their_strength[get_pos]["bench"]
                if not give_candidates or not get_candidates:
                    continue

                best_pair = None
                best_gap = None
                for give_player in give_candidates[:3]:
                    for get_player in get_candidates[:3]:
                        verdict = trade_engine.evaluate_trade([give_player], [get_player])
                        if verdict["verdict"] == "lopsided":
                            continue
                        if best_gap is None or verdict["gap_pct"] < best_gap:
                            best_gap = verdict["gap_pct"]
                            best_pair = (give_player, get_player, verdict)

                if best_pair and found_for_team < max_per_team:
                    give_player, get_player, verdict = best_pair
                    suggestions.append(
                        {
                            "with_team": team_label,
                            "give": give_player,
                            "get": get_player,
                            "verdict": verdict,
                            "reason": f"You have surplus at {give_pos}; they need it. "
                            f"They have surplus at {get_pos}; you need it.",
                        }
                    )
                    found_for_team += 1

    return suggestions


def find_shop_matches(
    my_selected: list[dict],
    other_rosters: list[tuple[str, list[dict]]],
    favor_min_pct: float,
    favor_max_pct: float,
    max_results: int = 25,
) -> list[dict]:
    """Deliberately asymmetric matcher: for personal use only, to surface offers
    where what you'd RECEIVE outvalues what you'd GIVE by a target margin
    (favor_min_pct-favor_max_pct). This is not a fairness check — it's meant to
    help you find offers worth proposing that lean in your favor, not to judge
    whether a trade is balanced."""
    matches = []

    def edge_pct(give_total: float, get_total: float) -> float | None:
        if give_total <= 0:
            return None
        return (get_total - give_total) / give_total * 100

    # 1-for-1: each shopped player against each individual player elsewhere.
    for mine in my_selected:
        for team_label, their_players in other_rosters:
            for theirs in their_players:
                if theirs["value"] <= 0:
                    continue
                pct = edge_pct(mine["value"], theirs["value"])
                if pct is not None and favor_min_pct <= pct <= favor_max_pct:
                    matches.append(
                        {
                            "type": "1-for-1",
                            "with_team": team_label,
                            "give": [mine],
                            "get": [theirs],
                            "give_total": mine["value"],
                            "get_total": theirs["value"],
                            "edge_pct": round(pct, 1),
                        }
                    )

    # Bundle: all shopped players together against one bigger target elsewhere.
    if len(my_selected) > 1:
        give_total = sum(p["value"] for p in my_selected)
        for team_label, their_players in other_rosters:
            for theirs in their_players:
                if theirs["value"] <= 0:
                    continue
                pct = edge_pct(give_total, theirs["value"])
                if pct is not None and favor_min_pct <= pct <= favor_max_pct:
                    matches.append(
                        {
                            "type": "bundle-for-1",
                            "with_team": team_label,
                            "give": my_selected,
                            "get": [theirs],
                            "give_total": give_total,
                            "get_total": theirs["value"],
                            "edge_pct": round(pct, 1),
                        }
                    )

    # Closest-to-fair-looking offers first — more likely the other side bites.
    matches.sort(key=lambda m: m["edge_pct"])
    return matches[:max_results]


def effective_give_value(my_needs: dict[str, dict], players: list[dict]) -> float:
    """What a package is really 'costing' you: a surplus-position player is
    discounted (you don't need it anyway), a needed-position player carries a
    premium (giving it up actually hurts), so the match search doesn't price
    every player at flat market value regardless of your own roster."""
    total = 0.0
    for p in players:
        scores = my_needs.get(p["position"])
        multiplier = 1.0
        if scores:
            # A position can show positive need AND positive surplus at once
            # (weak starters, deep bench) — need wins, since giving up a
            # needed position is costly regardless of bench depth.
            if scores["need_score"] > 0:
                multiplier = PACKAGE_NEED_PREMIUM
            elif scores["surplus_score"] > 0:
                multiplier = PACKAGE_SURPLUS_DISCOUNT
        total += p["value"] * multiplier
    return total


def find_package_matches(
    my_package: list[dict],
    my_needs: dict[str, dict],
    other_rosters: list[tuple[str, list[dict]]],
    favor_min_pct: float = 0.0,
    favor_max_pct: float = 50.0,
    max_combo_size: int = 3,
    max_per_team: int = 2,
    max_results: int = 20,
    positions: list[str] | None = None,
) -> list[dict]:
    """Finds multi-player return packages (1-3 players) for a multi-player
    package you're shopping, biased by your own positional need/surplus
    rather than treating every player at flat market value. When `positions`
    is given, every player in the return package must be one of them."""
    give_total_raw = sum(p["value"] for p in my_package)
    give_total_effective = effective_give_value(my_needs, my_package)
    if give_total_effective <= 0:
        return []

    position_filter = set(positions) if positions else None

    matches = []
    for team_label, their_players in other_rosters:
        pool = sorted(
            (p for p in their_players if p["value"] > 0 and (not position_filter or p["position"] in position_filter)),
            key=lambda p: p["value"],
            reverse=True,
        )
        pool = pool[:PACKAGE_POOL_CAP]

        team_matches = []
        for size in range(1, max_combo_size + 1):
            for combo in combinations(pool, size):
                get_total = sum(p["value"] for p in combo)
                edge_pct = (get_total - give_total_effective) / give_total_effective * 100
                if not (favor_min_pct <= edge_pct <= favor_max_pct):
                    continue
                positions = [p["position"] for p in combo]
                need_fill = sum(1 for pos in positions if my_needs.get(pos, {}).get("need_score", 0) > 0)
                team_matches.append(
                    {
                        "with_team": team_label,
                        "get": list(combo),
                        "get_positions": positions,
                        "get_total": get_total,
                        "give_total_raw": give_total_raw,
                        "give_total_effective": round(give_total_effective),
                        "edge_pct": round(edge_pct, 1),
                        "noticeable_upgrade": edge_pct >= PACKAGE_NOTICEABLE_UPGRADE_PCT,
                        "need_fill": need_fill,
                    }
                )

        team_matches.sort(key=lambda m: (-m["need_fill"], -m["edge_pct"], len(m["get"])))
        matches.extend(team_matches[:max_per_team])

    matches.sort(key=lambda m: (-m["need_fill"], -m["edge_pct"], len(m["get"])))
    return matches[:max_results]
