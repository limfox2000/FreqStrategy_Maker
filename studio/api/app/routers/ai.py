from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.ai import AiModelsResponse, AiSwitchRequest, PersonaRequest, PersonaResponse
from ..services.ai_runtime import get_persona, list_models, set_active_model, set_persona


router = APIRouter()


@router.get("/models", response_model=AiModelsResponse)
def list_models_endpoint() -> AiModelsResponse:
    return list_models()


@router.put("/models/active", response_model=AiModelsResponse)
def set_active_model_endpoint(payload: AiSwitchRequest) -> AiModelsResponse:
    try:
        return set_active_model(payload.model_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/persona", response_model=PersonaResponse)
def get_persona_endpoint() -> PersonaResponse:
    return get_persona()


@router.put("/persona", response_model=PersonaResponse)
def set_persona_endpoint(payload: PersonaRequest) -> PersonaResponse:
    return set_persona(payload.content)

