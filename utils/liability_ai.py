import json
import math
import re
from urllib import request

import cv2

from utils.ai_experts import experts_for_runtime, load_ai_experts
from utils.ai_settings import ai_request_config, sanitize_ai_settings
from utils.data_converter import convert_to_3d_data


DEFAULT_DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
ALIGNMENT_MIN_ABS = 0.55
WRONG_WAY_MIN_ABS = 0.72
NON_OBSERVABLE_PATTERNS = [
    re.compile(r"[0-9０-９]{2,4}\s*年"),
    re.compile(r"[0-9０-９]{1,2}\s*月"),
    re.compile(r"[0-9０-９]{1,2}\s*[日号]"),
    re.compile(r"[0-9０-９]{1,2}\s*[时点:：]"),
    re.compile(r"[0-9０-９]{1,2}\s*分"),
    re.compile(r"(上午|中午|下午|凌晨|傍晚|晚上)"),
    re.compile(r"([东南西北]{1,2}[^，。；\n]{0,10}[往向朝][东南西北]{1,2})"),
    re.compile(r"([东南西北]{1,2}向[东南西北]{1,2})"),
]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _subtract(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _normalize(vec):
    length = math.hypot(vec[0], vec[1])
    if length <= 1e-9:
        raise ValueError("责任分析失败：车辆方向向量无效。")
    return (vec[0] / length, vec[1] / length)


def _safe_round(value, digits=4):
    return round(float(value), digits)


def _oriented_vehicle_corners(vehicle):
    center_x = float(vehicle["position"]["x"])
    center_z = float(vehicle["position"]["z"])
    width = max(float(vehicle["size"]["width"]), 0.01)
    length = max(float(vehicle["size"]["length"]), 0.01)
    yaw = float(vehicle["rotation"]["y"])

    side = (math.cos(yaw), -math.sin(yaw))
    front = (math.sin(yaw), math.cos(yaw))
    half_w = width / 2.0
    half_l = length / 2.0

    return [
        (
            center_x - side[0] * half_w + front[0] * half_l,
            center_z - side[1] * half_w + front[1] * half_l,
        ),
        (
            center_x + side[0] * half_w + front[0] * half_l,
            center_z + side[1] * half_w + front[1] * half_l,
        ),
        (
            center_x + side[0] * half_w - front[0] * half_l,
            center_z + side[1] * half_w - front[1] * half_l,
        ),
        (
            center_x - side[0] * half_w - front[0] * half_l,
            center_z - side[1] * half_w - front[1] * half_l,
        ),
    ]


def _projection_range(points, axis):
    values = [_dot(point, axis) for point in points]
    return min(values), max(values)


def _rectangles_overlap(points_a, points_b):
    axes = []
    for points in (points_a, points_b):
        for index in range(2):
            edge = _subtract(points[(index + 1) % 4], points[index])
            axes.append(_normalize((-edge[1], edge[0])))
    for axis in axes:
        a_min, a_max = _projection_range(points_a, axis)
        b_min, b_max = _projection_range(points_b, axis)
        if a_max < b_min or b_max < a_min:
            return False
    return True


def _vehicle_center(vehicle):
    return (
        float(vehicle["position"]["x"]),
        float(vehicle["position"]["z"]),
    )


def _vehicle_forward(vehicle):
    yaw = float(vehicle["rotation"]["y"])
    return _normalize((math.sin(yaw), math.cos(yaw)))


def _angle_between(vec_a, vec_b, ignore_sign=False):
    dot_value = max(-1.0, min(1.0, _dot(vec_a, vec_b)))
    if ignore_sign:
        dot_value = abs(dot_value)
    return math.degrees(math.acos(dot_value))


def _road_axis(roads):
    sum_x = 0.0
    sum_z = 0.0
    for road in roads:
        direction = road.get("direction") or {}
        dx = float(direction.get("x", 0.0))
        dz = float(direction.get("z", 0.0))
        length = math.hypot(dx, dz)
        if length <= 1e-9:
            continue
        sum_x += dx / length
        sum_z += dz / length
    if math.hypot(sum_x, sum_z) <= 1e-9:
        return {"x": 0.0, "z": 1.0}, False
    axis = _normalize((sum_x, sum_z))
    return {"x": _safe_round(axis[0]), "z": _safe_round(axis[1])}, True


def _collision_map(collisions):
    mapping = {}
    for collision in collisions:
        left_id = str(collision.get("vehicleIdA", "") or "")
        right_id = str(collision.get("vehicleIdB", "") or "")
        if left_id and right_id:
            mapping.setdefault(left_id, []).append(right_id)
            mapping.setdefault(right_id, []).append(left_id)
    return mapping


def _dominant_flow_sign(vehicles, axis_tuple):
    pos_count = 0
    neg_count = 0
    for vehicle in vehicles:
        if int(vehicle.get("laneIndex", -1)) < 0:
            continue
        alignment = _dot(_vehicle_forward(vehicle), axis_tuple)
        if abs(alignment) < ALIGNMENT_MIN_ABS:
            continue
        if alignment >= 0:
            pos_count += 1
        else:
            neg_count += 1
    if pos_count == neg_count or max(pos_count, neg_count) == 0:
        return 0
    return 1 if pos_count > neg_count else -1


def _collision_records(vehicles):
    collisions = []
    for left_index in range(len(vehicles)):
        for right_index in range(left_index + 1, len(vehicles)):
            left = vehicles[left_index]
            right = vehicles[right_index]
            if _rectangles_overlap(
                _oriented_vehicle_corners(left), _oriented_vehicle_corners(right)
            ):
                left_center = _vehicle_center(left)
                right_center = _vehicle_center(right)
                collisions.append(
                    {
                        "vehicleIdA": left["vehicleId"],
                        "vehicleIdB": right["vehicleId"],
                        "estimatedImpactPoint": {
                            "x": round((left_center[0] + right_center[0]) / 2.0, 4),
                            "z": round((left_center[1] + right_center[1]) / 2.0, 4),
                        },
                        "laneTypeA": left.get("laneType", "未知区域"),
                        "laneTypeB": right.get("laneType", "未知区域"),
                    }
                )
    return collisions


def _vehicle_summaries(accident_settings, collisions):
    axis, axis_reliable = _road_axis(accident_settings.get("roads", []))
    axis_tuple = (axis["x"], axis["z"])
    dominant_sign = _dominant_flow_sign(accident_settings.get("vehicles", []), axis_tuple)
    collision_mapping = _collision_map(collisions)
    summaries = []
    for vehicle in accident_settings.get("vehicles", []):
        vehicle_id = str(vehicle.get("vehicleId", "") or "")
        heading = _vehicle_forward(vehicle)
        heading_alignment = _dot(heading, axis_tuple)
        collided_with = collision_mapping.get(vehicle_id, [])
        likely_wrong_way = bool(
            axis_reliable
            and dominant_sign != 0
            and abs(heading_alignment) >= WRONG_WAY_MIN_ABS
            and (1 if heading_alignment >= 0 else -1) != dominant_sign
        )
        observation_tags = []
        if likely_wrong_way:
            observation_tags.append("疑似逆行")
        if vehicle.get("laneType") == "应急车道":
            observation_tags.append("位于应急车道")
        summaries.append(
            {
                "vehicleId": vehicle_id,
                "vehicleType": vehicle.get("type", ""),
                "presetType": vehicle.get("presetType", ""),
                "position": vehicle["position"],
                "rotation": vehicle["rotation"],
                "size": vehicle["size"],
                "laneId": vehicle.get("laneId", "未知区域"),
                "laneType": vehicle.get("laneType", "未知区域"),
                "sourceBox": vehicle.get("sourceBox", {}),
                "headingVector": {
                    "x": _safe_round(heading[0]),
                    "z": _safe_round(heading[1]),
                },
                "headingToRoadAxisAngleDeg": round(
                    _angle_between(heading, axis_tuple, ignore_sign=True), 2
                ),
                "headingAlignmentToRoadAxis": _safe_round(heading_alignment),
                "collidedWithVehicleIds": collided_with,
                "likelyWrongWay": likely_wrong_way,
                "observationTags": observation_tags,
            }
        )
    dominant_flow = "unknown"
    if dominant_sign > 0:
        dominant_flow = "sameAsRoadAxis"
    elif dominant_sign < 0:
        dominant_flow = "oppositeToRoadAxis"
    return summaries, {
        "roadAxis": axis,
        "roadAxisReliable": axis_reliable,
        "dominantTrafficFlowRelativeToRoadAxis": dominant_flow,
    }


def _marker_summaries(accident_settings):
    summaries = []
    for marker in accident_settings.get("markers", []) or []:
        if not isinstance(marker, dict):
            continue
        pos = marker.get("position") or {}
        summaries.append(
            {
                "markerId": str(marker.get("markerId", "") or ""),
                "type": str(marker.get("type", "") or marker.get("presetType", "") or ""),
                "position": {
                    "x": _safe_round(pos.get("x", 0.0)),
                    "z": _safe_round(pos.get("z", 0.0)),
                },
            }
        )
    return summaries


def _motion_path_summaries(accident_settings):
    summaries = []
    for vehicle in accident_settings.get("vehicles", []) or []:
        if not isinstance(vehicle, dict):
            continue
        path = vehicle.get("motionPath")
        if not isinstance(path, list) or len(path) < 2:
            continue
        summaries.append(
            {
                "vehicleId": str(vehicle.get("id", "") or ""),
                "pointCount": len(path),
                "motionSpeedKmh": vehicle.get("motionSpeedKmh"),
                "motionPath": path,
            }
        )
    return summaries


def build_liability_context(
    image_path,
    vehicles,
    lanes,
    accident_brief=None,
    lane_width_settings=None,
    markers=None,
):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图像: {image_path}")
    img_h, img_w = img.shape[:2]
    lane_width = None
    emergency_lane_width = None
    if isinstance(lane_width_settings, dict):
        try:
            lane_width = float(lane_width_settings.get("laneWidth"))
            emergency_lane_width = float(
                lane_width_settings.get("emergencyLaneWidth")
            )
        except (TypeError, ValueError):
            lane_width = None
            emergency_lane_width = None
        if (
            lane_width is not None
            and (lane_width <= 0 or emergency_lane_width <= 0)
        ):
            lane_width = None
            emergency_lane_width = None
    accident_settings = convert_to_3d_data(
        vehicles,
        lanes,
        img_w,
        img_h,
        img,
        markers=markers,
        lane_width=lane_width,
        emergency_lane_width=emergency_lane_width,
    )
    collisions = _collision_records(accident_settings["vehicles"])
    vehicle_summaries, traffic_reference = _vehicle_summaries(
        accident_settings, collisions
    )
    marker_summaries = _marker_summaries(accident_settings)
    motion_summaries = _motion_path_summaries(accident_settings)
    context = {
        "imagePath": image_path,
        "vehicleCount": len(vehicle_summaries),
        "laneCount": len(accident_settings.get("roads", [])),
        "markerCount": len(marker_summaries),
        "accidentSettings": accident_settings,
        "vehicleSummaries": vehicle_summaries,
        "markerSummaries": marker_summaries,
        "motionPathSummaries": motion_summaries,
        "collisionSummaries": collisions,
        "trafficFlowReference": traffic_reference,
        "observableLimits": [
            "仅依据单张图片建模数据分析，无法确认具体时间、日期、天气、信号灯状态、车速和驾驶人口供。",
            "禁止输出东南西北、由南往北等绝对方向描述；若需描述方向，只能相对道路轴线说明同向、反向、斜向。",
            "必须综合参考全部图层信息：车辆、道路线、标记物、运动路径（若有）以及用户案情简述。",
        ],
    }
    brief_text = str(accident_brief or "").strip()
    if brief_text:
        context["userReportedAccidentBrief"] = brief_text
        context["observableLimits"].append(
            "userReportedAccidentBrief 是用户用车辆ID撰写的简要案情描述，可作为参考线索辅助分析，"
            "但仍须以现场数据为准，如与现场数据冲突以现场数据为准。"
        )
    return context


def _request_payload(liability_context, ai_settings, experts=None):
    request_config = ai_request_config(ai_settings)
    expert_list = experts if isinstance(experts, list) else []
    response_schema = {
        "overallSummary": "字符串，总结事故整体责任划分",
        "vehicleResponsibilities": [
            {
                "vehicleId": "车辆1",
                "responsibility": "全责/主责/次责/同责/无责/责任待定",
                "reason": "说明责任原因",
                "accidentRole": "说明该车在事故中的作用",
            }
        ],
        "accidentAnalysis": "字符串，说明事故经过和关键碰撞关系",
        "preventionSuggestions": [
            "字符串，给出一条防控建议"
        ],
        "report": "字符串，给出完整事故报告",
        "expertSpeeches": [
            {
                "expertId": "case",
                "expertName": "案件侦办大队长",
                "speech": "该专家以第一人称发表的完整发言",
            }
        ],
    }
    prompt = {
        "task": (
            "你是事故发生后到达现场的交警调查员。accidentData 是事故已经发生之后的静态现场快照，"
            "其中车辆的位置、朝向、姿态都是碰撞或停车之后的最终状态，不是正在行驶的瞬时状态，也不是事故即将发生的预测画面。"
            "请以事后勘查的视角，先结合车道、位置、朝向、尺寸、标记物、运动路径和碰撞关系还原事故发生前各车辆的行驶轨迹与关键行为"
            "（如变道、转向、逆行、压线、占用应急车道等），再据此定位引发事故的直接原因和过错方，"
            "最后依据中国道路交通事故责任认定的一般规则给出每辆车的责任划分，"
            "并按 experts 列表顺序，分别以各位专家身份撰写第一人称发言。"
        ),
        "requirements": [
            "必须仅返回 JSON 对象，不能返回 Markdown 或额外说明。",
            "accidentData 描述的是事故已经发生后的静态现场，禁止使用‘正在发生’‘即将相撞’‘正驶向’‘正在变道’等进行时表述；"
            "应使用‘已发生碰撞’‘碰撞后停止于此’‘事故发生前该车曾……’等事后调查表述。",
            "必须以事后还原的方式叙述事故经过：先依据现场车辆姿态/位置/碰撞点反推事故前各车的行驶方向与关键操作，"
            "再说明哪一步操作或违规行为引发了本次事故，最后给出碰撞结果与最终停止状态。",
            "accidentAnalysis 与 report 必须体现‘事故发生前→引发事故的关键行为→碰撞→碰撞后停止状态’的因果链条，"
            "并明确指出引发事故的直接原因（如变更车道未让行、逆行、违规占道等），不能只描述当前位置关系。",
            "责任说明必须基于 vehicleId，不得使用颜色或模糊位置代称。",
            "如果某车辆与事故无关，请明确写无责，并在 reason 中说明未形成碰撞或未影响事故。",
            "需要结合车辆位置、方向、尺寸、车道类型、标记物、运动路径（若有）、碰撞关系进行分析。",
            "markerSummaries / accidentSettings.markers 中的散落物、碰撞点、锥桶、人员、导向牌等标记物必须纳入分析参考。",
            "motionPathSummaries 若存在，表示用户标注的车辆运动路径与相对车速，须作为事故前运动过程的重要参考。",
            "严禁臆造照片无法直接确认的信息，包括但不限于具体时间、日期、天气、信号灯状态、车速、驾驶人口供、东南西北或由南往北等绝对方向。",
            "可描述沿道路轴线同向、反向、斜向，不能写成东南西北。",
            "如果 vehicleSummaries 中某车 likelyWrongWay=true 且 collidedWithVehicleIds 非空，该车不得直接认定为无责；若非主责或全责，必须给出明确可观察依据。",
            "高速公路场景中，如果 vehicleSummaries 中某车 likelyWrongWay=true，即使该车未直接发生碰撞，"
            "但现场关系显示非逆行车辆可能为躲避该逆行车辆而变道、偏离车道并撞击其他车辆或护栏，"
            "应将逆行车辆认定为引发事故的直接原因并承担全责，避让车辆原则上不承担主要责任。",
            "若判断某车无责，必须明确写出其未碰撞、未接触或未对事故形成因果贡献的原因。",
            "事故报告 report 仅保留可观察事实与责任结论，不得复述原始 JSON。",
            "责任划分必须满足配对互斥规则：如果有车辆判定为‘主责’，则其余涉事车辆中必须至少有一辆为‘次责’，绝不允许出现‘某车主责而其他涉事车辆全部为无责或全部为同责’的情形。",
            "如果有车辆判定为‘全责’，则其他所有车辆必须为‘无责’，不允许同时出现‘次责/主责/同责’；‘全责’与‘次责’不得在同一事故中共存。",
            "如果有车辆判定为‘同责’，则其他涉事车辆中必须至少有一辆同样为‘同责’，不得出现‘某车同责而其他车辆为主责/次责’的逻辑矛盾。",
            "认定责任前先按上述配对规则自检一次：若发现矛盾，必须重新衡量证据并修正责任，使最终结果在逻辑上自洽。",
            "必须一次性返回全部结果，禁止按专家角色分多次请求或省略 expertSpeeches。",
            "expertSpeeches 必须按 experts 数组顺序逐人输出，expertId/expertName 与列表一致，speech 使用该专家第一人称口吻并贴合其 rolePrompt。",
        ],
        "experts": [
            {
                "expertId": item.get("id"),
                "expertName": item.get("name"),
                "rolePrompt": item.get("rolePrompt", ""),
            }
            for item in expert_list
        ],
        "sceneContext": {
            "snapshotTiming": "post_accident",
            "description": (
                "本数据为事故发生之后的事故现场静态快照，所有车辆位置和姿态均为碰撞或停车之后的最终状态。"
                "AI 的任务是以事后到达现场的交警身份进行调查、还原事故经过、定位引发原因并划分责任，"
                "同时按专家角色依次撰写发言，而不是描述一个正在发生或可能发生的事故。"
            ),
        },
        "responseSchema": response_schema,
        "accidentData": liability_context,
    }
    append_requirement = str(
        request_config.get("liabilityAppendRequirement", "") or ""
    ).strip()
    if append_requirement:
        prompt["requirements"].append(append_requirement)
    system_prompt = (
        "你是一名中国交警事故调查员，正在对一起已经发生的高速公路交通事故现场进行事后勘查。"
        "你拿到的所有数据都是事故发生之后的静态现场快照（车辆位置、姿态均为碰撞或停止后的最终状态），"
        "不是实时行驶画面，也不是事故预测。"
        "请基于现场快照反推事故经过、定位引发事故的直接原因，并依据中国道路交通事故责任认定规则划分责任。"
        "同时按 experts 列表中的角色定位，一次性为每位专家撰写第一人称发言。"
        "只能输出严格 JSON，不得返回任何额外说明或 Markdown。"
    )
    return {
        "model": request_config["model"] or DEFAULT_DEEPSEEK_MODEL,
        "temperature": request_config["temperature"],
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
    }


def _request_options(ai_settings):
    safe_settings = sanitize_ai_settings(ai_settings)
    request_config = ai_request_config(safe_settings)
    payload_extras = {}
    if request_config["reasoningEffort"]:
        payload_extras["reasoning_effort"] = request_config["reasoningEffort"]
    if request_config["thinkingMode"] in {"enabled", "disabled"}:
        payload_extras["extra_body"] = {
            "thinking": {"type": request_config["thinkingMode"]}
        }
    return {
        "apiKey": safe_settings["deepseekApiKey"],
        "requestUrl": request_config["requestUrl"] or DEFAULT_DEEPSEEK_CHAT_URL,
        "requestTimeoutSec": request_config["requestTimeoutSec"],
        "requestConfig": request_config,
        "payloadExtras": payload_extras,
    }


def _extract_json_content(content):
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _clean_non_observable_text(text, fallback=""):
    raw = str(text or "").strip()
    if not raw:
        return fallback
    pieces = re.split(r"(?<=[。！？；\n])", raw)
    kept = []
    for piece in pieces:
        stripped = piece.strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in NON_OBSERVABLE_PATTERNS):
            continue
        kept.append(stripped)
    cleaned = "".join(kept).strip()
    return cleaned or fallback


def _normalize_responsibility(value):
    text = str(value or "").strip()
    return text or "责任待定"


def _sorted_vehicle_responsibilities(items):
    def sort_key(item):
        vehicle_id = str(item.get("vehicleId", "") or "")
        match = re.search(r"(\d+)$", vehicle_id)
        return (int(match.group(1)) if match else 10**9, vehicle_id)

    return sorted(items, key=sort_key)


def _enforce_responsibility_consistency(response):
    items = response.get("vehicleResponsibilities")
    if not isinstance(items, list) or not items:
        return []

    def _set_resp(item, new_resp, suffix):
        old_resp = item.get("responsibility", "责任待定")
        if old_resp == new_resp:
            return None
        item["responsibility"] = new_resp
        reason_text = str(item.get("reason", "") or "").strip()
        suffix_text = f"（系统自动修正：{old_resp}→{new_resp}，{suffix}）"
        item["reason"] = (reason_text + suffix_text).strip()
        return f"{item.get('vehicleId', '未知车辆')} 由 {old_resp} 修正为 {new_resp}"

    corrections = []
    resp_counter = {}
    for item in items:
        resp = str(item.get("responsibility", "") or "").strip()
        resp_counter[resp] = resp_counter.get(resp, 0) + 1

    if resp_counter.get("全责", 0) >= 1:
        for item in items:
            resp = str(item.get("responsibility", "") or "").strip()
            if resp == "全责":
                continue
            if resp != "无责":
                note = _set_resp(
                    item,
                    "无责",
                    "存在‘全责’车辆时其余车辆只能为‘无责’",
                )
                if note:
                    corrections.append(note)
    elif resp_counter.get("主责", 0) >= 1:
        has_secondary = resp_counter.get("次责", 0) >= 1
        if not has_secondary:
            promoted = False
            for item in items:
                resp = str(item.get("responsibility", "") or "").strip()
                if resp in {"无责", "责任待定", "同责"} and not promoted:
                    note = _set_resp(
                        item,
                        "次责",
                        "存在‘主责’车辆必须配对‘次责’",
                    )
                    if note:
                        corrections.append(note)
                        promoted = True
    elif resp_counter.get("同责", 0) == 1:
        single_same = None
        for item in items:
            resp = str(item.get("responsibility", "") or "").strip()
            if resp == "同责":
                single_same = item
                break
        for item in items:
            if item is single_same:
                continue
            resp = str(item.get("responsibility", "") or "").strip()
            if resp in {"主责", "次责"}:
                note = _set_resp(
                    item,
                    "同责",
                    "存在‘同责’车辆时其余涉事车辆需同样为‘同责’",
                )
                if note:
                    corrections.append(note)
    return corrections


def _repair_vehicle_responsibilities(parsed_content, liability_context):
    response = parsed_content if isinstance(parsed_content, dict) else {}
    raw_items = response.get("vehicleResponsibilities")
    vehicle_items = raw_items if isinstance(raw_items, list) else []
    item_map = {}
    for item in vehicle_items:
        if not isinstance(item, dict):
            continue
        vehicle_id = str(item.get("vehicleId", "") or "").strip()
        if vehicle_id:
            item_map[vehicle_id] = dict(item)

    corrected_wrong_way_ids = []
    for summary in liability_context.get("vehicleSummaries", []):
        vehicle_id = str(summary.get("vehicleId", "") or "")
        if not vehicle_id:
            continue
        item = item_map.setdefault(
            vehicle_id,
            {
                "vehicleId": vehicle_id,
                "responsibility": "责任待定",
                "reason": "",
                "accidentRole": "",
            },
        )
        item["responsibility"] = _normalize_responsibility(item.get("responsibility"))
        item["reason"] = _clean_non_observable_text(
            item.get("reason"),
            fallback="需结合可观察碰撞关系和车道位置进一步判断。",
        )
        item["accidentRole"] = _clean_non_observable_text(
            item.get("accidentRole"),
            fallback="现场相关车辆",
        )
        if summary.get("likelyWrongWay") and summary.get("collidedWithVehicleIds"):
            if item["responsibility"] in {"无责", "责任待定"}:
                item["responsibility"] = "主责"
                item["reason"] = (
                    "根据建模数据，该车沿道路轴线反向行驶，存在明显疑似逆行特征，"
                    "且已与事故相关车辆发生碰撞，不能认定为无责。"
                )
                item["accidentRole"] = "疑似逆行并与事故车辆发生碰撞"
                corrected_wrong_way_ids.append(vehicle_id)
        if not summary.get("collidedWithVehicleIds") and item["responsibility"] == "无责":
            if "未形成碰撞" not in item["reason"] and "未影响事故" not in item["reason"]:
                item["reason"] = "该车未与事故车辆形成碰撞，且未见其对事故形成直接因果贡献。"

    response["vehicleResponsibilities"] = _sorted_vehicle_responsibilities(
        list(item_map.values())
    )
    if corrected_wrong_way_ids:
        correction_text = "；".join(
            f"{vehicle_id} 因疑似逆行且已发生碰撞，责任下限修正为主责"
            for vehicle_id in corrected_wrong_way_ids
        )
        response["overallSummary"] = _clean_non_observable_text(
            response.get("overallSummary"),
            fallback="已结合车辆位置、方向、车道与碰撞关系完成责任划分。",
        )
        if correction_text not in response["overallSummary"]:
            response["overallSummary"] = f"{response['overallSummary']} {correction_text}".strip()
        response["accidentAnalysis"] = _clean_non_observable_text(
            response.get("accidentAnalysis"),
            fallback="已结合车辆位置、姿态、车道关系与碰撞情况进行分析。",
        )
        if correction_text not in response["accidentAnalysis"]:
            response["accidentAnalysis"] = (
                f"{response['accidentAnalysis']} {correction_text}"
            ).strip()
    else:
        response["overallSummary"] = _clean_non_observable_text(
            response.get("overallSummary"),
            fallback="已结合车辆位置、方向、车道与碰撞关系完成责任划分。",
        )
        response["accidentAnalysis"] = _clean_non_observable_text(
            response.get("accidentAnalysis"),
            fallback="已结合车辆位置、姿态、车道关系与碰撞情况进行分析。",
        )

    suggestions = response.get("preventionSuggestions")
    if isinstance(suggestions, list):
        response["preventionSuggestions"] = [
            _clean_non_observable_text(item)
            for item in suggestions
            if _clean_non_observable_text(item)
        ]
    else:
        cleaned_suggestion = _clean_non_observable_text(suggestions)
        response["preventionSuggestions"] = [cleaned_suggestion] if cleaned_suggestion else []
    response["report"] = _clean_non_observable_text(
        response.get("report"),
        fallback=response["overallSummary"],
    )

    expert_speeches = response.get("expertSpeeches")
    if not isinstance(expert_speeches, list):
        expert_speeches = []
    cleaned_speeches = []
    for item in expert_speeches:
        if not isinstance(item, dict):
            continue
        speech = _clean_non_observable_text(item.get("speech"), fallback="")
        if not speech:
            continue
        cleaned_speeches.append(
            {
                "expertId": str(item.get("expertId", "") or "").strip(),
                "expertName": str(item.get("expertName", "") or "").strip(),
                "speech": speech,
            }
        )
    response["expertSpeeches"] = cleaned_speeches

    consistency_notes = _enforce_responsibility_consistency(response)
    if consistency_notes:
        correction_text = "；".join(consistency_notes)
        response["overallSummary"] = (
            f"{response['overallSummary']} 责任配对一致性自动修正：{correction_text}。"
        ).strip()
        response["accidentAnalysis"] = (
            f"{response['accidentAnalysis']} 责任配对一致性自动修正：{correction_text}。"
        ).strip()
        response["report"] = (
            f"{response['report']} 责任配对一致性自动修正：{correction_text}。"
        ).strip()
        response["vehicleResponsibilities"] = _sorted_vehicle_responsibilities(
            response["vehicleResponsibilities"]
        )

    return response


def _align_expert_speeches(parsed_content, experts):
    response = parsed_content if isinstance(parsed_content, dict) else {}
    speeches = response.get("expertSpeeches")
    if not isinstance(speeches, list):
        speeches = []
    by_id = {}
    by_name = {}
    for item in speeches:
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("expertId", "") or "").strip()
        expert_name = str(item.get("expertName", "") or "").strip()
        if expert_id:
            by_id[expert_id] = item
        if expert_name:
            by_name[expert_name] = item
    aligned = []
    for expert in experts or []:
        expert_id = str(expert.get("id", "") or "")
        expert_name = str(expert.get("name", "") or "")
        item = by_id.get(expert_id) or by_name.get(expert_name) or {}
        speech = _clean_non_observable_text(
            item.get("speech"),
            fallback=f"我是{expert_name}，结合现场数据完成本次专项分析。",
        )
        aligned.append(
            {
                "expertId": expert_id,
                "expertName": expert_name,
                "speech": speech,
            }
        )
    response["expertSpeeches"] = aligned
    return response


def request_liability_analysis(ai_settings, liability_context):
    request_options = _request_options(ai_settings)
    token = str(request_options["apiKey"] or "").strip()
    if not token:
        raise ValueError("未配置 DeepSeek API 密钥。")
    experts_payload = load_ai_experts()
    experts = experts_for_runtime(experts_payload)
    payload = _request_payload(liability_context, ai_settings, experts=experts)
    payload.update(request_options["payloadExtras"])
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        request_options["requestUrl"],
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=request_options["requestTimeoutSec"]) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    content = response_payload["choices"][0]["message"]["content"]
    parsed_content = json.loads(_extract_json_content(content))
    parsed_content = _repair_vehicle_responsibilities(parsed_content, liability_context)
    parsed_content = _align_expert_speeches(parsed_content, experts)
    return {
        "provider": "DeepSeek",
        "model": payload["model"],
        "requestUrl": request_options["requestUrl"],
        "requestConfig": request_options["requestConfig"],
        "response": parsed_content,
        "requestContext": liability_context,
        "experts": experts,
    }
