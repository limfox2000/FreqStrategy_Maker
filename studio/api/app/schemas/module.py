from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CardType = Literal["indicator_factor", "position_adjustment", "risk_system"]


class ModuleContext(BaseModel):
    timeframe: str = Field(default="1m")
    pair: str = Field(default="XRP/USDT:USDT")
    can_short: bool = Field(default=True)


class GenerateModuleRequest(BaseModel):
    card_type: CardType
    requirement: str = Field(min_length=5)
    context: ModuleContext
    optimize_target_code: str | None = Field(default=None)
    optimize_from_version_id: str | None = Field(default=None)


class GenerateModuleResponse(BaseModel):
    version_id: str
    card_type: CardType
    module_code: str
    params: dict[str, float | int | str | bool]
    explain: str
