"""Fairness scoring for a proposed N-for-M player trade."""
from __future__ import annotations

# % gap between side totals. Tune these in one place.
FAIR_THRESHOLD = 0.05
SLIGHT_EDGE_THRESHOLD = 0.15


def evaluate_trade(side_a: list[dict], side_b: list[dict]) -> dict:
    total_a = sum(p["value"] for p in side_a)
    total_b = sum(p["value"] for p in side_b)
    bigger = max(total_a, total_b)
    gap_pct = 0.0 if bigger == 0 else abs(total_a - total_b) / bigger

    if gap_pct <= FAIR_THRESHOLD:
        verdict = "fair"
        winner = None
    elif gap_pct <= SLIGHT_EDGE_THRESHOLD:
        verdict = "slight edge"
        winner = "a" if total_a > total_b else "b"
    else:
        verdict = "lopsided"
        winner = "a" if total_a > total_b else "b"

    unvalued = [p["name"] for p in (side_a + side_b) if p.get("unvalued")]

    return {
        "side_a_total": total_a,
        "side_b_total": total_b,
        "gap_pct": round(gap_pct * 100, 1),
        "verdict": verdict,
        "favors": winner,
        "unvalued_players": unvalued,
    }
