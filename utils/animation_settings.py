import json
import os

from utils.app_paths import app_path

SETTINGS_PATH = app_path("config", "animation_settings.json")

DEFAULT_PLAYBACK_SPEED_FACTOR = 0.1
MIN_PLAYBACK_SPEED_FACTOR = 0.02
MAX_PLAYBACK_SPEED_FACTOR = 0.25


def default_animation_settings():
    return {"playbackSpeedFactor": DEFAULT_PLAYBACK_SPEED_FACTOR}


def sanitize_animation_settings(raw_settings):
    settings = default_animation_settings()
    if not isinstance(raw_settings, dict):
        return settings
    try:
        factor = float(raw_settings.get("playbackSpeedFactor", settings["playbackSpeedFactor"]))
    except (TypeError, ValueError):
        factor = settings["playbackSpeedFactor"]
    if factor < MIN_PLAYBACK_SPEED_FACTOR:
        factor = MIN_PLAYBACK_SPEED_FACTOR
    elif factor > MAX_PLAYBACK_SPEED_FACTOR:
        factor = MAX_PLAYBACK_SPEED_FACTOR
    settings["playbackSpeedFactor"] = factor
    return settings


def load_animation_settings():
    if not os.path.isfile(SETTINGS_PATH):
        return default_animation_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_animation_settings()
    return sanitize_animation_settings(raw)


def save_animation_settings(raw_settings):
    settings = sanitize_animation_settings(raw_settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings


def playback_speed_factor():
    return float(load_animation_settings().get("playbackSpeedFactor", DEFAULT_PLAYBACK_SPEED_FACTOR))
