import json
import os

from utils.app_paths import app_path

SETTINGS_PATH = app_path("config", "recognition_settings.json")


def list_yolo_model_files():
    downloads_dir = app_path("downloads")
    models = []
    if os.path.isdir(downloads_dir):
        for name in sorted(os.listdir(downloads_dir)):
            if name.lower().endswith(".pt"):
                models.append(name)
    return models


def default_recognition_settings():
    models = list_yolo_model_files()
    preferred = ""
    for name in models:
        if "obb" not in name.lower():
            preferred = name
            break
    if not preferred and models:
        preferred = models[0]
    return {"modelFile": preferred}


def sanitize_recognition_settings(raw_settings):
    settings = default_recognition_settings()
    models = list_yolo_model_files()
    if not isinstance(raw_settings, dict):
        return settings
    model_file = str(raw_settings.get("modelFile", "") or "").strip()
    if model_file and model_file in models:
        settings["modelFile"] = model_file
    elif settings["modelFile"] not in models:
        settings["modelFile"] = models[0] if models else ""
    return settings


def load_recognition_settings():
    if not os.path.isfile(SETTINGS_PATH):
        return default_recognition_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_recognition_settings()
    return sanitize_recognition_settings(raw)


def save_recognition_settings(raw_settings):
    settings = sanitize_recognition_settings(raw_settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings


def selected_model_path():
    settings = load_recognition_settings()
    model_file = settings.get("modelFile", "")
    if not model_file:
        return ""
    path = app_path("downloads", model_file)
    if os.path.isfile(path):
        return path
    return ""


def models_available():
    return bool(list_yolo_model_files())
