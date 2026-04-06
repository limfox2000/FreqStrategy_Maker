from __future__ import annotations

from fastapi import APIRouter

from ..schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResponse
from ..services.backtest_runner import get_backtest_result, start_backtest


router = APIRouter()


@router.post("/run", response_model=BacktestRunResponse)
def run_backtest_endpoint(payload: BacktestRunRequest) -> BacktestRunResponse:
    return start_backtest(payload)


@router.get("/{job_id}/result", response_model=BacktestResultResponse)
def get_backtest_result_endpoint(job_id: str) -> BacktestResultResponse:
    return get_backtest_result(job_id)

