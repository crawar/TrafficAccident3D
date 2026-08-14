import json
import os

from utils.app_paths import app_path


PROMPT_PATH = app_path("config", "ai_prompt.json")


def load_ai_prompt():
    """读取用户追加的责任分析约束（追加在 requirements 末尾）。未设置时返回空字符串。"""
    if not os.path.isfile(PROMPT_PATH):
        return ""
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("appendRequirement", "") or "").strip()
    return ""


def save_ai_prompt(text):
    """保存用户追加约束到 config/ai_prompt.json，返回清洗后的文本。"""
    safe_text = str(text or "").strip()
    os.makedirs(os.path.dirname(PROMPT_PATH), exist_ok=True)
    with open(PROMPT_PATH, "w", encoding="utf-8") as f:
        json.dump({"appendRequirement": safe_text}, f, ensure_ascii=False, indent=2)
    return safe_text
