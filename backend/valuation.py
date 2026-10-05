"""Joins Sleeper player data to FantasyCalc trade values by sleeperId, and
builds roster views carrying that value info."""
from __future__ import annotations


def build_value_map(fc_values: list[dict]) -> dict[str, dict]:
    """sleeper player_id -> {value, position_rank, trend_30_day}"""
    value_map: dict[str, dict] = {}
    for entry in fc_values:
        player = entry.get("player", {})
        sleeper_id = player.get("sleeperId")
        if not sleeper_id:
            continue
        value_map[str(sleeper_id)] = {
            "value": entry.get("value", 0),
            "position_rank": entry.get("positionRank"),
            "trend_30_day": entry.get("trend30Day"),
        }
    return value_map


def player_name(player: dict) -> str:
    full_name = player.get("full_name")
    if full_name:
        return full_name
    first = player.get("first_name", "")
    last = player.get("last_name", "")
    name = f"{first} {last}".strip()
    return name or player.get("player_id", "Unknown")


def valued_player(player_id: str, all_players: dict, value_map: dict) -> dict:
    player = all_players.get(player_id, {})
    value_info = value_map.get(player_id)
    return {
        "player_id": player_id,
        "name": player_name(player) if player else f"Unknown ({player_id})",
        "position": player.get("position", "?"),
        "team": player.get("team"),
        "value": value_info["value"] if value_info else 0,
        "position_rank": value_info["position_rank"] if value_info else None,
        "trend_30_day": value_info["trend_30_day"] if value_info else None,
        "unvalued": value_info is None,
    }


def valued_roster(roster: dict, all_players: dict, value_map: dict) -> list[dict]:
    player_ids = roster.get("players") or []
    return [valued_player(pid, all_players, value_map) for pid in player_ids]
