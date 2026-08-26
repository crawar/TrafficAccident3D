import copy
import json
import os

from utils.app_paths import app_path


DEFAULT_LANE_WIDTH = 3.75
DEFAULT_EMERGENCY_LANE_WIDTH = 3.0
DEFAULT_OUTLINE_WIDTH = 2.5
SETTINGS_PATH = app_path("config", "vehicle_model_settings.json")
DEFAULTS_PATH = app_path("config", "vehicle_model_defaults.json")

# Per-vehicle editable keys (besides kind). Legacy cab/cargo/hood/wheelY fields are dropped on sanitize.
VEHICLE_SPEC_KEYS = ("width", "length", "height", "wheelRadius", "wheels")

DEFAULT_VEHICLE_SPECS = {
    "小客车": {
        "kind": "passenger",
        "width": 1.8,
        "length": 4.3,
        "height": 1.6,
        "wheelRadius": 0.3,
        "wheels": [1.25, -1.25],
    },
    "商务车": {
        "kind": "passenger",
        "width": 1.6,
        "length": 3.8,
        "height": 1.9,
        "wheelRadius": 0.3,
        "wheels": [1.3, -1.1],
    },
    "牵引车及挂车": {
        "kind": "tractorTrailer",
        "width": 2.6,
        "length": 18.0,
        "height": 3.3,
        "wheelRadius": 0.42,
        "wheels": [6.5, 3.75, -2.8, -4.8],
    },
    "大型厢式货车": {
        "kind": "boxTruck",
        "width": 2.6,
        "length": 9.0,
        "height": 3.5,
        "wheelRadius": 0.42,
        "wheels": [3.2, -2.3],
    },
    "大型罐式货车": {
        "kind": "tankTruck",
        "width": 2.6,
        "length": 9.0,
        "height": 3.5,
        "wheelRadius": 0.42,
        "wheels": [2.8, -2.1, -0.4],
    },
    "大型栏板货车": {
        "kind": "flatbedTruck",
        "width": 2.6,
        "length": 9.0,
        "height": 3.5,
        "wheelRadius": 0.42,
        "wheels": [2.9, -2.6],
    },
    "轻型栏板货车": {
        "kind": "flatbedTruck",
        "width": 2.1,
        "length": 6.0,
        "height": 2.2,
        "wheelRadius": 0.36,
        "wheels": [1.9, -2.0],
    },
    "大巴车": {
        "kind": "bus",
        "width": 2.6,
        "length": 12.0,
        "height": 4.0,
        "wheelRadius": 0.44,
        "wheels": [3.0, -3.0],
    },
}

DEFAULT_MARKER_SPECS = {
    "安全椎桶": {
        "kind": "trafficCone",
        "width": 0.4,
        "length": 0.4,
        "height": 0.8,
    },
    "成年人": {
        "kind": "adult",
        "width": 0.35,
        "length": 0.45,
        "height": 1.75,
    },
    "导向牌": {
        "kind": "guideSign",
        "width": 0.8,
        "length": 0.2,
        "height": 2.2,
    },
    "公里牌": {
        "kind": "kilometerSign",
        "width": 0.8,
        "length": 0.2,
        "height": 2.2,
    },
    "散落物": {
        "kind": "scatteredDebris",
        "radius": 1.5,
        "emissionInterval": 0.5,
    },
    "碰撞点": {
        "kind": "impactSphere",
        "radius": 1.5,
        "height": 1.5,
        "emissionInterval": 1.0,
    },
}


def factory_vehicle_model_settings():
    """Built-in factory baseline (code defaults)."""
    return {
        "laneWidth": DEFAULT_LANE_WIDTH,
        "emergencyLaneWidth": DEFAULT_EMERGENCY_LANE_WIDTH,
        "outlineWidth": DEFAULT_OUTLINE_WIDTH,
        "vehicleSpecs": copy.deepcopy(DEFAULT_VEHICLE_SPECS),
        "markerSpecs": copy.deepcopy(DEFAULT_MARKER_SPECS),
    }


def default_vehicle_model_settings():
    """
    Active restore baseline: user-saved defaults file if present, else factory.
    """
    if os.path.isfile(DEFAULTS_PATH):
        try:
            with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
                return sanitize_vehicle_model_settings(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return factory_vehicle_model_settings()


def _as_positive_float(value, fallback):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if result <= 0:
        return fallback
    return result


def _sanitize_wheels(value, fallback):
    if not isinstance(value, list):
        return list(fallback)
    wheels = []
    for item in value:
        try:
            wheels.append(float(item))
        except (TypeError, ValueError):
            continue
    return wheels or list(fallback)


def sanitize_vehicle_model_settings(raw_settings):
    settings = factory_vehicle_model_settings()
    if not isinstance(raw_settings, dict):
        return settings

    settings["laneWidth"] = _as_positive_float(
        raw_settings.get("laneWidth"), DEFAULT_LANE_WIDTH
    )
    settings["emergencyLaneWidth"] = _as_positive_float(
        raw_settings.get("emergencyLaneWidth"), DEFAULT_EMERGENCY_LANE_WIDTH
    )
    settings["outlineWidth"] = _as_positive_float(
        raw_settings.get("outlineWidth"), DEFAULT_OUTLINE_WIDTH
    )
    raw_specs = raw_settings.get("vehicleSpecs", {})
    if not isinstance(raw_specs, dict):
        return settings

    for vehicle_type, default_spec in DEFAULT_VEHICLE_SPECS.items():
        raw_spec = raw_specs.get(vehicle_type, {})
        if not isinstance(raw_spec, dict):
            continue
        spec = settings["vehicleSpecs"][vehicle_type]
        for key, fallback in default_spec.items():
            if key == "kind":
                spec[key] = fallback
            elif key == "wheels":
                spec[key] = _sanitize_wheels(raw_spec.get(key), fallback)
            elif isinstance(fallback, (int, float)):
                spec[key] = _as_positive_float(raw_spec.get(key), fallback)

    raw_marker_specs = raw_settings.get("markerSpecs", {})
    if isinstance(raw_marker_specs, dict):
        for marker_type, default_spec in DEFAULT_MARKER_SPECS.items():
            raw_spec = raw_marker_specs.get(marker_type, {})
            if not isinstance(raw_spec, dict):
                continue
            spec = settings["markerSpecs"][marker_type]
            for key, fallback in default_spec.items():
                if key == "kind":
                    spec[key] = fallback
                elif isinstance(fallback, (int, float)):
                    spec[key] = _as_positive_float(raw_spec.get(key), fallback)
    return settings


def load_vehicle_model_settings():
    if not os.path.isfile(SETTINGS_PATH):
        return default_vehicle_model_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return sanitize_vehicle_model_settings(json.load(f))
    except (OSError, json.JSONDecodeError):
        return default_vehicle_model_settings()


def save_vehicle_model_settings(settings):
    safe_settings = sanitize_vehicle_model_settings(settings)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(safe_settings, f, ensure_ascii=False, indent=2)
    return safe_settings


def save_as_default_vehicle_model_settings(settings):
    """Persist current settings as the restore baseline and as the active settings."""
    safe_settings = sanitize_vehicle_model_settings(settings)
    os.makedirs(os.path.dirname(DEFAULTS_PATH), exist_ok=True)
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(safe_settings, f, ensure_ascii=False, indent=2)
    return save_vehicle_model_settings(safe_settings)


def reset_vehicle_model_settings():
    settings = default_vehicle_model_settings()
    if os.path.exists(SETTINGS_PATH):
        os.remove(SETTINGS_PATH)
    return settings
