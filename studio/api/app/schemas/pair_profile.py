from __future__ import annotations

from pydantic import BaseModel, Field


PairProfileValue = int | float | str | bool


class PairProfilePayload(BaseModel):
    defaults: dict[str, PairProfileValue] = Field(default_factory=dict)
    pairs: dict[str, dict[str, PairProfileValue]] = Field(default_factory=dict)


class PairProfileResponse(PairProfilePayload):
    updated_at: str
    storage_file: str
    freqtrade_file: str


class PairProfilePreviewRequest(BaseModel):
    pair: str = Field(default="XRP/USDT:USDT")
    timeframe: str = Field(default="2h")
    timerange: str = Field(default="20251220-20260306")
    max_points: int = Field(default=1800, ge=400, le=6000)


class PairProfilePreviewResponse(BaseModel):
    requested_pair: str
    resolved_pair: str
    pair_candidates: list[str] = Field(default_factory=list)
    matched_pair_key: str | None = None
    timeframe: str
    timerange: str
    effective_attrs: dict = Field(default_factory=dict)
    pair_params: dict = Field(default_factory=dict)
    zones: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    series: dict = Field(default_factory=dict)
