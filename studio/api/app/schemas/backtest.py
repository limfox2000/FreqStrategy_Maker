from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "finished", "failed"]


class BacktestRunRequest(BaseModel):
    build_id: str
    pair: str = Field(default="XRP/USDT:USDT")
    timeframe: str = Field(default="1m")
    timerange: str = Field(default="20251220-20260306")


class BacktestRunResponse(BaseModel):
    job_id: str
    status: JobStatus


class BacktestSummary(BaseModel):
    trades: int = 0
    winrate: float = 0.0
    profit_total_pct: float = 0.0
    profit_total_abs: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float | None = None
    market_change_pct: float = 0.0


class BacktestResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    logs: list[str] = Field(default_factory=list)
    summary: BacktestSummary | None = None
    series: dict = Field(default_factory=dict)
    artifacts: dict = Field(default_factory=dict)
    ai_review: str | None = None
    repair_rounds: int = 0
    error: str | None = None
