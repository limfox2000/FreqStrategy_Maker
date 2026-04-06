from __future__ import annotations

from fastapi import APIRouter

from ..schemas.strategy import ComposeStrategyRequest, ComposeStrategyResponse
from ..services.strategy_composer import compose_strategy


router = APIRouter()


@router.post("/compose", response_model=ComposeStrategyResponse)
def compose_strategy_endpoint(payload: ComposeStrategyRequest) -> ComposeStrategyResponse:
    return compose_strategy(payload)

