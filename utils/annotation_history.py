import hashlib
import json
import os
from datetime import datetime

from utils.app_paths import app_path


HISTORY_JSON_DIR = app_path("history", "json")
MAX_HISTORY_JSON_FILES = 200


def _normalized_image_path(image_path):
    return os.path.normcase(os.path.abspath(image_path))


def _annotation_path(image_path):
    key = _normalized_image_path(image_path)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(HISTORY_JSON_DIR, f"{digest}.json")


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    return value


def annotation_fingerprint(
    vehicles, lanes, markers=None, accident_brief="", lane_width_settings=None
):
    payload = {
        "vehicles": _json_safe(vehicles),
        "lanes": _json_safe(lanes),
        "markers": _json_safe(markers or []),
        "accident_brief": str(accident_brief or ""),
        "lane_width_settings": _json_safe(lane_width_settings or {}),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prune_history_json_files(keep_count=MAX_HISTORY_JSON_FILES):
    if keep_count <= 0 or not os.path.isdir(HISTORY_JSON_DIR):
        return

    entries = []
    try:
        with os.scandir(HISTORY_JSON_DIR) as scan:
            for entry in scan:
                if not entry.is_file() or not entry.name.lower().endswith(".json"):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                entries.append((stat.st_mtime, entry.name, entry.path))
    except OSError:
        return

    if len(entries) <= keep_count:
        return

    entries.sort(reverse=True)
    for _, _, path in entries[keep_count:]:
        try:
            os.remove(path)
        except OSError:
            continue


def _sanitize_lane_width_settings(raw):
    if not isinstance(raw, dict):
        return None
    try:
        lane_width = float(raw.get("laneWidth"))
        emergency_width = float(raw.get("emergencyLaneWidth"))
    except (TypeError, ValueError):
        return None
    if lane_width <= 0 or emergency_width <= 0:
        return None
    return {
        "laneWidth": lane_width,
        "emergencyLaneWidth": emergency_width,
    }


def load_annotation(image_path):
    annotation_path = _annotation_path(image_path)
    if not os.path.exists(annotation_path):
        return None

    try:
        with open(annotation_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    image_key = _normalized_image_path(image_path)
    stored_key = payload.get("image_path_key")
    stored_path = payload.get("image_path")
    if stored_key != image_key and _normalized_image_path(stored_path or "") != image_key:
        return None
    vehicles = payload.get("vehicles", [])
    lanes = payload.get("lanes", [])
    markers = payload.get("markers", [])
    if not isinstance(vehicles, list) or not isinstance(lanes, list):
        return None
    if not isinstance(markers, list):
        return None

    return {
        "vehicles": vehicles,
        "lanes": lanes,
        "markers": markers,
        "annotation_path": os.path.abspath(annotation_path),
        "data_fingerprint": str(payload.get("data_fingerprint", "") or ""),
        "ai_analysis": payload.get("ai_analysis"),
        "liability_context": payload.get("liability_context"),
        "generated_html_path": payload.get("generated_html_path", ""),
        "accident_brief": str(payload.get("accident_brief", "") or ""),
        "lane_width_settings": _sanitize_lane_width_settings(
            payload.get("lane_width_settings")
        ),
    }


def save_annotation(
    image_path,
    vehicles,
    lanes,
    markers=None,
    ai_analysis=None,
    liability_context=None,
    generated_html_path="",
    accident_brief="",
    lane_width_settings=None,
):
    os.makedirs(HISTORY_JSON_DIR, exist_ok=True)
    annotation_path = _annotation_path(image_path)
    safe_vehicles = _json_safe(vehicles)
    safe_lanes = _json_safe(lanes)
    safe_markers = _json_safe(markers or [])
    safe_accident_brief = str(accident_brief or "")
    safe_lane_widths = _sanitize_lane_width_settings(lane_width_settings)
    payload = {
        "version": 1,
        "image_path": os.path.abspath(image_path),
        "image_path_key": _normalized_image_path(image_path),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "vehicles": safe_vehicles,
        "lanes": safe_lanes,
        "markers": safe_markers,
        "data_fingerprint": annotation_fingerprint(
            safe_vehicles,
            safe_lanes,
            safe_markers,
            safe_accident_brief,
            safe_lane_widths,
        ),
        "ai_analysis": _json_safe(ai_analysis) if ai_analysis else None,
        "liability_context": _json_safe(liability_context) if liability_context else None,
        "generated_html_path": os.path.abspath(generated_html_path) if generated_html_path else "",
        "accident_brief": safe_accident_brief,
        "lane_width_settings": safe_lane_widths,
    }

    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _prune_history_json_files()
    return os.path.abspath(annotation_path)
