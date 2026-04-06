from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .ai_runtime import AiIdentity


class LlmAdapterError(RuntimeError):
    pass


@dataclass
class LlmCompletion:
    text: str
    request_id: str | None = None


def _join_url(base: str, suffix: str) -> str:
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def _shorten(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_sec: int = 120) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise LlmAdapterError(
            f"HTTP {exc.code} calling {url}: {_shorten(detail)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise LlmAdapterError(f"Network error calling {url}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmAdapterError(f"Invalid JSON response from {url}: {_shorten(raw)}") from exc

    if isinstance(data, dict) and "error" in data:
        raise LlmAdapterError(f"Provider error from {url}: {_shorten(json.dumps(data['error'], ensure_ascii=False))}")
    return data


def _extract_openai_chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmAdapterError("OpenAI-compatible response missing choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, str):
        text = content.strip()
        if not text:
            raise LlmAdapterError("OpenAI-compatible response content is empty")
        return text

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        merged = "\n".join(parts).strip()
        if merged:
            return merged
    raise LlmAdapterError("OpenAI-compatible response content is empty")


def _extract_openai_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if not isinstance(output, list):
        raise LlmAdapterError("Responses API payload missing output")
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    merged = "\n".join(parts).strip()
    if not merged:
        raise LlmAdapterError("Responses API content is empty")
    return merged


def _extract_claude_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise LlmAdapterError("Claude response missing content")
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    merged = "\n".join(parts).strip()
    if not merged:
        raise LlmAdapterError("Claude response content is empty")
    return merged


def _call_openai_compatible_chat(identity: AiIdentity, system_prompt: str, user_prompt: str) -> LlmCompletion:
    url = _join_url(identity.api_base, "/chat/completions")
    payload: dict[str, Any] = {
        "model": identity.model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = _post_json(
        url=url,
        payload=payload,
        headers={"Authorization": f"Bearer {identity.api_key}"},
    )
    return LlmCompletion(
        text=_extract_openai_chat_text(response),
        request_id=response.get("id"),
    )


def _call_openai_responses(identity: AiIdentity, system_prompt: str, user_prompt: str) -> LlmCompletion:
    url = _join_url(identity.api_base, "/responses")
    payload: dict[str, Any] = {
        "model": identity.model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": 3200,
        "reasoning": {"effort": identity.reasoning_effort},
    }
    response = _post_json(
        url=url,
        payload=payload,
        headers={"Authorization": f"Bearer {identity.api_key}"},
    )
    return LlmCompletion(
        text=_extract_openai_responses_text(response),
        request_id=response.get("id"),
    )


def _call_claude(identity: AiIdentity, system_prompt: str, user_prompt: str) -> LlmCompletion:
    url = _join_url(identity.api_base, "/messages")
    payload: dict[str, Any] = {
        "model": identity.model,
        "temperature": 0.2,
        "max_tokens": 3200,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    response = _post_json(
        url=url,
        payload=payload,
        headers={
            "x-api-key": identity.api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    return LlmCompletion(
        text=_extract_claude_text(response),
        request_id=response.get("id"),
    )


def complete_text(identity: AiIdentity, system_prompt: str, user_prompt: str) -> LlmCompletion:
    if not identity.api_key:
        raise LlmAdapterError(f"Missing API key for provider: {identity.provider}")

    if identity.provider == "claude":
        return _call_claude(identity, system_prompt, user_prompt)

    if identity.provider == "openai":
        try:
            return _call_openai_responses(identity, system_prompt, user_prompt)
        except LlmAdapterError:
            return _call_openai_compatible_chat(identity, system_prompt, user_prompt)

    if identity.provider in {"deepseek", "glm"}:
        return _call_openai_compatible_chat(identity, system_prompt, user_prompt)

    raise LlmAdapterError(f"Unsupported provider: {identity.provider}")
