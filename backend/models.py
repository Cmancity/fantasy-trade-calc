from __future__ import annotations

from pydantic import BaseModel


class TradeRequest(BaseModel):
    side_a: list[str]
    side_b: list[str]


class ShopRequest(BaseModel):
    player_ids: list[str]
    favor_min_pct: float = 5.0
    favor_max_pct: float = 20.0


class PackageRequest(BaseModel):
    player_ids: list[str]
    favor_min_pct: float = 0.0
    favor_max_pct: float = 50.0
    target_roster_id: int | None = None
    positions: list[str] | None = None
