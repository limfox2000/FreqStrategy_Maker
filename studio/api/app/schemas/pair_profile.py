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
