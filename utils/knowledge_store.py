# -*- coding: utf-8 -*-
"""Local knowledge layout: one shared playbook + multiple case packs."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from datetime import datetime

from utils.ai_settings import load_ai_settings
from utils.app_paths import app_path


KNOWLEDGE_DIRNAME = "knowledge"
PACKS_DIRNAME = "packs"
PLAYBOOK_FILENAME = "playbook.json"
INDEX_FILENAME = "index.json"
LEGACY_PACK_FILENAME = "accident_knowledge.json"
EXAMPLE_TABLE_FILENAME = "ExampleTable.xlsx"
INDEX_VERSION = 2
MAX_ACCIDENTS = 1500
MAX_SIMILAR_CASES = 8
MAX_PLAYBOOK_CHARS = 18000
MAX_BRIEF_CHARS = 160
MAX_PACK_NAME = 48
PACK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

_migrated = False


def knowledge_dir():
    path = app_path(KNOWLEDGE_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def packs_dir():
    path = os.path.join(knowledge_dir(), PACKS_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def playbook_path():
    return os.path.join(knowledge_dir(), PLAYBOOK_FILENAME)


def index_path():
    return os.path.join(knowledge_dir(), INDEX_FILENAME)


def example_table_path():
    return os.path.join(knowledge_dir(), EXAMPLE_TABLE_FILENAME)


def prepare_example_table_readonly_copy():
    src = example_table_path()
    if not os.path.isfile(src):
        raise ValueError("未找到精炼表格示例 ExampleTable.xlsx。")
    dest_dir = os.path.join(tempfile.gettempdir(), "accident_knowledge_example")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, EXAMPLE_TABLE_FILENAME)
    try:
        if os.path.isfile(dest):
            os.chmod(dest, stat.S_IWRITE)
            os.remove(dest)
    except OSError:
        dest = os.path.join(
            dest_dir,
            "ExampleTable_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
    shutil.copyfile(src, dest)
    os.chmod(dest, stat.S_IREAD)
    return dest


def pack_file_path(pack_id):
    return os.path.join(packs_dir(), f"{_safe_pack_id(pack_id)}.json")


def legacy_pack_path():
    return os.path.join(knowledge_dir(), LEGACY_PACK_FILENAME)


def has_ai_api_key(settings=None):
    data = settings if isinstance(settings, dict) else load_ai_settings()
    return bool(str(data.get("deepseekApiKey", "") or "").strip())


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def default_pack_name(source_file):
    name = os.path.splitext(os.path.basename(str(source_file or "")))[0]
    name = name.replace("_anonymized", "")
    if name.startswith("(原始)"):
        name = name[4:]
    name = name.strip() or "未命名精炼结果"
    return name[:MAX_PACK_NAME]


def playbook_is_populated(playbook=None):
    data = playbook if isinstance(playbook, dict) else load_playbook()
    if not isinstance(data, dict):
        return False
    return bool(data.get("scenarioPatterns") or data.get("pairingRules"))


def _safe_pack_id(pack_id):
    text = str(pack_id or "").strip().lower()
    if not PACK_ID_PATTERN.fullmatch(text):
        raise ValueError("无效的知识包编号。")
    return text


def _read_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path


def _empty_index():
    return {"version": INDEX_VERSION, "packs": []}


def _as_list(value):
    return value if isinstance(value, list) else []


def _trim_name(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:MAX_PACK_NAME]


def _summary_from_payload(payload, enabled=True):
    cards = payload.get("caseCards") if isinstance(payload.get("caseCards"), list) else []
    return {
        "id": str(payload.get("id") or ""),
        "name": _trim_name(payload.get("name")) or "未命名精炼结果",
        "enabled": bool(enabled),
        "sourceFile": str(payload.get("sourceFile", "") or ""),
        "sourceRows": int(payload.get("sourceRows") or 0),
        "usedRows": int(payload.get("usedRows") or len(cards)),
        "truncated": bool(payload.get("truncated")),
        "distilledAt": str(payload.get("distilledAt", "") or ""),
        "model": str(payload.get("model", "") or ""),
        "cardCount": len(cards),
    }


def _unique_name(name, exclude_id=None):
    base = _trim_name(name) or "未命名精炼结果"
    taken = set()
    for item in list_pack_summaries(migrate=False):
        if exclude_id and item.get("id") == exclude_id:
            continue
        taken.add(str(item.get("name") or ""))
    if base not in taken:
        return base
    index = 2
    while True:
        candidate = f"{base}（{index}）"[:MAX_PACK_NAME]
        if candidate not in taken:
            return candidate
        index += 1


def migrate_legacy_pack_if_needed():
    global _migrated
    if _migrated:
        return None
    _migrated = True
    packs_dir()
    legacy = legacy_pack_path()
    if not os.path.isfile(legacy):
        return None
    data = _read_json(legacy)
    if not data:
        return {"ok": False, "reason": "legacy-unreadable"}

    playbook = data.get("playbook") if isinstance(data.get("playbook"), dict) else {}
    cards = data.get("caseCards") if isinstance(data.get("caseCards"), list) else []
    result = {"ok": True, "playbook": False, "packId": "", "cardCount": 0}

    if playbook_is_populated(playbook) and not playbook_is_populated(load_playbook()):
        body = dict(playbook)
        body["version"] = INDEX_VERSION
        body["updatedAt"] = str(data.get("distilledAt") or now_iso())
        _atomic_write(playbook_path(), body)
        result["playbook"] = True

    source_file = str(data.get("sourceFile", "") or "")
    distilled_at = str(data.get("distilledAt", "") or "")
    already = any(
        item.get("sourceFile") == source_file and item.get("distilledAt") == distilled_at
        for item in list_pack_summaries(migrate=False)
    )
    if cards and not already:
        saved = add_case_pack(
            name=default_pack_name(source_file),
            source_file=source_file,
            source_rows=int(data.get("sourceRows") or len(cards)),
            used_rows=int(data.get("usedRows") or len(cards)),
            truncated=bool(data.get("truncated")),
            distilled_at=distilled_at,
            model=str(data.get("model", "") or ""),
            case_cards=cards,
            enabled=True,
            migrate=False,
        )
        result["packId"] = saved.get("id") or ""
        result["cardCount"] = len(cards)

    bak_path = legacy + ".migrated"
    try:
        os.replace(legacy, bak_path)
        result["archived"] = os.path.basename(bak_path)
    except OSError:
        result["archived"] = ""
    return result


def _ensure_layout(migrate=True):
    knowledge_dir()
    packs_dir()
    if migrate:
        migrate_legacy_pack_if_needed()


def load_playbook():
    _ensure_layout()
    data = _read_json(playbook_path())
    return data if isinstance(data, dict) else {}


def save_playbook(playbook):
    _ensure_layout()
    payload = dict(playbook or {})
    payload["version"] = INDEX_VERSION
    if not str(payload.get("updatedAt") or "").strip():
        payload["updatedAt"] = now_iso()
    return _atomic_write(playbook_path(), payload)


def delete_playbook():
    """Remove the shared playbook only. Case packs are left untouched."""
    _ensure_layout()
    path = playbook_path()
    tmp_path = path + ".tmp"
    removed = False
    for target in (path, tmp_path):
        if os.path.isfile(target):
            os.remove(target)
            removed = True
    return removed


def load_index():
    _ensure_layout()
    data = _read_json(index_path())
    if not data:
        return _empty_index()
    packs = data.get("packs")
    if not isinstance(packs, list):
        packs = []
    cleaned = []
    for item in packs:
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("id") or "").strip().lower()
        if not PACK_ID_PATTERN.fullmatch(pack_id):
            continue
        cleaned.append(
            {
                "id": pack_id,
                "name": _trim_name(item.get("name")) or "未命名精炼结果",
                "enabled": bool(item.get("enabled", True)),
                "sourceFile": str(item.get("sourceFile", "") or ""),
                "sourceRows": int(item.get("sourceRows") or 0),
                "usedRows": int(item.get("usedRows") or 0),
                "truncated": bool(item.get("truncated")),
                "distilledAt": str(item.get("distilledAt", "") or ""),
                "model": str(item.get("model", "") or ""),
                "cardCount": int(item.get("cardCount") or 0),
            }
        )
    data["packs"] = cleaned
    data["version"] = INDEX_VERSION
    return data


def save_index(index):
    _ensure_layout()
    payload = dict(index or _empty_index())
    payload["version"] = INDEX_VERSION
    if not isinstance(payload.get("packs"), list):
        payload["packs"] = []
    return _atomic_write(index_path(), payload)


def list_pack_summaries(migrate=True):
    if migrate:
        _ensure_layout()
    else:
        packs_dir()
    index = _read_json(index_path()) or _empty_index()
    items = []
    for item in _as_list(index.get("packs")):
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("id") or "").strip().lower()
        if not PACK_ID_PATTERN.fullmatch(pack_id):
            continue
        items.append(
            {
                "id": pack_id,
                "name": _trim_name(item.get("name")) or "未命名精炼结果",
                "enabled": bool(item.get("enabled", True)),
                "sourceFile": str(item.get("sourceFile", "") or ""),
                "sourceRows": int(item.get("sourceRows") or 0),
                "usedRows": int(item.get("usedRows") or 0),
                "truncated": bool(item.get("truncated")),
                "distilledAt": str(item.get("distilledAt", "") or ""),
                "model": str(item.get("model", "") or ""),
                "cardCount": int(item.get("cardCount") or 0),
            }
        )
    return items


def load_pack(pack_id):
    _ensure_layout()
    try:
        path = pack_file_path(pack_id)
    except ValueError:
        return None
    data = _read_json(path)
    if not data:
        return None
    cards = data.get("caseCards")
    if not isinstance(cards, list):
        cards = []
    data["caseCards"] = cards
    return data


def add_case_pack(
    name="",
    source_file="",
    source_rows=0,
    used_rows=0,
    truncated=False,
    distilled_at="",
    model="",
    case_cards=None,
    enabled=True,
    migrate=True,
):
    if migrate:
        _ensure_layout()
    else:
        packs_dir()
    pack_id = uuid.uuid4().hex
    cards = [item for item in _as_list(case_cards) if isinstance(item, dict)]
    display = _unique_name(name or default_pack_name(source_file))
    payload = {
        "version": INDEX_VERSION,
        "id": pack_id,
        "name": display,
        "sourceFile": str(source_file or ""),
        "sourceRows": int(source_rows or 0),
        "usedRows": int(used_rows or len(cards)),
        "truncated": bool(truncated),
        "distilledAt": str(distilled_at or now_iso()),
        "model": str(model or ""),
        "caseCards": cards,
    }
    _atomic_write(pack_file_path(pack_id), payload)
    index = load_index() if migrate else (_read_json(index_path()) or _empty_index())
    if not isinstance(index.get("packs"), list):
        index["packs"] = []
    index["packs"].append(_summary_from_payload(payload, enabled=enabled))
    save_index(index)
    return payload


def set_pack_enabled(pack_id, enabled):
    _ensure_layout()
    pack_id = _safe_pack_id(pack_id)
    index = load_index()
    found = False
    for item in index.get("packs") or []:
        if item.get("id") == pack_id:
            item["enabled"] = bool(enabled)
            found = True
            break
    if not found:
        raise ValueError("未找到该精炼结果。")
    save_index(index)
    return True


def rename_pack(pack_id, name):
    _ensure_layout()
    pack_id = _safe_pack_id(pack_id)
    display = _unique_name(name, exclude_id=pack_id)
    if not display:
        raise ValueError("名称不能为空。")
    index = load_index()
    found = False
    for item in index.get("packs") or []:
        if item.get("id") == pack_id:
            item["name"] = display
            found = True
            break
    if not found:
        raise ValueError("未找到该精炼结果。")
    save_index(index)
    pack = load_pack(pack_id)
    if pack:
        pack["name"] = display
        _atomic_write(pack_file_path(pack_id), pack)
    return display


def delete_pack(pack_id):
    """Delete one case pack. The shared playbook is left untouched."""
    _ensure_layout()
    pack_id = _safe_pack_id(pack_id)
    index = load_index()
    packs = [item for item in (index.get("packs") or []) if item.get("id") != pack_id]
    if len(packs) == len(index.get("packs") or []):
        raise ValueError("未找到该精炼结果。")
    index["packs"] = packs
    save_index(index)
    path = pack_file_path(pack_id)
    tmp_path = path + ".tmp"
    removed = False
    for target in (path, tmp_path):
        if os.path.isfile(target):
            os.remove(target)
            removed = True
    return removed


def load_enabled_case_cards():
    _ensure_layout()
    cards = []
    for summary in list_pack_summaries():
        if not summary.get("enabled"):
            continue
        pack = load_pack(summary["id"])
        if not pack:
            continue
        source_name = summary.get("name") or ""
        prefix = summary["id"][:8]
        for card in pack.get("caseCards") or []:
            if not isinstance(card, dict):
                continue
            item = dict(card)
            item["id"] = f"{prefix}-{card.get('id')}"
            item["sourceName"] = source_name
            cards.append(item)
    return cards


def knowledge_has_content():
    _ensure_layout()
    if playbook_is_populated():
        return True
    return bool(list_pack_summaries())


def load_knowledge_pack():
    """Compatibility view: shared playbook + enabled case cards."""
    _ensure_layout()
    playbook = load_playbook()
    cards = load_enabled_case_cards()
    enabled = [item for item in list_pack_summaries() if item.get("enabled")]
    if not playbook_is_populated(playbook) and not cards:
        return None
    names = [item.get("name") or item.get("sourceFile") or "" for item in enabled]
    return {
        "version": INDEX_VERSION,
        "playbook": playbook or {},
        "caseCards": cards,
        "usedRows": sum(int(item.get("usedRows") or 0) for item in enabled),
        "sourceRows": sum(int(item.get("sourceRows") or 0) for item in enabled),
        "sourceFile": "、".join(name for name in names if name),
        "distilledAt": str((playbook or {}).get("updatedAt") or ""),
        "truncated": any(bool(item.get("truncated")) for item in enabled),
        "enabledPackCount": len(enabled),
        "packCount": len(list_pack_summaries()),
    }


def knowledge_pack_exists():
    return knowledge_has_content()


def playbook_status_text():
    _ensure_layout()
    playbook = load_playbook()
    if not playbook_is_populated(playbook):
        return (
            "口径手册：尚未建立。首次精炼后会生成；之后只做去重合并，"
            "删除下方案件结果不会改手册。"
        )
    patterns = playbook.get("scenarioPatterns") if isinstance(playbook.get("scenarioPatterns"), list) else []
    updated = str(playbook.get("updatedAt") or "") or "未知时间"
    return (
        f"口径手册：已建立（场景 {len(patterns)} 条，更新于 {updated}）。"
        "全库共用这一份；再次精炼会合并进手册，删除案件结果不会回退手册。"
    )


def pack_status_text(pack=None):
    _ensure_layout()
    summaries = list_pack_summaries()
    enabled = [item for item in summaries if item.get("enabled")]
    playbook_line = playbook_status_text()
    if not summaries:
        return playbook_line + "\n案件结果：还没有精炼记录。选择 Excel 后会追加一条，不会覆盖旧结果。"
    enabled_cards = sum(int(item.get("cardCount") or 0) for item in enabled)
    return (
        f"{playbook_line}\n"
        f"案件结果：共 {len(summaries)} 份，已启用 {len(enabled)} 份、{enabled_cards} 张案件卡。"
        "分析时只检索已勾选的结果，并注入最多若干张相近案件。"
    )
