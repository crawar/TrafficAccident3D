# Standard vehicle types for 3D scene (must match createVehicle switch in accident_scene.html)

STANDARD_VEHICLE_TYPES = (
    "小客车",
    "商务车",
    "牵引车及挂车",
    "大型厢式货车",
    "大型罐式货车",
    "大型栏板货车",
    "轻型栏板货车",
    "大巴车",
)

STANDARD_VEHICLE_TYPE_SET = frozenset(STANDARD_VEHICLE_TYPES)

CLASS_ID_TO_PRESET = {
    2: "小客车",
    3: "商务车",
    5: "大巴车",
    7: "大型栏板货车",
    9: "大型栏板货车",
    10: "小客车",
}


def infer_vehicle_preset(veh):
    """Infer preset from YOLO class_id / class_name when user has not set preset_type."""
    cls_id = veh.get("class_id", -1)
    cls_name = str(veh.get("class_name", "")).lower()
    v_type = "小客车"
    if cls_id in CLASS_ID_TO_PRESET:
        v_type = CLASS_ID_TO_PRESET[cls_id]
    elif "large" in cls_name or "truck" in cls_name or "bus" in cls_name:
        v_type = "大型栏板货车"
    elif "small" in cls_name or "car" in cls_name:
        v_type = "小客车"
    return v_type


def resolve_export_vehicle_type(veh):
    """Type string written to accidentSettings.vehicles[].type for Three.js."""
    pt = veh.get("preset_type")
    if pt and pt in STANDARD_VEHICLE_TYPE_SET:
        return pt
    return infer_vehicle_preset(veh)


def ensure_vehicle_preset(veh):
    """Ensure veh dict has a valid preset_type (mutates dict)."""
    pt = veh.get("preset_type")
    if pt not in STANDARD_VEHICLE_TYPE_SET:
        veh["preset_type"] = infer_vehicle_preset(veh)
    return veh["preset_type"]
