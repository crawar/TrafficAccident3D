# -*- coding: utf-8 -*-
"""One-shot distillation: Excel -> case cards + compact liability playbook."""

from __future__ import annotations

import json
import os
from urllib import error, request

from utils.ai_settings import ai_enabled, ai_request_config, load_ai_settings, sanitize_ai_settings
from utils.knowledge_parse import read_accident_excel_rows, rows_to_case_cards
from utils.knowledge_store import (
    MAX_ACCIDENTS,
    MAX_PLAYBOOK_CHARS,
    add_case_pack,
    default_pack_name,
    load_playbook,
    now_iso,
    playbook_is_populated,
    save_playbook,
)


BATCH_SIZE = 70
DEFAULT_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-pro"
REFINE_TIMEOUT_SEC = 180


class KnowledgeRefineCancelled(Exception):
    """Raised when the caller stops a running refine job."""


def _emit(progress_cb, percent, message):
    if callable(progress_cb):
        progress_cb(max(0, min(100, int(percent))), str(message or ""))


def _extract_json_content(content):
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _post_json(ai_settings, messages, timeout_sec=REFINE_TIMEOUT_SEC):
    safe = sanitize_ai_settings(ai_settings)
    cfg = ai_request_config(safe)
    token = str(safe.get("deepseekApiKey", "") or "").strip()
    if not token:
        raise ValueError("未配置 DeepSeek API 密钥，无法精炼知识库。")
    url = cfg.get("requestUrl") or DEFAULT_CHAT_URL
    model = cfg.get("model") or DEFAULT_MODEL
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=int(timeout_sec)) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise ValueError(f"知识库精炼接口失败（HTTP {exc.code}）：{detail[:400]}") from exc
    except error.URLError as exc:
        raise ValueError(f"知识库精炼网络失败：{exc}") from exc
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("知识库精炼返回格式无效。") from exc
    parsed = json.loads(_extract_json_content(content))
    if not isinstance(parsed, dict):
        raise ValueError("知识库精炼未返回 JSON 对象。")
    return parsed, model


def _card_for_prompt(card):
    return {
        "id": card.get("id"),
        "scenarioTags": card.get("scenarioTags") or [],
        "brief": card.get("brief") or "",
        "liabilitySummary": card.get("liabilitySummary") or "",
        "liabilities": card.get("liabilities") or [],
        "articles": card.get("articles") or [],
    }


def _empty_playbook():
    return {
        "scenarioPatterns": [],
        "pairingRules": [],
        "legalAnchors": [],
        "exceptions": [],
        "expertStyleHints": {},
        "vocabulary": {
            "全部责任": "全责",
            "主要责任": "主责",
            "次要责任": "次责",
            "同等责任": "同责",
            "无责任": "无责",
            "无责": "无责",
        },
        "usageNote": (
            "只参考规律、配对和文风。不得套用历史案件的具体车辆、地点或伤亡。"
            "与当前现场图层冲突时，以当前现场为准。"
        ),
    }


def _as_list(value):
    return value if isinstance(value, list) else []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _trim_text(value, limit):
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _normalize_playbook(raw):
    data = _as_dict(raw)
    playbook = _empty_playbook()
    patterns = []
    for item in _as_list(data.get("scenarioPatterns")):
        if not isinstance(item, dict):
            continue
        name = _trim_text(item.get("name") or item.get("id"), 24)
        if not name:
            continue
        patterns.append(
            {
                "name": name,
                "triggers": [
                    _trim_text(x, 40)
                    for x in _as_list(item.get("triggers"))
                    if str(x or "").strip()
                ][:6],
                "typicalPairing": _trim_text(
                    item.get("typicalPairing") or item.get("typicalLiability"), 80
                ),
                "exceptions": [
                    _trim_text(x, 60)
                    for x in _as_list(item.get("exceptions"))
                    if str(x or "").strip()
                ][:5],
            }
        )
        if len(patterns) >= 18:
            break
    playbook["scenarioPatterns"] = patterns
    playbook["pairingRules"] = [
        _trim_text(item, 80)
        for item in _as_list(data.get("pairingRules"))
        if str(item or "").strip()
    ][:12]
    anchors = []
    for item in _as_list(data.get("legalAnchors")):
        if isinstance(item, dict):
            article = _trim_text(item.get("article"), 40)
            typical = _trim_text(item.get("typicalUse") or item.get("use"), 60)
            if article:
                anchors.append({"article": article, "typicalUse": typical})
        elif str(item or "").strip():
            anchors.append({"article": _trim_text(item, 40), "typicalUse": ""})
        if len(anchors) >= 16:
            break
    playbook["legalAnchors"] = anchors
    playbook["exceptions"] = [
        _trim_text(item, 80)
        for item in _as_list(data.get("exceptions"))
        if str(item or "").strip()
    ][:10]
    hints = _as_dict(data.get("expertStyleHints"))
    playbook["expertStyleHints"] = {
        str(key): _trim_text(value, 160)
        for key, value in hints.items()
        if str(value or "").strip()
    }
    vocab = _as_dict(data.get("vocabulary"))
    if vocab:
        merged = dict(playbook["vocabulary"])
        for key, value in vocab.items():
            if str(key or "").strip() and str(value or "").strip():
                merged[str(key).strip()] = _trim_text(value, 12)
        playbook["vocabulary"] = merged
    note = _trim_text(data.get("usageNote"), 180)
    if note:
        playbook["usageNote"] = note
    return playbook


def _cap_playbook(playbook):
    data = _normalize_playbook(playbook)
    encoded = json.dumps(data, ensure_ascii=False)
    if len(encoded) <= MAX_PLAYBOOK_CHARS:
        return data
    data["exceptions"] = data.get("exceptions", [])[:4]
    data["legalAnchors"] = data.get("legalAnchors", [])[:8]
    data["scenarioPatterns"] = data.get("scenarioPatterns", [])[:10]
    encoded = json.dumps(data, ensure_ascii=False)
    if len(encoded) <= MAX_PLAYBOOK_CHARS:
        return data
    data["expertStyleHints"] = {
        key: value[:80]
        for key, value in list(data.get("expertStyleHints", {}).items())[:4]
    }
    return data


def _chunk(items, size):
    block = []
    for item in items:
        block.append(item)
        if len(block) >= size:
            yield block
            block = []
    if block:
        yield block


def _batch_messages(cards, batch_index, batch_count):
    schema = {
        "scenarioPatterns": [
            {
                "name": "场景名",
                "triggers": ["可观察触发条件"],
                "typicalPairing": "例如后车主要责任、前车次要或无责",
                "exceptions": ["例外"],
            }
        ],
        "pairingRules": ["主要责任必须配对次要责任等"],
        "legalAnchors": [{"article": "法条名", "typicalUse": "对应过错"}],
        "exceptions": ["需要改口的情形"],
        "expertStyleHints": {
            "案件侦办": "口吻要点",
            "秩序管理": "口吻要点",
            "护路联防": "口吻要点",
            "指挥调度": "口吻要点",
        },
    }
    user = {
        "task": (
            f"这是第 {batch_index}/{batch_count} 批高速公路事故历史认定摘要。"
            "请归纳责任划分规律，不要复述任何具体案件事实、姓名、车牌或地点。"
        ),
        "requirements": [
            "只返回 JSON 对象。",
            "规律必须能映射到当前系统枚举：全责/主责/次责/同责/无责。",
            "历史文书常用主要责任/次要责任/同等责任/全部责任，请在 vocabulary 中对照。",
            "不要输出东南西北等绝对方向。",
            "scenarioPatterns 控制在 12 条以内，文字简短。",
        ],
        "responseSchema": schema,
        "cases": [_card_for_prompt(card) for card in cards],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是高速公路交通事故责任认定规律抽取器。"
                "根据历史认定摘要提炼可复用口径，禁止抄写个案细节。"
                "只输出 JSON。"
            ),
        },
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _merge_messages(partials):
    user = {
        "task": "合并多批责任规律，去重并压缩成一份可注入大模型的口径手册。",
        "requirements": [
            "只返回 JSON 对象，字段与各批相同。",
            "保留高频、可执行的规律，删除重复和过细个案。",
            "pairingRules 必须覆盖：全责配无责；主责配次责；同责至少两方。",
            "压缩总长度，避免长段落。",
        ],
        "partialPlaybooks": partials,
    }
    return [
        {
            "role": "system",
            "content": "你负责合并事故责任口径手册。只输出压缩后的 JSON。",
        },
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _accumulate_playbook_messages(existing, incoming):
    user = {
        "task": (
            "将 incomingPlaybook 合并进 existingPlaybook。"
            "这是全库唯一的口径手册：只改写、去重、补例外，不要把手册变厚。"
        ),
        "requirements": [
            "只返回 JSON 对象，字段与 existingPlaybook 相同。",
            "同名 scenarioPatterns 必须覆盖更新，不得再新增一条同名场景。",
            "只有 existing 里完全没有的新形态才允许新增场景，且总数不超过 18 条。",
            "pairingRules、vocabulary、legalAnchors 按含义去重；条数原则上不增加。",
            "pairingRules 必须覆盖：全责配无责；主责配次责；同责至少两方。",
            "禁止复述案件事实、姓名、车牌或地点。",
            "压缩总长度，避免长段落。",
        ],
        "existingPlaybook": existing,
        "incomingPlaybook": incoming,
    }
    return [
        {
            "role": "system",
            "content": (
                "你负责维护一份全局事故责任口径手册。"
                "合并时以改写和去重为主，禁止把手册越写越长。"
                "只输出压缩后的 JSON。"
            ),
        },
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _playbook_for_merge(playbook):
    data = _normalize_playbook(playbook)
    data.pop("usageNote", None)
    return data


def refine_knowledge_from_excel(
    xlsx_path,
    ai_settings=None,
    progress_cb=None,
    should_cancel=None,
):
    def _check_cancel():
        if callable(should_cancel) and should_cancel():
            raise KnowledgeRefineCancelled("已取消知识库精炼。")

    settings = ai_settings if isinstance(ai_settings, dict) else load_ai_settings()
    if not ai_enabled(settings):
        raise ValueError("未启用 AI，无法精炼知识库。")
    _check_cancel()
    _emit(progress_cb, 2, "正在读取 Excel…")
    rows = read_accident_excel_rows(xlsx_path)
    _check_cancel()
    _emit(progress_cb, 8, "正在抽取案件卡…")
    parsed = rows_to_case_cards(rows, max_accidents=MAX_ACCIDENTS)
    cards = parsed["caseCards"]
    batches = list(_chunk(cards, BATCH_SIZE))
    batch_count = max(1, len(batches))
    partials = []
    model_name = ""
    for index, batch in enumerate(batches, start=1):
        _check_cancel()
        percent = 12 + int(70 * (index - 1) / batch_count)
        _emit(
            progress_cb,
            percent,
            f"正在归纳第 {index}/{batch_count} 批口径（{len(batch)} 起）…",
        )
        parsed_batch, model_name = _post_json(
            settings,
            _batch_messages(batch, index, batch_count),
        )
        partials.append(_normalize_playbook(parsed_batch))
    _check_cancel()
    _emit(progress_cb, 86, "正在合并本表口径…")
    if len(partials) == 1:
        incoming = _cap_playbook(partials[0])
    else:
        merged, model_name = _post_json(settings, _merge_messages(partials))
        incoming = _cap_playbook(merged)
    existing = load_playbook()
    playbook_merged = True
    playbook_merge_error = ""
    if playbook_is_populated(existing):
        _check_cancel()
        _emit(progress_cb, 90, "正在把新口径合并进全局手册…")
        try:
            merged_global, model_name = _post_json(
                settings,
                _accumulate_playbook_messages(
                    _playbook_for_merge(existing),
                    _playbook_for_merge(incoming),
                ),
            )
            incoming = _cap_playbook(merged_global)
        except Exception as exc:
            playbook_merged = False
            playbook_merge_error = str(exc)
    _check_cancel()
    _emit(progress_cb, 96, "正在保存精炼结果…")
    if playbook_merged:
        incoming["updatedAt"] = now_iso()
        save_playbook(incoming)
    source_file = os.path.basename(str(xlsx_path or ""))
    pack = add_case_pack(
        name=default_pack_name(source_file),
        source_file=source_file,
        source_rows=parsed["sourceRows"],
        used_rows=parsed["usedRows"],
        truncated=parsed["truncated"],
        distilled_at=now_iso(),
        model=model_name,
        case_cards=cards,
        enabled=True,
    )
    pack["playbookMerged"] = playbook_merged
    pack["playbookMergeError"] = playbook_merge_error
    _emit(progress_cb, 100, "知识库精炼完成。")
    return pack
