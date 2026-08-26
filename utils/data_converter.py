import numpy as np

from core.vehicle_model_settings import load_vehicle_model_settings
from core.vehicle_presets import resolve_export_vehicle_type
from core.marker_presets import ensure_marker_preset
from utils.vehicle_appearance import resolve_vehicle_paint_colors

# Gray ground padding around the crop AABB in the road-aligned frame.
GROUND_PAD_ALONG_METERS = 10.0
GROUND_PAD_LATERAL_METERS = 5.0



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


def _default_road_basis():
    """Image +X → world +X, image +Y → world +Z (legacy axis-aligned mapping)."""
    return {"nx": 1.0, "ny": 0.0, "ux": 0.0, "uy": 1.0}


def _lane_road_basis(lanes):
    """Unit axes: lateral (nx, ny) and along-road (ux, uy) in image pixels."""
    if not lanes:
        return _default_road_basis()
    first_lane = lanes[0]
    dx = first_lane["x2"] - first_lane["x1"]
    dy = first_lane["y2"] - first_lane["y1"]
    length = np.hypot(dx, dy)
    if length <= 1e-9:
        return _default_road_basis()
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    if len(lanes) >= 2:
        second_lane = lanes[1]
        sx = (second_lane["x1"] + second_lane["x2"]) / 2.0
        sy = (second_lane["y1"] + second_lane["y2"]) / 2.0
        fx = (first_lane["x1"] + first_lane["x2"]) / 2.0
        fy = (first_lane["y1"] + first_lane["y2"]) / 2.0
        if (sx - fx) * nx + (sy - fy) * ny < 0:
            nx, ny = -nx, -ny
    return {"nx": nx, "ny": ny, "ux": ux, "uy": uy}


def _physical_point(x, y, origin_x, origin_y, ppm, basis=None):
    basis = basis or _default_road_basis()
    rel_x = float(x) - origin_x
    rel_y = float(y) - origin_y
    return {
        "x": (rel_x * basis["nx"] + rel_y * basis["ny"]) / ppm,
        "z": (rel_x * basis["ux"] + rel_y * basis["uy"]) / ppm,
    }


def _vehicle_yaw(angle, direction_offset, basis):
    theta = float(angle) + np.radians(float(direction_offset or 0.0))
    fx, fy = -np.sin(theta), np.cos(theta)
    front_x = fx * basis["nx"] + fy * basis["ny"]
    front_z = fx * basis["ux"] + fy * basis["uy"]
    return float(np.arctan2(front_x, front_z))


def _crop_world_aabb(crop, img_w, img_h, origin_x, origin_y, ppm, basis):
    if crop is not None:
        x = crop["x"]
        y = crop["y"]
        width = crop["width"]
        height = crop["height"]
        corners = ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
    else:
        corners = ((0.0, 0.0), (float(img_w), 0.0), (0.0, float(img_h)), (float(img_w), float(img_h)))
    xs = []
    zs = []
    for cx, cy in corners:
        point = _physical_point(cx, cy, origin_x, origin_y, ppm, basis)
        xs.append(point["x"])
        zs.append(point["z"])
    return min(xs), max(xs), min(zs), max(zs)


def _ground_rect_from_crop_aabb(min_x, max_x, min_z, max_z):
    ground_min_x = min_x - GROUND_PAD_LATERAL_METERS
    ground_max_x = max_x + GROUND_PAD_LATERAL_METERS
    ground_min_z = min_z - GROUND_PAD_ALONG_METERS
    ground_max_z = max_z + GROUND_PAD_ALONG_METERS
    return {
        "minX": ground_min_x,
        "maxX": ground_max_x,
        "minZ": ground_min_z,
        "maxZ": ground_max_z,
        "width": ground_max_x - ground_min_x,
        "depth": ground_max_z - ground_min_z,
        "centerX": (ground_min_x + ground_max_x) / 2.0,
        "centerZ": (ground_min_z + ground_max_z) / 2.0,
    }


def _sanitize_canvas_crop(raw, img_w, img_h):
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x"))
        y = float(raw.get("y"))
    except (TypeError, ValueError):
        return None
    if x != x or y != y:
        return None
    try:
        if raw.get("width") is not None and raw.get("height") is not None:
            crop_w = float(raw.get("width"))
            crop_h = float(raw.get("height"))
        elif raw.get("size") is not None:
            crop_w = crop_h = float(raw.get("size"))
        else:
            return None
    except (TypeError, ValueError):
        return None
    if not (crop_w > 0 and crop_h > 0):
        return None
    width = max(1.0, float(img_w))
    height = max(1.0, float(img_h))
    crop_w = min(crop_w, width)
    crop_h = min(crop_h, height)
    x = min(max(x, 0.0), max(0.0, width - crop_w))
    y = min(max(y, 0.0), max(0.0, height - crop_h))
    return {"x": x, "y": y, "width": crop_w, "height": crop_h}


def _origin_from_canvas_crop(img_w, img_h, canvas_crop=None):
    crop = _sanitize_canvas_crop(canvas_crop, img_w, img_h)
    if crop is None:
        return float(img_w) / 2.0, float(img_h) / 2.0, None
    return (
        crop["x"] + crop["width"] / 2.0,
        crop["y"] + crop["height"] / 2.0,
        crop,
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
    canvas_crop=None,
):
    """
    将图像坐标转换为道路对齐的 3D 物理坐标。
    世界 +Z 沿道路线，世界 +X 垂直于道路线，使灰底、道路线和锁定直角测量互相平行或垂直。
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
    lanes = list(lanes or [])
    origin_x, origin_y, crop = _origin_from_canvas_crop(img_w, img_h, canvas_crop)
    basis = _lane_road_basis(lanes)
    lane_offsets = []
    for lane in lanes:
        cx = (lane["x1"] + lane["x2"]) / 2.0
        cy = (lane["y1"] + lane["y2"]) / 2.0
        lane_offsets.append((cx - origin_x) * basis["nx"] + (cy - origin_y) * basis["ny"])

    if len(lane_offsets) >= 2:
        ppm_candidates = []
        for i in range(len(lane_offsets) - 1):
            pixel_gap = abs(lane_offsets[i + 1] - lane_offsets[i])
            physical_gap = emergency_lane_width if i == 0 else lane_width
            if pixel_gap > 0 and physical_gap > 0:
                ppm_candidates.append(pixel_gap / physical_gap)
        if ppm_candidates:
            ppm = float(np.median(ppm_candidates))

    crop_min_x, crop_max_x, crop_min_z, crop_max_z = _crop_world_aabb(
        crop, img_w, img_h, origin_x, origin_y, ppm, basis
    )
    ground = _ground_rect_from_crop_aabb(crop_min_x, crop_max_x, crop_min_z, crop_max_z)

    road_settings = []
    # 第一、第二根和最后一根车道线为实线，其余为虚线
    lane_count = len(lanes)
    for i, lane in enumerate(lanes):
        if i < len(lane_offsets):
            physical_x = lane_offsets[i] / ppm
        else:
            mid = _physical_point(
                (lane["x1"] + lane["x2"]) / 2.0,
                (lane["y1"] + lane["y2"]) / 2.0,
                origin_x,
                origin_y,
                ppm,
                basis,
            )
            physical_x = mid["x"]

        is_solid = i == 0 or i == 1 or i == lane_count - 1
        line_type = "solid" if is_solid else "dash"
        original_a = _physical_point(lane["x1"], lane["y1"], origin_x, origin_y, ppm, basis)
        original_b = _physical_point(lane["x2"], lane["y2"], origin_x, origin_y, ppm, basis)
        original_start = {"x": physical_x, "z": original_a["z"]}
        original_end = {"x": physical_x, "z": original_b["z"]}
        start = {"x": physical_x, "z": ground["minZ"]}
        end = {"x": physical_x, "z": ground["maxZ"]}
        road_settings.append({
            "type": line_type,
            "x": physical_x,
            "start": start,
            "end": end,
            "originalStart": original_start,
            "originalEnd": original_end,
            "center": {
                "x": physical_x,
                "z": ground["centerZ"],
            },
            "direction": {"x": 0.0, "z": 1.0},
        })
        
    lane_areas = _build_lane_areas(road_settings)
    vehicle_settings = []
    vehicle_specs = model_settings["vehicleSpecs"]
    marker_specs = model_settings.get("markerSpecs", {})

    for veh in vehicles:
        v_type = resolve_export_vehicle_type(veh)
        world = _physical_point(
            veh["x_center"], veh["y_center"], origin_x, origin_y, ppm, basis
        )
        px, pz = world["x"], world["z"]
        rot_y = _vehicle_yaw(veh["angle"], veh.get("direction_offset", 0.0), basis)
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
                world = _physical_point(sx, sy, origin_x, origin_y, ppm, basis)
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
        world = _physical_point(
            marker["x_center"], marker["y_center"], origin_x, origin_y, ppm, basis
        )
        px, pz = world["x"], world["z"]
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
        
    scale = {
        "pixelsPerMeter": ppm,
        "laneWidth": lane_width,
        "emergencyLaneWidth": emergency_lane_width,
        "imageWidth": img_w,
        "imageHeight": img_h,
        "groundWidthMeters": ground["width"],
        "groundDepthMeters": ground["depth"],
        "groundCenterX": ground["centerX"],
        "groundCenterZ": ground["centerZ"],
        "groundPadAlongMeters": GROUND_PAD_ALONG_METERS,
        "groundPadLateralMeters": GROUND_PAD_LATERAL_METERS,
        "canvasWidthMeters": crop_max_x - crop_min_x,
        "canvasHeightMeters": crop_max_z - crop_min_z,
        "canvasSizeMeters": max(crop_max_x - crop_min_x, crop_max_z - crop_min_z),
    }
    if crop is not None:
        scale["canvasCrop"] = {
            "x": crop["x"],
            "y": crop["y"],
            "width": crop["width"],
            "height": crop["height"],
        }
    return {
        "roads": road_settings,
        "vehicles": vehicle_settings,
        "markers": marker_settings,
        "laneAreas": lane_areas,
        "scale": scale,
    }
