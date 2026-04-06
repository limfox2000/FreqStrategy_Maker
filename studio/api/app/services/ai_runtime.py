from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os

from ..schemas.ai import AiModelPreset, AiModelsResponse, PersonaResponse
from .storage import DATA_DIR, read_json, write_json


AI_DIR = DATA_DIR / "ai"
AI_CONFIG_PATH = AI_DIR / "config.json"
AI_PERSONA_PATH = AI_DIR / "persona.md"
AI_PERSONA_META_PATH = AI_DIR / "persona_meta.json"
AI_SECRETS_PATH = AI_DIR / "secrets.json"


MODEL_PRESETS: list[dict[str, str]] = [
    {
        "key": "codex-xhigh",
        "label": "GPT Codex XHigh",
        "provider": "openai",
        "model": "gpt-5.3-codex",
        "summary": "Codex 超高推理预设（固定）。",
        "mode": "codex",
        "reasoning_effort": "xhigh",
    },
    {
        "key": "deepseek-chat",
        "label": "DeepSeek Chat",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "summary": "DeepSeek Chat 预设（固定）。",
        "mode": "chat",
        "reasoning_effort": "medium",
    },
    {
        "key": "glm-reasoner",
        "label": "GLM 5.1",
        "provider": "glm",
        "model": "glm-5.1",
        "summary": "GLM 5.1 预设（固定）。",
        "mode": "reasoner",
        "reasoning_effort": "high",
    },
    {
        "key": "claude-code",
        "label": "Claude Code 4.6",
        "provider": "claude",
        "model": "claude-4.6",
        "summary": "Claude 4.6 强模型预设（固定）。",
        "mode": "code",
        "reasoning_effort": "high",
    },
]

MODEL_MAP = {item["key"]: item for item in MODEL_PRESETS}

DEFAULT_CONFIG = {
    "active_model_key": "deepseek-chat",
}

DEFAULT_SECRETS = {
    "openai": "",
    "deepseek": "",
    "glm": "",
    "claude": "",
}

PROVIDER_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "glm": "GLM_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

PROVIDER_BASE_URL_DEFAULT = {
    "openai": "https://right.codes/codex/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "claude": "https://api.anthropic.com/v1",
}

MODEL_BASE_URL_DEFAULT = {
    "codex-xhigh": "https://right.codes/codex/v1",
}

PROVIDER_BASE_ENV_MAP = {
    "openai": "OPENAI_BASE_URL",
    "deepseek": "DEEPSEEK_BASE_URL",
    "glm": "GLM_BASE_URL",
    "claude": "ANTHROPIC_BASE_URL",
}

MODEL_BASE_ENV_MAP = {
    "codex-xhigh": "CODEX_BASE_URL",
}

DEFAULT_PERSONA = """# Freqtrade Strategy Architect

你是一个策略工程师，目标是：
1. 在可解释的前提下输出可执行 freqtrade 策略代码。
2. 先保证风险控制，再追求收益。
3. 输出代码结构稳定，便于继续迭代。
"""


@dataclass
class AiIdentity:
    provider: str
    model: str
    mode: str
    reasoning_effort: str
    preset_key: str
    preset_label: str
    persona_md: str
    enable_live_call: bool
    api_base: str
    api_key: str


def _safe_model_key(raw_key: str) -> str:
    if raw_key in MODEL_MAP:
        return raw_key
    return DEFAULT_CONFIG["active_model_key"]


def ensure_ai_files() -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)

    if not AI_CONFIG_PATH.exists():
        write_json(AI_CONFIG_PATH, DEFAULT_CONFIG)
    else:
        config = read_json(AI_CONFIG_PATH)
        if "active_model_key" not in config:
            provider = str(config.get("provider", "")).lower()
            inferred = DEFAULT_CONFIG["active_model_key"]
            if provider == "openai":
                inferred = "codex-xhigh"
            elif provider == "deepseek":
                inferred = "deepseek-chat"
            elif provider == "glm":
                inferred = "glm-reasoner"
            elif provider == "claude":
                inferred = "claude-code"

            write_json(AI_CONFIG_PATH, {"active_model_key": _safe_model_key(inferred)})
        else:
            config["active_model_key"] = _safe_model_key(str(config.get("active_model_key", "")))
            write_json(AI_CONFIG_PATH, config)

    if not AI_PERSONA_PATH.exists():
        AI_PERSONA_PATH.write_text(DEFAULT_PERSONA, encoding="utf-8")
    if not AI_PERSONA_META_PATH.exists():
        write_json(AI_PERSONA_META_PATH, {"updated_at": datetime.now(timezone.utc).isoformat()})
    if not AI_SECRETS_PATH.exists():
        write_json(AI_SECRETS_PATH, DEFAULT_SECRETS)


ensure_ai_files()


def list_models() -> AiModelsResponse:
    ensure_ai_files()
    config = read_json(AI_CONFIG_PATH)
    active_key = _safe_model_key(str(config.get("active_model_key", "")))
    secret_data = read_json(AI_SECRETS_PATH)

    def provider_has_key(provider: str) -> bool:
        if provider == "template":
            return True
        env_name = PROVIDER_ENV_MAP.get(provider, "")
        env_value = os.getenv(env_name, "").strip() if env_name else ""
        if env_value:
            return True
        file_value = str(secret_data.get(provider, "")).strip()
        return bool(file_value)

    models = [
        AiModelPreset(
            key=item["key"],
            label=item["label"],
            provider=item["provider"],  # type: ignore[arg-type]
            model=item["model"],
            summary=item["summary"],
            api_key_configured=provider_has_key(item["provider"]),
        )
        for item in MODEL_PRESETS
    ]
    return AiModelsResponse(
        active_model_key=active_key,
        secrets_file=str(AI_SECRETS_PATH),
        models=models,
    )


def set_active_model(model_key: str) -> AiModelsResponse:
    ensure_ai_files()
    if model_key not in MODEL_MAP:
        raise ValueError(f"Unknown model key: {model_key}")
    write_json(AI_CONFIG_PATH, {"active_model_key": model_key})
    return list_models()


def get_persona() -> PersonaResponse:
    ensure_ai_files()
    meta = read_json(AI_PERSONA_META_PATH)
    return PersonaResponse(
        content=AI_PERSONA_PATH.read_text(encoding="utf-8"),
        updated_at=meta["updated_at"],
    )


def set_persona(content: str) -> PersonaResponse:
    ensure_ai_files()
    AI_PERSONA_PATH.write_text(content, encoding="utf-8")
    updated_at = datetime.now(timezone.utc).isoformat()
    write_json(AI_PERSONA_META_PATH, {"updated_at": updated_at})
    return PersonaResponse(content=content, updated_at=updated_at)


def get_provider_api_key(provider: str) -> str:
    ensure_ai_files()
    env_name = PROVIDER_ENV_MAP.get(provider, "")
    env_value = os.getenv(env_name, "").strip() if env_name else ""
    if env_value:
        return env_value
    secret_data = read_json(AI_SECRETS_PATH)
    return str(secret_data.get(provider, "")).strip()


def get_provider_base_url(provider: str) -> str:
    env_name = PROVIDER_BASE_ENV_MAP.get(provider, "")
    env_value = os.getenv(env_name, "").strip() if env_name else ""
    if env_value:
        return env_value.rstrip("/")
    return PROVIDER_BASE_URL_DEFAULT.get(provider, "").rstrip("/")


def get_model_base_url(model_key: str, provider: str) -> str:
    model_env_name = MODEL_BASE_ENV_MAP.get(model_key, "")
    model_env_value = os.getenv(model_env_name, "").strip() if model_env_name else ""
    if model_env_value:
        return model_env_value.rstrip("/")

    model_default = MODEL_BASE_URL_DEFAULT.get(model_key, "").strip()
    if model_default:
        return model_default.rstrip("/")

    return get_provider_base_url(provider)


def get_ai_identity() -> AiIdentity:
    ensure_ai_files()
    config = read_json(AI_CONFIG_PATH)
    key = _safe_model_key(str(config.get("active_model_key", "")))
    preset = MODEL_MAP[key]
    persona = AI_PERSONA_PATH.read_text(encoding="utf-8")
    return AiIdentity(
        provider=preset["provider"],
        model=preset["model"],
        mode=preset["mode"],
        reasoning_effort=preset["reasoning_effort"],
        preset_key=key,
        preset_label=preset["label"],
        persona_md=persona,
        enable_live_call=False,
        api_base=get_model_base_url(key, preset["provider"]),
        api_key=get_provider_api_key(preset["provider"]),
    )


def optimize_strategy_code(draft_code: str, source_versions: dict[str, str]) -> tuple[str, str]:
    identity = get_ai_identity()
    persona_line = next((line.strip() for line in identity.persona_md.splitlines() if line.strip()), "")
    tag = (
        "\n".join(
            [
                '"""',
                "AI-composed Strategy Artifact",
                f"preset={identity.preset_key}",
                f"provider={identity.provider}",
                f"model={identity.model}",
                f"mode={identity.mode}",
                f"reasoning={identity.reasoning_effort}",
                f"persona={persona_line[:120]}",
                f"sources={source_versions}",
                '"""',
            ]
        )
        + "\n\n"
    )

    optimized = draft_code
    if "process_only_new_candles = True" not in optimized:
        optimized = optimized.replace(
            "startup_candle_count = 240",
            "process_only_new_candles = True\n    startup_candle_count = 240",
        )

    note = (
        f"策略已由 {identity.preset_label} 参与封装，"
        f"并写入 persona 身份与来源模块标记。"
    )
    return tag + optimized, note
