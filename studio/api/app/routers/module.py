from __future__ import annotations

from fastapi import APIRouter

from ..schemas.module import GenerateModuleRequest, GenerateModuleResponse
from ..services.freqtrade_skill import generate_module


router = APIRouter()


@router.post("/generate", response_model=GenerateModuleResponse)
def generate_module_endpoint(payload: GenerateModuleRequest) -> GenerateModuleResponse:
    return generate_module(payload)

