from __future__ import annotations

from typing import Any

from packages.storage.db import session_scope
from packages.storage.repositories import AppSettingsRepository

AI_BACKEND_SETTING_KEY = "ai_backend"
AI_BACKENDS = {"llm", "codex"}
DEFAULT_AI_BACKEND_CONFIG = {
    "backend": "llm",
    "codexCliPath": "",
    "codexTimeoutMs": 600000,
}


def normalize_ai_backend_config(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    backend = str(raw.get("backend") or DEFAULT_AI_BACKEND_CONFIG["backend"]).strip().lower()
    if backend not in AI_BACKENDS:
        backend = DEFAULT_AI_BACKEND_CONFIG["backend"]
    path = str(raw.get("codexCliPath") or raw.get("codex_cli_path") or "").strip()
    try:
        timeout_ms = int(raw.get("codexTimeoutMs") or raw.get("codex_timeout_ms") or 600000)
    except (TypeError, ValueError):
        timeout_ms = 600000
    timeout_ms = max(30000, min(1800000, timeout_ms))
    return {
        "backend": backend,
        "codexCliPath": path,
        "codexTimeoutMs": timeout_ms,
    }


def get_ai_backend_config() -> dict[str, Any]:
    with session_scope() as session:
        stored = AppSettingsRepository(session).get(
            AI_BACKEND_SETTING_KEY,
            DEFAULT_AI_BACKEND_CONFIG,
        )
    return normalize_ai_backend_config(stored)


def update_ai_backend_config(value: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_ai_backend_config(value)
    with session_scope() as session:
        AppSettingsRepository(session).set(AI_BACKEND_SETTING_KEY, normalized)
    return normalized
