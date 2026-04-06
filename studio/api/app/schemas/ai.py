from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AiProvider = Literal["template", "openai", "deepseek", "glm", "claude"]


class AiModelPreset(BaseModel):
    key: str
    label: str
    provider: AiProvider
    model: str
    summary: str
    api_key_configured: bool


class AiModelsResponse(BaseModel):
    active_model_key: str
    secrets_file: str
    models: list[AiModelPreset]


class AiSwitchRequest(BaseModel):
    model_key: str = Field(min_length=3)


class PersonaRequest(BaseModel):
    content: str = Field(min_length=1)


class PersonaResponse(BaseModel):
    content: str
    updated_at: str
