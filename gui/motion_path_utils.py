"""Motion-path helpers for the result editor (pixel-space paths on vehicles)."""

from __future__ import annotations

import math

DEFAULT_MOTION_SPEED_KMH = 80.0
MAX_MOTION_PATH_POINTS = 10
MOTION_HOLD_SECONDS = 1.0
MOTION_WARN_DURATION_S = 30.0
# Path-point drive mode: G = forward (nose to next), F = reverse (rear to next).
MOTION_DRIVE_FORWARD = "G"
MOTION_DRIVE_REVERSE = "F"


def normalize_drive_mode(value):
    raw = str(value or MOTION_DRIVE_FORWARD).strip().upper()
    if raw == MOTION_DRIVE_REVERSE:
        return MOTION_DRIVE_REVERSE
    return MOTION_DRIVE_FORWARD


def normalize_motion_path(raw):
    points = []
    if not isinstance(raw, list):
        return points
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        points.append(
            {
                "x": x,
                "y": y,
                "drive": normalize_drive_mode(item.get("drive")),
            }
        )
        if len(points) >= MAX_MOTION_PATH_POINTS:
            break
    return points


def ensure_motion_fields(veh):
    if not isinstance(veh, dict):
        return
    path = normalize_motion_path(veh.get("motion_path"))
    if path:
        veh["motion_path"] = path
    else:
        veh.pop("motion_path", None)
    try:
        speed = float(veh.get("motion_speed_kmh", DEFAULT_MOTION_SPEED_KMH))
    except (TypeError, ValueError):
        speed = DEFAULT_MOTION_SPEED_KMH
    if not math.isfinite(speed) or speed <= 0:
        speed = DEFAULT_MOTION_SPEED_KMH
    veh["motion_speed_kmh"] = speed


def motion_speed_kmh(veh):
    ensure_motion_fields(veh)
    return float(veh.get("motion_speed_kmh", DEFAULT_MOTION_SPEED_KMH))


def path_pixel_length(points):
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        dx = float(points[i]["x"]) - float(points[i - 1]["x"])
        dy = float(points[i]["y"]) - float(points[i - 1]["y"])
        total += math.hypot(dx, dy)
    return total


def estimate_motion_duration_s(points, speed_kmh, ppm, playback_factor):
    """Estimate path travel duration (seconds). Pre-play hold is not included."""
    ppm = float(ppm) if ppm and ppm > 1e-6 else 100.0
    factor = float(playback_factor) if playback_factor and playback_factor > 1e-9 else 0.1
    speed = float(speed_kmh) if speed_kmh and speed_kmh > 1e-9 else DEFAULT_MOTION_SPEED_KMH
    length_m = path_pixel_length(points) / ppm
    speed_mps = (speed / 3.6) * factor
    if speed_mps <= 1e-9:
        return float("inf")
    return length_m / speed_mps


def path_color_for_duration(duration_s):
    if duration_s > MOTION_WARN_DURATION_S:
        return (220, 40, 40)  # red
    return (120, 180, 255)  # light blue
