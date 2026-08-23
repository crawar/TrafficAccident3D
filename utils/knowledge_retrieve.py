# -*- coding: utf-8 -*-
"""Retrieve similar historical case cards for the current accident scene."""

from __future__ import annotations

from utils.knowledge_parse import detect_scenario_tags
from utils.knowledge_store import (
    MAX_SIMILAR_CASES,
    list_pack_summaries,
    load_enabled_case_cards,
    load_playbook,
    playbook_is_populated,
)


def _scene_text(liability_context):
    ctx = liability_context if isinstance(liability_context, dict) else {}
    parts = [str(ctx.get("userReportedAccidentBrief", "") or "")]
    for item in ctx.get("vehicleSummaries") or []:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("laneType", "") or ""))
        parts.extend(str(tag) for tag in (item.get("observationTags") or []))
        if item.get("likelyWrongWay"):
            parts.append("逆行")
    for item in ctx.get("markerSummaries") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("type", "") or ""))
    for item in ctx.get("motionPathSummaries") or []:
        if not isinstance(item, dict):
            continue
        for point in item.get("motionPath") or []:
            if isinstance(point, dict) and str(point.get("drive", "")).upper() == "F":
                parts.append("倒车")
                break
    if ctx.get("collisionSummaries"):
        parts.append("碰撞")
    return "\n".join(parts)


def _query_tags(liability_context):
    text = _scene_text(liability_context)
    tags = set(detect_scenario_tags(text))
    ctx = liability_context if isinstance(liability_context, dict) else {}
    vehicles = ctx.get("vehicleSummaries") or []
    markers = ctx.get("markerSummaries") or []
    motions = ctx.get("motionPathSummaries") or []
    if any(isinstance(v, dict) and v.get("likelyWrongWay") for v in vehicles):
        tags.add("逆行")
    if any(
        isinstance(v, dict) and str(v.get("laneType", "") or "") == "应急车道"
        for v in vehicles
    ):
        tags.add("应急车道")
    if any(
        isinstance(m, dict)
        and ("成年" in str(m.get("type", "") or "") or "行人" in str(m.get("type", "") or ""))
        for m in markers
    ):
        tags.add("行人")
    for item in motions:
        if not isinstance(item, dict):
            continue
        for point in item.get("motionPath") or []:
            if isinstance(point, dict) and str(point.get("drive", "")).upper() == "F":
                tags.add("倒车")
                break
    return tags, text


def _score_card(card, query_tags, query_text):
    card_tags = set(card.get("scenarioTags") or [])
    score = 3 * len(query_tags & card_tags)
    brief = str(card.get("brief", "") or "")
    blob = brief + " " + " ".join(card_tags)
    for tag in query_tags:
        if tag and tag in blob:
            score += 1
    for token in ("追尾", "倒车", "逆行", "应急", "行人", "变道", "醉酒", "超速"):
        if token in query_text and token in blob:
            score += 1
    return score


def retrieve_similar_cases(liability_context, pack=None, limit=MAX_SIMILAR_CASES):
    if isinstance(pack, dict) and isinstance(pack.get("caseCards"), list):
        cards = pack.get("caseCards") or []
    else:
        cards = load_enabled_case_cards()
    if not cards:
        return []
    query_tags, query_text = _query_tags(liability_context)
    ranked = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        score = _score_card(card, query_tags, query_text)
        if score <= 0:
            continue
        ranked.append((score, card))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    selected = []
    for score, card in ranked[: max(1, int(limit))]:
        selected.append(
            {
                "id": card.get("id"),
                "sourceName": card.get("sourceName") or "",
                "scenarioTags": card.get("scenarioTags") or [],
                "brief": card.get("brief") or "",
                "liabilitySummary": card.get("liabilitySummary") or "",
                "liabilities": card.get("liabilities") or [],
                "articles": card.get("articles") or [],
                "matchScore": score,
            }
        )
    return selected


def _playbook_for_attachment(playbook):
    data = dict(playbook or {})
    data.pop("version", None)
    data.pop("updatedAt", None)
    return data


def build_knowledge_attachment(liability_context):
    playbook = load_playbook()
    similar = retrieve_similar_cases(liability_context)
    if not playbook_is_populated(playbook) and not similar:
        return None
    enabled = [item for item in list_pack_summaries() if item.get("enabled")]
    return {
        "usageNote": str(
            (playbook or {}).get("usageNote")
            or (
                "historicalLiabilityKnowledge 来自本地历史认定精炼结果。"
                "只参考规律、配对、法条习惯和文风；不得套用历史案件具体事实。"
                "与当前 accidentData 冲突时，以当前现场图层为准。"
            )
        ),
        "sourceRows": sum(int(item.get("usedRows") or 0) for item in enabled),
        "enabledPackCount": len(enabled),
        "playbook": _playbook_for_attachment(playbook),
        "similarHistoricalCases": similar,
    }
