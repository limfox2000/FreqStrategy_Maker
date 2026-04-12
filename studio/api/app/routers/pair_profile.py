from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.pair_profile import PairProfilePayload, PairProfileResponse
from ..services.pair_profile import get_pair_profile, save_pair_profile


router = APIRouter()


@router.get("", response_model=PairProfileResponse)
def get_pair_profile_endpoint() -> PairProfileResponse:
    return get_pair_profile()


@router.put("", response_model=PairProfileResponse)
def save_pair_profile_endpoint(payload: PairProfilePayload) -> PairProfileResponse:
    try:
        return save_pair_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

