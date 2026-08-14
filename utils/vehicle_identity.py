def _normalized_vehicle_id(value):
    text = str(value or "").strip()
    return text if text else ""


def ensure_vehicle_ids(vehicles):
    used = set()
    next_index = 1
    for veh in vehicles:
        vehicle_id = _normalized_vehicle_id(veh.get("vehicle_id"))
        if vehicle_id and vehicle_id not in used:
            veh["vehicle_id"] = vehicle_id
            used.add(vehicle_id)
            continue
        while f"车辆{next_index}" in used:
            next_index += 1
        vehicle_id = f"车辆{next_index}"
        next_index += 1
        veh["vehicle_id"] = vehicle_id
        used.add(vehicle_id)
    return vehicles


def next_vehicle_id(vehicles):
    used = {
        _normalized_vehicle_id(veh.get("vehicle_id"))
        for veh in vehicles
        if _normalized_vehicle_id(veh.get("vehicle_id"))
    }
    next_index = 1
    while f"车辆{next_index}" in used:
        next_index += 1
    return f"车辆{next_index}"
