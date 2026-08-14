"""Default vehicle paint sampling from the aerial image.

When the user has not manually eyedropped a color, sample at fixed
geometry relative to the recognition OBB and heading:

- body / unified: 0.5 m inward from the front edge on the centerline
- cargo (split types only): 0.5 m inward from the rear edge on the centerline
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import numpy as np

from core.vehicle_presets import resolve_export_vehicle_type

# Matches gui.image_viewer.SPLIT_COLOR_VEHICLE_TYPES (cab / cargo dual paint).
SPLIT_COLOR_VEHICLE_TYPES = frozenset(
    {"大型罐式货车", "大型厢式货车", "牵引车及挂车"}
)

DEFAULT_INSET_METERS = 0.5
DEFAULT_PPM = 100.0

# Per-region paint source. Stored on the vehicle dict as body_color_mode /
# cargo_color_mode so it travels with the per-image annotation cache.
COLOR_MODE_AUTO = "auto"
COLOR_MODE_GRAB = "grab"
COLOR_MODE_NATIVE = "native"
COLOR_MODE_DEFAULT = COLOR_MODE_AUTO
VALID_COLOR_MODES = frozenset(
    {COLOR_MODE_AUTO, COLOR_MODE_GRAB, COLOR_MODE_NATIVE}
)
COLOR_KEY_TO_MODE_KEY = {
    "body_color": "body_color_mode",
    "cargo_color": "cargo_color_mode",
}
COLOR_KEY_TO_REGION = {
    "body_color": "body",
    "cargo_color": "cargo",
}


def color_mode_key(color_key: str) -> str:
    return COLOR_KEY_TO_MODE_KEY.get(color_key, f"{color_key}_mode")


def get_vehicle_color_mode(veh: Dict[str, Any], color_key: str) -> str:
    """
    Resolve paint mode for a color region.

    Missing mode: legacy cache with a stored hex → grab; otherwise auto.
    """
    mode = veh.get(color_mode_key(color_key))
    if isinstance(mode, str) and mode.strip().lower() in VALID_COLOR_MODES:
        return mode.strip().lower()
    if _normalize_hex_color(veh.get(color_key)):
        return COLOR_MODE_GRAB
    return COLOR_MODE_DEFAULT


def set_vehicle_color_mode(veh: Dict[str, Any], color_key: str, mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in VALID_COLOR_MODES:
        normalized = COLOR_MODE_DEFAULT
    veh[color_mode_key(color_key)] = normalized
    return normalized


def ensure_vehicle_color_modes(veh: Dict[str, Any]) -> Dict[str, Any]:
    """Persist explicit mode fields (default auto) for caching / UI."""
    set_vehicle_color_mode(veh, "body_color", get_vehicle_color_mode(veh, "body_color"))
    if is_split_color_vehicle(veh):
        set_vehicle_color_mode(
            veh, "cargo_color", get_vehicle_color_mode(veh, "cargo_color")
        )
    return veh


def is_split_color_vehicle(veh_or_type: Any) -> bool:
    if isinstance(veh_or_type, dict):
        v_type = resolve_export_vehicle_type(veh_or_type)
    else:
        v_type = str(veh_or_type or "")
    return v_type in SPLIT_COLOR_VEHICLE_TYPES


def vehicle_front_unit(veh: Dict[str, Any]) -> Tuple[float, float]:
    """Unit vector from rear toward front (matches the on-image heading arrow)."""
    theta = float(veh["angle"]) + math.radians(float(veh.get("direction_offset", 0.0)))
    return (-math.sin(theta), math.cos(theta))


def _obb_half_extent_along(veh: Dict[str, Any], dx: float, dy: float) -> float:
    """Half-length of the recognition OBB along a unit direction."""
    w = max(float(veh["width"]), 1.0)
    h = max(float(veh["height"]), 1.0)
    a = float(veh["angle"])
    ew_x, ew_y = math.cos(a), math.sin(a)
    eh_x, eh_y = -math.sin(a), math.cos(a)
    return abs(dx * ew_x + dy * ew_y) * (w * 0.5) + abs(dx * eh_x + dy * eh_y) * (h * 0.5)


def default_color_sample_point(
    veh: Dict[str, Any],
    region: str,
    ppm: float,
) -> Optional[Tuple[float, float]]:
    """
    Image / scene coordinates for the default sample point.

    region: \"body\" (front / unified) or \"cargo\" (rear).
    """
    try:
        cx = float(veh["x_center"])
        cy = float(veh["y_center"])
    except (KeyError, TypeError, ValueError):
        return None

    fx, fy = vehicle_front_unit(veh)
    flen = math.hypot(fx, fy)
    if flen < 1e-9:
        return None
    fx /= flen
    fy /= flen

    half_len = _obb_half_extent_along(veh, fx, fy)
    if half_len < 1.0:
        return (cx, cy)

    inset_px = max(float(ppm), 1e-6) * DEFAULT_INSET_METERS
    # Keep the sample inside the box even for short vehicles.
    inset_px = min(inset_px, max(half_len - 1.0, 0.0))

    if region == "cargo":
        # Rear edge, then 0.5 m toward the front, width centerline.
        return (
            cx - fx * half_len + fx * inset_px,
            cy - fy * half_len + fy * inset_px,
        )

    # Front edge, then 0.5 m toward the rear, width centerline.
    return (
        cx + fx * half_len - fx * inset_px,
        cy + fy * half_len - fy * inset_px,
    )


def sample_hex_at_image_xy(
    img_bgr: np.ndarray,
    x: float,
    y: float,
    radius: int = 2,
) -> Optional[str]:
    """Sample a small neighborhood and return #RRGGBB (uppercase)."""
    if img_bgr is None or getattr(img_bgr, "size", 0) == 0:
        return None
    ih, iw = img_bgr.shape[:2]
    ix = int(round(x))
    iy = int(round(y))
    if ix < 0 or iy < 0 or ix >= iw or iy >= ih:
        return None

    r = max(0, int(radius))
    x0 = max(0, ix - r)
    x1 = min(iw, ix + r + 1)
    y0 = max(0, iy - r)
    y1 = min(ih, iy + r + 1)
    patch = img_bgr[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    bgr = np.median(patch.reshape(-1, 3), axis=0)
    b, g, r_ch = [int(np.clip(v, 0, 255)) for v in bgr]
    return f"#{r_ch:02X}{g:02X}{b:02X}"


def default_vehicle_paint_hex(
    img_bgr: Optional[np.ndarray],
    veh: Dict[str, Any],
    ppm: float = DEFAULT_PPM,
    region: str = "body",
) -> Optional[str]:
    if img_bgr is None:
        return None
    point = default_color_sample_point(veh, region, ppm)
    if point is None:
        return None
    return sample_hex_at_image_xy(img_bgr, point[0], point[1])


def _normalize_hex_color(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = "#" + text
    if len(text) != 7:
        return None
    try:
        int(text[1:], 16)
    except ValueError:
        return None
    return text.upper()


def resolve_region_paint_hex(
    img_bgr: Optional[np.ndarray],
    veh: Dict[str, Any],
    ppm: float,
    color_key: str,
) -> Optional[str]:
    """Resolve one paint region according to its mode. None = keep GLB original."""
    mode = get_vehicle_color_mode(veh, color_key)
    if mode == COLOR_MODE_NATIVE:
        return None
    if mode == COLOR_MODE_GRAB:
        return _normalize_hex_color(veh.get(color_key))
    region = COLOR_KEY_TO_REGION.get(color_key, "body")
    return default_vehicle_paint_hex(img_bgr, veh, ppm, region)


def resolve_vehicle_paint_colors(
    img_bgr: Optional[np.ndarray],
    veh: Dict[str, Any],
    ppm: float = DEFAULT_PPM,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve body/cargo colors from mode + image.

    Returns (body_hex, cargo_hex). cargo_hex is only set for split types.
    None means do not tint (GLB original materials).
    """
    body = resolve_region_paint_hex(img_bgr, veh, ppm, "body_color")
    if is_split_color_vehicle(veh):
        cargo = resolve_region_paint_hex(img_bgr, veh, ppm, "cargo_color")
    else:
        cargo = None
    return body, cargo
