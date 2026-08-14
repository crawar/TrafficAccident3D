import json
import os
import re

from utils.app_paths import app_path

DEFAULT_MEASUREMENT_SAVE_PORT = 8765

SETTINGS_PATH = app_path("config", "measurement_port.json")

_SAVE_URL_PATTERN = re.compile(
    r"http://127\.0\.0\.1:\d+/save-measurements"
)


def default_measurement_port_settings():
    return {
        "silentRandom": True,
        "port": DEFAULT_MEASUREMENT_SAVE_PORT,
    }


def sanitize_measurement_port_settings(raw_settings):
    settings = default_measurement_port_settings()
    if not isinstance(raw_settings, dict):
        return settings
    settings["silentRandom"] = bool(
        raw_settings.get("silentRandom", settings["silentRandom"])
    )
    try:
        port = int(raw_settings.get("port", settings["port"]))
    except (TypeError, ValueError):
        port = settings["port"]
    if port < 1 or port > 65535:
        port = settings["port"]
    settings["port"] = port
    return settings


def load_measurement_port_settings():
    if not os.path.isfile(SETTINGS_PATH):
        return default_measurement_port_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_measurement_port_settings()
    return sanitize_measurement_port_settings(raw)


def save_measurement_port_settings(raw_settings):
    settings = sanitize_measurement_port_settings(raw_settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings


def save_url_for_port(port):
    return f"http://127.0.0.1:{int(port)}/save-measurements"


def rewrite_html_save_measurements_url(html_path, port):
    """Rewrite all local save-measurements URLs in an HTML file to the given port."""
    html_path = os.path.abspath(html_path)
    new_url = save_url_for_port(port)
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    updated = _SAVE_URL_PATTERN.sub(new_url, content)
    if updated != content:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(updated)
    return new_url
