from __future__ import annotations

from fastapi import APIRouter

from ..schemas.strategy import ComposeStrategyRequest, ComposeStrategyResponse, SyncStrategyFromFileRequest
from ..services.strategy_composer import compose_strategy, sync_strategy_from_file


router = APIRouter()


@router.post("/compose", response_model=ComposeStrategyResponse)
def compose_strategy_endpoint(payload: ComposeStrategyRequest) -> ComposeStrategyResponse:
    return compose_strategy(payload)


@router.post("/sync-file", response_model=ComposeStrategyResponse)
def sync_strategy_from_file_endpoint(payload: SyncStrategyFromFileRequest) -> ComposeStrategyResponse:
    return sync_strategy_from_file(payload)
