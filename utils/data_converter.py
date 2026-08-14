import numpy as np

from core.vehicle_model_settings import load_vehicle_model_settings
from core.vehicle_presets import resolve_export_vehicle_type
from core.marker_presets import ensure_marker_preset
from utils.vehicle_appearance import resolve_vehicle_paint_colors

ROAD_MODEL_END_EXTENSION_RATIO = 0.30



def _normalize_user_hex_color(value):
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


def _physical_point(x, y, img_w, img_h, ppm):
    return {
        "x": (float(x) - img_w / 2.0) / ppm,
        "z": (float(y) - img_h / 2.0) / ppm,
    }


def _extend_physical_segment(start, end, end_extension_ratio):
    dx = end["x"] - start["x"]
    dz = end["z"] - start["z"]
    length = np.hypot(dx, dz)
    if length <= 1e-9:
        return start, end

    extend_x = dx * end_extension_ratio
    extend_z = dz * end_extension_ratio
    return (
        {"x": start["x"] - extend_x, "z": start["z"] - extend_z},
        {"x": end["x"] + extend_x, "z": end["z"] + extend_z},
    )


def _build_lane_areas(road_settings):
    ordered_roads = sorted(
        (
            {
                "boundaryIndex": index,
                "x": float(road["x"]),
                "lineType": road["type"],
            }
            for index, road in enumerate(road_settings)
            if "x" in road
        ),
        key=lambda item: item["x"],
    )
    lane_areas = []
    for index in range(len(ordered_roads) - 1):
        left = ordered_roads[index]
        right = ordered_roads[index + 1]
        lane_areas.append(
            {
                "laneIndex": index,
                "laneId": "应急车道" if index == 0 else f"快车道{index}",
                "laneType": "应急车道" if index == 0 else "快车道",
                "leftBoundaryIndex": left["boundaryIndex"],
                "rightBoundaryIndex": right["boundaryIndex"],
                "minX": left["x"],
                "maxX": right["x"],
                "centerX": (left["x"] + right["x"]) / 2.0,
                "width": right["x"] - left["x"],
            }
        )
    return lane_areas


def _resolve_lane_info(px, lane_areas):
    for lane in lane_areas:
        if lane["minX"] <= px <= lane["maxX"]:
            return {
                "laneId": lane["laneId"],
                "laneType": lane["laneType"],
                "laneIndex": lane["laneIndex"],
            }
    return {
        "laneId": "未知区域",
        "laneType": "未知区域",
        "laneIndex": -1,
    }


def convert_to_3d_data(
    vehicles,
    lanes,
    img_w,
    img_h,
    img_bgr=None,
    markers=None,
    lane_width=None,
    emergency_lane_width=None,
):
    """
    将图像坐标转换为 3D 物理坐标。
    车道宽基准默认来自车辆建模设置：第一、第二根实线之间为应急车道宽，其余相邻线为车道宽。
    可通过 lane_width / emergency_lane_width 传入本图临时覆盖值。
    """
    model_settings = load_vehicle_model_settings()
    if lane_width is None:
        lane_width = float(model_settings["laneWidth"])
    else:
        lane_width = float(lane_width)
    if emergency_lane_width is None:
        emergency_lane_width = float(model_settings["emergencyLaneWidth"])
    else:
        emergency_lane_width = float(emergency_lane_width)
    ppm = 100.0 # 默认值
    lane_offsets = []

    if lanes:
        first_lane = lanes[0]
        dx = first_lane['x2'] - first_lane['x1']
        dy = first_lane['y2'] - first_lane['y1']
        length = np.hypot(dx, dy)
        if length > 1e-9:
            ux, uy = dx / length, dy / length
            nx, ny = -uy, ux
            image_cx = img_w / 2.0
            image_cy = img_h / 2.0

            if len(lanes) >= 2:
                second_lane = lanes[1]
                sx = (second_lane['x1'] + second_lane['x2']) / 2.0
                sy = (second_lane['y1'] + second_lane['y2']) / 2.0
                fx = (first_lane['x1'] + first_lane['x2']) / 2.0
                fy = (first_lane['y1'] + first_lane['y2']) / 2.0
                if (sx - fx) * nx + (sy - fy) * ny < 0:
                    nx, ny = -nx, -ny

            for lane in lanes:
                cx = (lane['x1'] + lane['x2']) / 2.0
                cy = (lane['y1'] + lane['y2']) / 2.0
                lane_offsets.append((cx - image_cx) * nx + (cy - image_cy) * ny)
        else:
            lane_offsets = [(lane['x1'] + lane['x2']) / 2.0 - img_w / 2.0 for lane in lanes]
    
    if len(lane_offsets) >= 2:
        ppm_candidates = []
        for i in range(len(lane_offsets) - 1):
            pixel_gap = abs(lane_offsets[i + 1] - lane_offsets[i])
            physical_gap = emergency_lane_width if i == 0 else lane_width
            if pixel_gap > 0 and physical_gap > 0:
                ppm_candidates.append(pixel_gap / physical_gap)
        if ppm_candidates:
            ppm = float(np.median(ppm_candidates))
            
    road_settings = []
    # 第一、第二根和最后一根车道线为实线，其余为虚线
    lane_count = len(lanes)
    for i, lane in enumerate(lanes):
        if i < len(lane_offsets):
            physical_x = lane_offsets[i] / ppm
        else:
            mid_x = (lane['x1'] + lane['x2']) / 2.0
            physical_x = (mid_x - img_w / 2.0) / ppm

        is_solid = i == 0 or i == 1 or i == lane_count - 1
        line_type = 'solid' if is_solid else 'dash'
        original_start = _physical_point(lane["x1"], lane["y1"], img_w, img_h, ppm)
        original_end = _physical_point(lane["x2"], lane["y2"], img_w, img_h, ppm)
        start, end = _extend_physical_segment(
            original_start,
            original_end,
            ROAD_MODEL_END_EXTENSION_RATIO,
        )
        dir_dx = end["x"] - start["x"]
        dir_dz = end["z"] - start["z"]
        dir_len = np.hypot(dir_dx, dir_dz)
        if dir_len > 1e-9:
            direction = {"x": dir_dx / dir_len, "z": dir_dz / dir_len}
        else:
            direction = {"x": 0.0, "z": 1.0}
        road_settings.append({
            "type": line_type,
            "x": physical_x,
            "start": start,
            "end": end,
            "originalStart": original_start,
            "originalEnd": original_end,
            "center": {
                "x": (start["x"] + end["x"]) / 2.0,
                "z": (start["z"] + end["z"]) / 2.0,
            },
            "direction": direction,
        })
        
    lane_areas = _build_lane_areas(road_settings)
    vehicle_settings = []
    vehicle_specs = model_settings["vehicleSpecs"]
    marker_specs = model_settings.get("markerSpecs", {})

    for veh in vehicles:
        v_type = resolve_export_vehicle_type(veh)
        px = (veh['x_center'] - img_w / 2.0) / ppm
        pz = (veh['y_center'] - img_h / 2.0) / ppm
        rot_y = -(veh['angle'] + np.radians(float(veh.get('direction_offset', 0.0))))
        # User-picked colors win; otherwise sample defaults from the aerial image.
        body_hex, cargo_hex = resolve_vehicle_paint_colors(img_bgr, veh, ppm)
        spec = vehicle_specs.get(v_type, {})
        lane_info = _resolve_lane_info(px, lane_areas)
        custom_size = veh.get("custom_size")
        if not (
            isinstance(custom_size, dict)
            and all(float(custom_size.get(k, 0) or 0) > 0 for k in ("width", "length", "height"))
        ):
            custom_size = None
        size = {
            "width": float((custom_size or spec).get("width", 0.0)),
            "length": float((custom_size or spec).get("length", 0.0)),
            "height": float((custom_size or spec).get("height", 0.0)),
        }
        if custom_size is not None:
            try:
                wr = float(custom_size.get("wheelRadius", 0) or 0)
            except (TypeError, ValueError):
                wr = 0.0
            if wr > 0:
                size["wheelRadius"] = wr
            wheels_raw = custom_size.get("wheels")
            if isinstance(wheels_raw, list) and wheels_raw:
                wheels = []
                for item in wheels_raw:
                    try:
                        wheels.append(float(item))
                    except (TypeError, ValueError):
                        continue
                if wheels:
                    size["wheels"] = wheels
        entry = {
            "vehicleId": str(veh.get("vehicle_id", "") or ""),
            "type": v_type,
            "presetType": v_type,
            "position": {"x": px, "y": 0, "z": pz},
            "rotation": {"x": 0, "y": rot_y, "z": 0},
            "size": size,
            "sourceBox": {
                "xCenter": float(veh["x_center"]),
                "yCenter": float(veh["y_center"]),
                "width": float(veh["width"]),
                "height": float(veh["height"]),
                "angle": float(veh["angle"]),
            },
            "laneId": lane_info["laneId"],
            "laneType": lane_info["laneType"],
            "laneIndex": lane_info["laneIndex"],
        }
        if body_hex is not None:
            entry["color"] = body_hex
        if cargo_hex is not None:
            entry["cargoColor"] = cargo_hex

        motion_path_raw = veh.get("motion_path")
        motion_points = []
        if isinstance(motion_path_raw, list):
            for pt in motion_path_raw:
                if not isinstance(pt, dict):
                    continue
                try:
                    sx = float(pt.get("x"))
                    sy = float(pt.get("y"))
                except (TypeError, ValueError):
                    continue
                if not (np.isfinite(sx) and np.isfinite(sy)):
                    continue
                world = _physical_point(sx, sy, img_w, img_h, ppm)
                drive_raw = str(pt.get("drive", "G") or "G").strip().upper()
                drive = "F" if drive_raw == "F" else "G"
                motion_points.append(
                    {"x": world["x"], "z": world["z"], "drive": drive}
                )
                if len(motion_points) >= 10:
                    break
        if motion_points:
            entry["motionPath"] = motion_points
            try:
                speed = float(veh.get("motion_speed_kmh", 80.0))
            except (TypeError, ValueError):
                speed = 80.0
            if not np.isfinite(speed) or speed <= 0:
                speed = 80.0
            entry["motionSpeedKmh"] = speed

        vehicle_settings.append(entry)

    marker_settings = []
    for marker in markers or []:
        ensure_marker_preset(marker)
        marker_type = marker["marker_type"]
        px = (marker["x_center"] - img_w / 2.0) / ppm
        pz = (marker["y_center"] - img_h / 2.0) / ppm
        spec = marker_specs.get(marker_type, {})
        marker_settings.append(
            {
                "markerId": str(marker.get("marker_id", "") or ""),
                "type": marker_type,
                "presetType": marker_type,
                "position": {"x": px, "y": 0, "z": pz},
                "rotation": {"x": 0, "y": 0, "z": 0},
                "size": {
                    "width": float(spec.get("width", 0.0)),
                    "length": float(spec.get("length", 0.0)),
                    "height": float(spec.get("height", 0.0)),
                },
                "sourcePoint": {
                    "xCenter": float(marker["x_center"]),
                    "yCenter": float(marker["y_center"]),
                },
            }
        )
        
    return {
        "roads": road_settings,
        "vehicles": vehicle_settings,
        "markers": marker_settings,
        "laneAreas": lane_areas,
        "scale": {
            "pixelsPerMeter": ppm,
            "laneWidth": lane_width,
            "emergencyLaneWidth": emergency_lane_width,
            "imageWidth": img_w,
            "imageHeight": img_h,
        },
    }
