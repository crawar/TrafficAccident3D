import json
import os

from utils.ai_prompt import load_ai_prompt
from utils.app_paths import app_path


SETTINGS_PATH = app_path("config", "ai_settings.json")


def default_ai_settings():
    return {
        "deepseekApiKey": "",
        "enableLiabilityAnalysis": False,
        "regenerateLiabilityEachTime": True,
        "requestUrl": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-v4-pro",
        "reasoningEffort": "high",
        "thinkingMode": "enabled",
        "temperature": 0.1,
        "requestTimeoutSec": 120,
    }


def _normalize_float(raw_value, fallback):
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(fallback)


def _normalize_int(raw_value, fallback):
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(fallback)


def sanitize_ai_settings(raw_settings):
    settings = default_ai_settings()
    if not isinstance(raw_settings, dict):
        return settings
    settings["deepseekApiKey"] = str(raw_settings.get("deepseekApiKey", "") or "").strip()
    settings["enableLiabilityAnalysis"] = bool(
        raw_settings.get("enableLiabilityAnalysis", False)
    )
    settings["regenerateLiabilityEachTime"] = bool(
        raw_settings.get(
            "regenerateLiabilityEachTime",
            settings["regenerateLiabilityEachTime"],
        )
    )
    settings["requestUrl"] = str(
        raw_settings.get("requestUrl", settings["requestUrl"]) or ""
    ).strip()
    settings["model"] = str(raw_settings.get("model", settings["model"]) or "").strip()

    reasoning_effort = str(
        raw_settings.get("reasoningEffort", settings["reasoningEffort"]) or ""
    ).strip().lower()
    if reasoning_effort not in {"", "low", "medium", "high"}:
        reasoning_effort = settings["reasoningEffort"]
    settings["reasoningEffort"] = reasoning_effort

    thinking_mode = str(
        raw_settings.get("thinkingMode", settings["thinkingMode"]) or ""
    ).strip().lower()
    if thinking_mode not in {"default", "enabled", "disabled"}:
        thinking_mode = settings["thinkingMode"]
    settings["thinkingMode"] = thinking_mode

    temperature = _normalize_float(
        raw_settings.get("temperature", settings["temperature"]),
        settings["temperature"],
    )
    settings["temperature"] = min(2.0, max(0.0, temperature))

    timeout_sec = _normalize_int(
        raw_settings.get("requestTimeoutSec", settings["requestTimeoutSec"]),
        settings["requestTimeoutSec"],
    )
    settings["requestTimeoutSec"] = min(600, max(10, timeout_sec))
    return settings


def load_ai_settings():
    if not os.path.isfile(SETTINGS_PATH):
        return default_ai_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return sanitize_ai_settings(json.load(f))
    except (OSError, json.JSONDecodeError):
        return default_ai_settings()


def save_ai_settings(settings):
    safe_settings = sanitize_ai_settings(settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(safe_settings, f, ensure_ascii=False, indent=2)
    return safe_settings


def ai_liability_enabled(settings):
    safe_settings = sanitize_ai_settings(settings)
    return bool(
        safe_settings["enableLiabilityAnalysis"]
        and safe_settings["deepseekApiKey"]
        and safe_settings["requestUrl"]
        and safe_settings["model"]
    )


def ai_request_config(settings):
    safe_settings = sanitize_ai_settings(settings)
    return {
        "requestUrl": safe_settings["requestUrl"],
        "model": safe_settings["model"],
        "reasoningEffort": safe_settings["reasoningEffort"],
        "thinkingMode": safe_settings["thinkingMode"],
        "temperature": safe_settings["temperature"],
        "requestTimeoutSec": safe_settings["requestTimeoutSec"],
        "liabilityAppendRequirement": load_ai_prompt(),
    }
