import json
import os
from urllib import error, request

from utils.ai_prompt import load_ai_prompt
from utils.app_paths import app_path


SETTINGS_PATH = app_path("config", "ai_settings.json")
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
_PROBE_TIMEOUT_SEC = 45
THINKING_LEVELS = ("none", "low", "medium", "high")
DEFAULT_THINKING_LEVEL = "high"


def default_ai_settings():
    return {
        "deepseekApiKey": "",
        "enableAI": False,
        "requestUrl": DEFAULT_DEEPSEEK_BASE_URL,
        "model": "deepseek-v4-pro",
        "thinkingLevel": DEFAULT_THINKING_LEVEL,
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


def resolve_chat_completions_url(request_url):
    """Append /chat/completions to the documented OpenAI base_url."""
    url = str(request_url or "").strip().rstrip("/")
    if not url:
        url = DEFAULT_DEEPSEEK_BASE_URL
    return url + _CHAT_COMPLETIONS_SUFFIX


def thinking_params(thinking_level):
    """Map the single UI level to DeepSeek thinking / reasoning_effort."""
    level = str(thinking_level or "").strip().lower()
    if level not in THINKING_LEVELS:
        level = DEFAULT_THINKING_LEVEL
    if level == "none":
        return {"thinkingMode": "disabled", "reasoningEffort": ""}
    return {"thinkingMode": "enabled", "reasoningEffort": level}


def _thinking_level_from_raw(raw_settings):
    level = str(raw_settings.get("thinkingLevel", "") or "").strip().lower()
    if level in THINKING_LEVELS:
        return level
    thinking_mode = str(raw_settings.get("thinkingMode", "") or "").strip().lower()
    if thinking_mode == "disabled":
        return "none"
    effort = str(raw_settings.get("reasoningEffort", "") or "").strip().lower()
    if effort in {"low", "medium", "high"}:
        return effort
    return DEFAULT_THINKING_LEVEL


def sanitize_ai_settings(raw_settings):
    settings = default_ai_settings()
    if not isinstance(raw_settings, dict):
        return settings
    settings["deepseekApiKey"] = str(raw_settings.get("deepseekApiKey", "") or "").strip()
    settings["enableAI"] = bool(raw_settings.get("enableAI", False))
    settings["requestUrl"] = str(
        raw_settings.get("requestUrl", settings["requestUrl"]) or ""
    ).strip()
    settings["model"] = str(raw_settings.get("model", settings["model"]) or "").strip()
    settings["thinkingLevel"] = _thinking_level_from_raw(raw_settings)

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


def ai_enabled(settings=None):
    if settings is None:
        safe_settings = load_ai_settings()
    else:
        safe_settings = sanitize_ai_settings(settings)
    return bool(
        safe_settings["enableAI"]
        and safe_settings["deepseekApiKey"]
        and safe_settings["requestUrl"]
        and safe_settings["model"]
    )


def probe_ai_connection(settings):
    """POST a tiny Chat Completions request to verify key, base_url and model."""
    safe_settings = sanitize_ai_settings(settings)
    token = safe_settings["deepseekApiKey"]
    if not token:
        raise ValueError("请先填写 API 密钥 (api_key)。")
    if not safe_settings["requestUrl"]:
        raise ValueError("请先填写请求地址 (base_url)。")
    if not safe_settings["model"]:
        raise ValueError("请先填写模型名称 (model)。")
    url = resolve_chat_completions_url(safe_settings["requestUrl"])
    payload = {
        "model": safe_settings["model"],
        "messages": [{"role": "user", "content": "Reply with the word ok."}],
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    timeout_sec = min(
        _PROBE_TIMEOUT_SEC, max(10, int(safe_settings["requestTimeoutSec"]))
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise ValueError("连接失败（HTTP %s）：%s" % (exc.code, detail[:400])) from exc
    except error.URLError as exc:
        raise ValueError("连接失败：%s" % exc) from exc
    except (OSError, json.JSONDecodeError, TimeoutError) as exc:
        raise ValueError("连接失败：%s" % exc) from exc
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError("接口已响应，但返回格式不是 Chat Completions。")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    preview = str((message or {}).get("content") or "").strip()
    return {
        "url": url,
        "model": str(raw.get("model") or safe_settings["model"]).strip(),
        "preview": preview[:80],
    }


def ai_request_config(settings):
    safe_settings = sanitize_ai_settings(settings)
    params = thinking_params(safe_settings["thinkingLevel"])
    return {
        "requestUrl": resolve_chat_completions_url(safe_settings["requestUrl"]),
        "model": safe_settings["model"],
        "thinkingLevel": safe_settings["thinkingLevel"],
        "reasoningEffort": params["reasoningEffort"],
        "thinkingMode": params["thinkingMode"],
        "temperature": safe_settings["temperature"],
        "requestTimeoutSec": safe_settings["requestTimeoutSec"],
        "liabilityAppendRequirement": load_ai_prompt(),
    }
