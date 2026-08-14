import base64
import json
import os
import re
import shutil
import uuid
from copy import deepcopy

import cv2
import numpy as np

from utils.app_paths import app_path


MAX_EXPERTS = 12
MAX_ROLE_CHARS = 500
MAX_AVATAR_BYTES = 500 * 1024
DEFAULT_UNKNOWN_AVATAR = "default_unknown.png"

EXPERTS_CONFIG_PATH = app_path("config", "ai_experts.json")
EXPERT_PIC_DIR = app_path("ExpertPic")

DEFAULT_EXPERT_IDS = ("case", "order", "road", "command")

DEFAULT_ROLE_PROMPTS = {
    "case": (
        "高速公路交警，负责侦破该事故案件的成因，调查各车辆的责任。"
        "在报告中会说类似“我来向您讲一下本次事故的经过，车辆1和车辆2本身是并行"
        "（具体车道、车速、方向等等），忽然车辆2失控……，造成了……处碰撞、预计车辆X/道路X处的护栏受损，"
        "其根本原因是车辆2……疲劳驾驶/操作失误/低速行驶/违法停车/倒车……违反了……法律法规，"
        "我认为它负主要、次要、同等、无责任……，我认为接下来的调查方向有……”的话。"
    ),
    "order": (
        "高速公路交警，负责找出该事故中驾驶人的主要违法，列举今后的工作方向。"
        "在报告中会说类似“我来分析一下事故中的违法情况，我发现车辆X、车辆X、车辆X分别有如下违法行为……"
        "其中X违法行为对引发交通事故的影响较大，我认为应该从以下X个角度来安排执法整治专项行动，分别是……；"
        "从X个角度来加强警示宣传，分别是……”"
    ),
    "road": (
        "高速公路交警，负责找出该事故中道路影响事故的因素，例如应急车道过窄容易发生二次事故；"
        "车辆轨迹线转急弯说明道路摩擦系数不足；驾驶人违停、倒车说明路缺少标志标牌、抓拍设备；"
        "驾驶人疲劳驾驶说明缺少短信、电话、声光电等现代化提示手段；车速过快说明缺少减速带。"
        "在报告中会说类似“我来看看本次事故是否存在道路影响……因此，我觉得路面应当增设……”"
    ),
    "command": (
        "高速公路交警，负责找出该事故中能被监控或者GPS信号发现的动态风险和二次事故隐患，"
        "例如车辆存在违停、倒车、占用应急车道、行人进入高速这种监控中能发现并制止的违法行为，"
        "提出指挥中心接下来的工作计划。"
        "在报告中会说类似“我来汇报一下本次事故的动态风险隐患，车辆X/车辆X……存在动态违法行为，"
        "这些行为对事故有……影响/诱因……，接下来指挥中心应当通过如下手段……来强化动态风险的发现和制止。”"
    ),
}

DEFAULT_EXPERT_DEFS = (
    {
        "id": "case",
        "name": "案件侦办大队长",
        "avatarFile": "案侦.png",
        "isDefault": True,
        "enabled": True,
        "rolePrompt": DEFAULT_ROLE_PROMPTS["case"],
    },
    {
        "id": "order",
        "name": "秩序管理大队长",
        "avatarFile": "秩序.png",
        "isDefault": True,
        "enabled": True,
        "rolePrompt": DEFAULT_ROLE_PROMPTS["order"],
    },
    {
        "id": "road",
        "name": "护路联防大队长",
        "avatarFile": "护路.png",
        "isDefault": True,
        "enabled": True,
        "rolePrompt": DEFAULT_ROLE_PROMPTS["road"],
    },
    {
        "id": "command",
        "name": "指挥调度大队长",
        "avatarFile": "指挥.png",
        "isDefault": True,
        "enabled": True,
        "rolePrompt": DEFAULT_ROLE_PROMPTS["command"],
    },
)


def expert_pic_dir():
    os.makedirs(EXPERT_PIC_DIR, exist_ok=True)
    return EXPERT_PIC_DIR


def ensure_default_unknown_avatar():
    path = os.path.join(expert_pic_dir(), DEFAULT_UNKNOWN_AVATAR)
    if os.path.isfile(path):
        return path
    img = np.full((256, 256, 3), 220, dtype=np.uint8)
    cv2.circle(img, (128, 128), 118, (190, 190, 190), -1)
    cv2.circle(img, (128, 128), 118, (140, 140, 140), 4)
    cv2.putText(
        img,
        "?",
        (98, 168),
        cv2.FONT_HERSHEY_SIMPLEX,
        3.2,
        (90, 90, 90),
        8,
        cv2.LINE_AA,
    )
    cv2.imwrite(path, img)
    return path


def _clip_role(text):
    return str(text or "").strip()[:MAX_ROLE_CHARS]


def _default_payload():
    return {
        "version": 1,
        "experts": [deepcopy(item) for item in DEFAULT_EXPERT_DEFS],
        "customOrder": [],
    }


def _normalize_expert(raw, fallback_id=""):
    data = raw if isinstance(raw, dict) else {}
    expert_id = str(data.get("id", fallback_id) or fallback_id).strip()
    is_default = bool(data.get("isDefault", expert_id in DEFAULT_EXPERT_IDS))
    name = str(data.get("name", "") or "").strip()
    avatar_file = str(data.get("avatarFile", "") or "").strip() or DEFAULT_UNKNOWN_AVATAR
    role_prompt = _clip_role(data.get("rolePrompt", ""))
    enabled = True if is_default else bool(data.get("enabled", True))
    if not expert_id:
        expert_id = f"custom_{uuid.uuid4().hex[:8]}"
    if not name:
        name = expert_id
    return {
        "id": expert_id,
        "name": name,
        "avatarFile": avatar_file,
        "isDefault": is_default,
        "enabled": enabled,
        "rolePrompt": role_prompt,
        "createdAt": str(data.get("createdAt", "") or ""),
    }


def sanitize_experts_payload(raw_payload):
    ensure_default_unknown_avatar()
    payload = _default_payload()
    if not isinstance(raw_payload, dict):
        return payload

    defaults_by_id = {item["id"]: deepcopy(item) for item in DEFAULT_EXPERT_DEFS}
    incoming = raw_payload.get("experts", [])
    incoming_map = {}
    custom_list = []
    if isinstance(incoming, list):
        for item in incoming:
            expert = _normalize_expert(item)
            if expert["isDefault"] and expert["id"] in defaults_by_id:
                base = defaults_by_id[expert["id"]]
                base["rolePrompt"] = expert["rolePrompt"] or base["rolePrompt"]
                base["name"] = defaults_by_id[expert["id"]]["name"]
                base["avatarFile"] = defaults_by_id[expert["id"]]["avatarFile"]
                base["enabled"] = True
                incoming_map[expert["id"]] = base
            elif not expert["isDefault"]:
                if not expert["rolePrompt"]:
                    expert["rolePrompt"] = "高速公路交警专家，请结合现场数据发言。"
                custom_list.append(expert)

    experts = []
    for default in DEFAULT_EXPERT_DEFS:
        experts.append(incoming_map.get(default["id"], deepcopy(default)))

    # Preserve declared custom order when possible.
    order = raw_payload.get("customOrder", [])
    ordered_ids = []
    if isinstance(order, list):
        ordered_ids = [str(x) for x in order if str(x)]
    custom_map = {item["id"]: item for item in custom_list}
    for expert_id in ordered_ids:
        if expert_id in custom_map:
            experts.append(custom_map.pop(expert_id))
    for expert in custom_list:
        if expert["id"] in custom_map:
            experts.append(custom_map.pop(expert["id"]))

    experts = experts[:MAX_EXPERTS]
    payload["experts"] = experts
    payload["customOrder"] = [
        item["id"] for item in experts if not item.get("isDefault")
    ]
    return payload


def load_ai_experts():
    ensure_default_unknown_avatar()
    if not os.path.isfile(EXPERTS_CONFIG_PATH):
        payload = _default_payload()
        save_ai_experts(payload)
        return payload
    try:
        with open(EXPERTS_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = _default_payload()
    payload = sanitize_experts_payload(raw)
    return payload


def save_ai_experts(payload):
    ensure_default_unknown_avatar()
    clean = sanitize_experts_payload(payload)
    os.makedirs(os.path.dirname(EXPERTS_CONFIG_PATH), exist_ok=True)
    with open(EXPERTS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


def list_experts(payload=None):
    data = payload if isinstance(payload, dict) else load_ai_experts()
    return list(data.get("experts", []))


def enabled_experts_for_ai(payload=None):
    """Default experts always included; custom only when enabled."""
    experts = []
    for expert in list_experts(payload):
        if expert.get("isDefault") or expert.get("enabled"):
            experts.append(deepcopy(expert))
    return experts


def avatar_path_for(expert):
    ensure_default_unknown_avatar()
    filename = str((expert or {}).get("avatarFile", "") or DEFAULT_UNKNOWN_AVATAR)
    filename = os.path.basename(filename)
    path = os.path.join(expert_pic_dir(), filename)
    if os.path.isfile(path):
        return path
    return os.path.join(expert_pic_dir(), DEFAULT_UNKNOWN_AVATAR)


def avatar_data_url(expert):
    path = avatar_path_for(expert)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def experts_for_runtime(payload=None):
    result = []
    for expert in enabled_experts_for_ai(payload):
        result.append(
            {
                "id": expert["id"],
                "name": expert["name"],
                "rolePrompt": expert.get("rolePrompt", ""),
                "isDefault": bool(expert.get("isDefault")),
                "avatarDataUrl": avatar_data_url(expert),
            }
        )
    return result


def validate_avatar_file(path):
    if not path or not os.path.isfile(path):
        return False, "头像文件不存在"
    size = os.path.getsize(path)
    if size <= 0:
        return False, "头像文件为空"
    if size > MAX_AVATAR_BYTES:
        return False, "头像不能超过 500KB"
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return False, "无法读取头像图片"
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return False, "头像尺寸无效"
    if h != w:
        return False, "头像必须是 1:1 正方形"
    return True, ""


def _safe_avatar_filename(expert_id, source_path):
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(expert_id or "expert"))
    return f"{safe_id}_{uuid.uuid4().hex[:8]}{ext}"


def store_avatar_file(source_path, expert_id):
    ok, message = validate_avatar_file(source_path)
    if not ok:
        raise ValueError(message)
    filename = _safe_avatar_filename(expert_id, source_path)
    dest = os.path.join(expert_pic_dir(), filename)
    shutil.copy2(source_path, dest)
    return filename


def create_custom_expert(name, role_prompt, avatar_source_path=None, payload=None):
    data = sanitize_experts_payload(payload or load_ai_experts())
    if len(data["experts"]) >= MAX_EXPERTS:
        raise ValueError(f"专家总数不能超过 {MAX_EXPERTS} 人")
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("专家名称不能为空")
    role = _clip_role(role_prompt)
    if not role:
        raise ValueError("角色定位不能为空")
    expert_id = f"custom_{uuid.uuid4().hex[:10]}"
    avatar_file = DEFAULT_UNKNOWN_AVATAR
    if avatar_source_path:
        avatar_file = store_avatar_file(avatar_source_path, expert_id)
    expert = {
        "id": expert_id,
        "name": clean_name,
        "avatarFile": avatar_file,
        "isDefault": False,
        "enabled": True,
        "rolePrompt": role,
        "createdAt": uuid.uuid4().hex,
    }
    data["experts"].append(expert)
    data["customOrder"].append(expert_id)
    return save_ai_experts(data), expert


def update_expert(expert_id, *, name=None, role_prompt=None, enabled=None, avatar_source_path=None, payload=None):
    data = sanitize_experts_payload(payload or load_ai_experts())
    target = None
    for expert in data["experts"]:
        if expert["id"] == expert_id:
            target = expert
            break
    if target is None:
        raise ValueError("未找到该专家")
    if name is not None and not target.get("isDefault"):
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("专家名称不能为空")
        target["name"] = clean_name
    if role_prompt is not None:
        role = _clip_role(role_prompt)
        if not role:
            raise ValueError("角色定位不能为空")
        target["rolePrompt"] = role
    if enabled is not None and not target.get("isDefault"):
        target["enabled"] = bool(enabled)
    if avatar_source_path:
        target["avatarFile"] = store_avatar_file(avatar_source_path, target["id"])
    return save_ai_experts(data), target


def delete_expert(expert_id, payload=None):
    data = sanitize_experts_payload(payload or load_ai_experts())
    target = next((e for e in data["experts"] if e["id"] == expert_id), None)
    if target is None:
        raise ValueError("未找到该专家")
    if target.get("isDefault"):
        raise ValueError("默认专家无法删除")
    data["experts"] = [e for e in data["experts"] if e["id"] != expert_id]
    data["customOrder"] = [eid for eid in data["customOrder"] if eid != expert_id]
    return save_ai_experts(data)
