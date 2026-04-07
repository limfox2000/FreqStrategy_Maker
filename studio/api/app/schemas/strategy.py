from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyBaseConfig(BaseModel):
    timeframe: str = Field(default="1m")
    can_short: bool = Field(default=True)


class StrategyModules(BaseModel):
    indicator_factor_version_id: str | None = None
    position_adjustment_version_id: str | None = None
    risk_system_version_id: str | None = None


class StrategyValidationConfig(BaseModel):
    enable: bool = Field(default=True)
    pair: str = Field(default="XRP/USDT:USDT")
    timeframe: str | None = Field(default=None)
    timerange: str = Field(default="20251220-20260306")
    max_repair_rounds: int = Field(default=2, ge=0, le=3)


class ComposeStrategyRequest(BaseModel):
    strategy_name: str = Field(min_length=3)
    requirement: str = Field(default="Integrate module logic into a production-ready freqtrade strategy.", min_length=5)
    base: StrategyBaseConfig
    modules: StrategyModules | None = None
    base_strategy_code: str | None = Field(default=None)
    base_build_id: str | None = Field(default=None)
    validation: StrategyValidationConfig = Field(default_factory=StrategyValidationConfig)


class SyncStrategyFromFileRequest(BaseModel):
    build_id: str = Field(min_length=5)


class ComposeStrategyResponse(BaseModel):
    build_id: str
    strategy_file: str
    lint_ok: bool
    warnings: list[str]
    optimization_note: str
    source_versions: dict[str, str]
    strategy_code: str
    validation_passed: bool = True
    validation_logs: list[str] = Field(default_factory=list)
    repair_rounds: int = 0
