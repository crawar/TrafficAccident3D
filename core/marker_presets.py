# Standard marker types for editor, preview, and 3D scene export.

STANDARD_MARKER_TYPES = (
    "安全椎桶",
    "成年人",
    "导向牌",
    "公里牌",
    "散落物",
    "碰撞点",
)

STANDARD_MARKER_TYPE_SET = frozenset(STANDARD_MARKER_TYPES)
DEFAULT_MARKER_TYPE = STANDARD_MARKER_TYPES[0]


def ensure_marker_preset(marker):
    marker_type = marker.get("marker_type")
    if marker_type not in STANDARD_MARKER_TYPE_SET:
        marker["marker_type"] = DEFAULT_MARKER_TYPE
    return marker["marker_type"]


def next_marker_id(markers):
    used = set()
    for marker in markers:
        raw_id = str(marker.get("marker_id", "") or "")
        if raw_id.startswith("M"):
            raw_id = raw_id[1:]
        try:
            used.add(int(raw_id))
        except ValueError:
            continue
    next_id = 1
    while next_id in used:
        next_id += 1
    return f"M{next_id:02d}"
