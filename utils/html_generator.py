import json
import os
import re
import cv2
from datetime import datetime
from utils.app_paths import app_path
from utils.animation_settings import playback_speed_factor
from utils.data_converter import convert_to_3d_data
from utils.measurement_service_config import (
    MEASUREMENT_SAVE_URL,
    configured_measurement_save_url,
)
from utils.scene_model_injection import inject_scene_model_scripts


RUNTIME_CONFIG_START = '<script id="runtime-config">'
RUNTIME_CONFIG_END = '</script>'


def _runtime_config_script(
    source_html_path="",
    save_measurements_url="",
    saved_measurements=None,
    extra_runtime=None,
):
    runtime_config = {
        "sourceHtmlPath": source_html_path or "",
        "saveMeasurementsUrl": save_measurements_url
        or configured_measurement_save_url()
        or MEASUREMENT_SAVE_URL,
        "savedMeasurements": saved_measurements or [],
    }
    if isinstance(extra_runtime, dict):
        runtime_config.update(extra_runtime)
    runtime_json = json.dumps(runtime_config, ensure_ascii=False)
    return f'{RUNTIME_CONFIG_START}\nconst accidentSceneRuntime = {runtime_json};\n{RUNTIME_CONFIG_END}'


def read_runtime_config(html_content):
    match = re.search(
        r'const\s+accidentSceneRuntime\s*=\s*(\{[\s\S]*?\})\s*;',
        html_content,
    )
    if not match:
        return {}
    return json.loads(match.group(1))


def inject_runtime_config(
    html_content,
    source_html_path="",
    save_measurements_url="",
    saved_measurements=None,
    extra_runtime=None,
):
    script_tag = _runtime_config_script(
        source_html_path,
        save_measurements_url,
        saved_measurements,
        extra_runtime=extra_runtime,
    )
    start = html_content.find(RUNTIME_CONFIG_START)
    if start >= 0:
        end = html_content.find(RUNTIME_CONFIG_END, start)
        if end >= 0:
            end += len(RUNTIME_CONFIG_END)
            return html_content[:start] + script_tag + html_content[end:]

    marker = '<!-- 引入 Three.js -->'
    if marker in html_content:
        return html_content.replace(marker, script_tag + "\n    " + marker, 1)
    return html_content


_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')
_TIMESTAMP_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")


def _line_html_path(source_html_path):
    root, ext = os.path.splitext(source_html_path)
    if root.endswith("(line)"):
        return source_html_path
    return f"{root}(line){ext or '.html'}"


def validate_save_file_name_base(file_name_base):
    """Return (ok, message, cleaned_base)."""
    name = str(file_name_base or "").strip()
    if not name:
        return False, "文件名不能为空", ""
    if name in {".", ".."}:
        return False, "文件名无效", ""
    if any(ch in _INVALID_FILENAME_CHARS for ch in name):
        return False, '文件名不能包含 \\ / : * ? " < > |', ""
    if any(ord(ch) < 32 for ch in name):
        return False, "文件名包含非法控制字符", ""
    return True, "", name


def suggest_save_file_name_base(source_html_path):
    stem = os.path.splitext(os.path.basename(str(source_html_path or "")))[0]
    if stem.endswith("(line)"):
        stem = stem[: -len("(line)")]
    stem = _TIMESTAMP_SUFFIX_RE.sub("", stem)
    return stem or "accident"


def build_line_html_filename(file_name_base, timestamp=None):
    ok, message, cleaned = validate_save_file_name_base(file_name_base)
    if not ok:
        raise ValueError(message)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cleaned}_{stamp}(line).html"


def save_measurement_html(
    source_html_path,
    measurements,
    save_measurements_url="",
    file_name_base=None,
    overwrite=False,
    history_dir=None,
    target_html_path=None,
):
    """
    将测量线数据写入 history 下的 `{name}_{time}(line).html`。
    未提供 file_name_base 时保持旧逻辑：同源文件名加 (line)。
    """
    source_abs = os.path.abspath(source_html_path)
    history_abs = os.path.abspath(history_dir or app_path("history"))
    if target_html_path:
        target_abs = os.path.abspath(target_html_path)
        try:
            if os.path.commonpath(
                [os.path.normcase(history_abs), os.path.normcase(target_abs)]
            ) != os.path.normcase(history_abs):
                raise ValueError("Invalid target HTML path")
        except ValueError as exc:
            raise ValueError("Invalid target HTML path") from exc
        if not target_abs.lower().endswith(".html"):
            raise ValueError("Invalid target HTML path")
    elif file_name_base is None or str(file_name_base).strip() == "":
        target_abs = os.path.abspath(_line_html_path(source_abs))
    else:
        os.makedirs(history_abs, exist_ok=True)
        filename = build_line_html_filename(file_name_base)
        target_abs = os.path.abspath(os.path.join(history_abs, filename))
        if os.path.exists(target_abs) and not overwrite:
            return {
                "needsOverwrite": True,
                "path": target_abs,
                "fileName": os.path.basename(target_abs),
            }

    with open(source_abs, "r", encoding="utf-8") as f:
        html_content = f.read()
    runtime_config = read_runtime_config(html_content)
    runtime_config["sourceHtmlPath"] = target_abs
    runtime_config["saveMeasurementsUrl"] = save_measurements_url or runtime_config.get(
        "saveMeasurementsUrl", configured_measurement_save_url() or MEASUREMENT_SAVE_URL
    )
    runtime_config["savedMeasurements"] = measurements

    html_content = inject_runtime_config(
        html_content,
        source_html_path=target_abs,
        save_measurements_url=save_measurements_url,
        saved_measurements=measurements,
        extra_runtime=runtime_config,
    )

    with open(target_abs, "w", encoding="utf-8") as f:
        f.write(html_content)
    return target_abs


def generate_html(
    image_path,
    vehicles,
    lanes,
    markers=None,
    save_measurements_url="",
    ai_analysis=None,
    liability_context=None,
    lane_width_settings=None,
):
    """
    根据图像和检测数据生成最终的 HTML 场景文件
    """
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

    # 转换坐标（传入图像以采样车身颜色）
    data = convert_to_3d_data(
        vehicles,
        lanes,
        img_w,
        img_h,
        img,
        markers=markers,
        lane_width=lane_width,
        emergency_lane_width=emergency_lane_width,
    )
    settings_json = json.dumps(data, ensure_ascii=False)

    # 只内嵌本次报告实际用到的车型 GLB 模型，控制生成的 HTML 体积
    used_vehicle_types = {
        v.get("type") for v in data.get("vehicles", []) if v.get("type")
    }

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_dir = app_path("history")
    os.makedirs(history_dir, exist_ok=True)

    output_path = os.path.join(history_dir, f"{timestamp}.html")
    output_abs = os.path.abspath(output_path)
    
    # 读取模板
    template_path = app_path("templates", "accident_scene.html")
    if not os.path.exists(template_path):
        # 回退到根目录下的文件
        template_path = app_path("accident_scene.html")
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    # 注入数据
    script_tag = f"<script>\nconst accidentSettings = {settings_json};\n</script>"
    html_content = html_content.replace('<script src="settings.js"></script>', script_tag)
    html_content = inject_runtime_config(
        html_content,
        source_html_path=output_abs,
        save_measurements_url=save_measurements_url,
        saved_measurements=[],
        extra_runtime={
            "liabilityAnalysis": ai_analysis or None,
            "liabilityContext": liability_context or None,
            "liabilityAvailable": bool(ai_analysis),
            "playbackSpeedFactor": playback_speed_factor(),
        },
    )
    html_content = inject_scene_model_scripts(html_content, vehicle_types=used_vehicle_types)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    return output_abs
