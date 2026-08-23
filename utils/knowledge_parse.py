# -*- coding: utf-8 -*-
"""Parse an accident Excel (column A process, column B determination) into case cards."""

from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET

from utils.knowledge_store import MAX_ACCIDENTS, MAX_BRIEF_CHARS


SSML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"m": SSML}

SCENARIO_RULES = (
    ("追尾", ("追尾", "同向刮碰后部", "撞击前车")),
    ("变道", ("变道", "变更车道", "借道")),
    ("倒车", ("倒车",)),
    ("逆行", ("逆行", "逆向", "反向停")),
    ("应急车道", ("应急车道", "应急停", "占用应急")),
    ("行人", ("行人", "上高速", "步行进入")),
    ("醉酒", ("醉酒", "酒后", "血液酒精")),
    ("超速", ("超速", "超过限速", "未降低行驶速度")),
    ("疲劳", ("疲劳", "未确保安全")),
    ("失控", ("失控", "打滑", "爆胎")),
    ("护栏", ("护栏", "中央分隔", "碰撞路产")),
    ("占用", ("占用", "违法停车", "停车")),
    ("接打手机", ("手持电话", "接听", "观看", "低头")),
)

LIABILITY_PATTERN = re.compile(
    r"(全部责任|主要责任|次要责任|同等责任|无责任|无责)"
)
ARTICLE_PATTERN = re.compile(
    r"《[^》]{2,40}》\s*第[零一二三四五六七八九十百千0-9]+条(?:第[零一二三四五六七八九十0-9]+款)?"
)
BARE_ARTICLE_PATTERN = re.compile(
    r"(?:道路交通安全法(?:实施条例)?|道路交通事故处理程序规定)"
    r"第[零一二三四五六七八九十百千0-9]+条(?:第[零一二三四五六七八九十0-9]+款)?"
)
HEADER_HINTS = ("事故", "认定", "简要", "经过", "基本情况")
PLATE_PATTERN = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]?\*{2,}")
DATE_PATTERN = re.compile(
    r"[0-9０-９*]{2,4}\s*年|[0-9０-９*]{1,2}\s*月|[0-9０-９*]{1,2}\s*[日号]"
    r"|[0-9０-９*]{1,2}\s*[时点:：]|[0-9０-９*]{1,2}\s*分"
)
DIRECTION_PATTERN = re.compile(
    r"[东南西北]{1,2}[^，。；\n]{0,8}[往向朝][东南西北]{1,2}"
    r"|[东南西北]{1,2}向[东南西北]{1,2}"
    r"|由南往北|由北往南|由东往西|由西往东"
)
NAME_PATTERN = re.compile(r"[\u4e00-\u9fff]某[\u4e00-\u9fff]?")
SPACE_PATTERN = re.compile(r"[ \t\r\f\v]+")


def _col_row(ref):
    match = re.match(r"([A-Z]+)(\d+)", str(ref or ""))
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def _cell_text(cell, shared):
    cell_type = cell.get("t")
    if cell_type == "s":
        value = cell.find("m:v", NS)
        if value is None or value.text is None:
            return ""
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(".//m:t", NS)]
        return "".join(texts)
    value = cell.find("m:v", NS)
    return value.text or "" if value is not None else ""


def _load_shared_strings(zip_file):
    try:
        root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.findall("m:si", NS):
        texts = [node.text or "" for node in item.findall(".//m:t", NS)]
        strings.append("".join(texts))
    return strings


def _first_sheet_path(zip_file):
    try:
        root = ET.fromstring(zip_file.read("xl/workbook.xml"))
    except KeyError:
        return "xl/worksheets/sheet1.xml"
    sheets = root.findall("m:sheets/m:sheet", NS)
    if not sheets:
        return "xl/worksheets/sheet1.xml"
    rels_root = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rels = {}
    for rel in rels_root:
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if rel_id and target:
            rels[rel_id] = target.replace("\\", "/")
    rel_id = sheets[0].get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    target = rels.get(rel_id, "worksheets/sheet1.xml")
    if not target.startswith("xl/"):
        target = "xl/" + target.lstrip("/")
    return target


def read_accident_excel_rows(xlsx_path):
    if not os.path.isfile(xlsx_path):
        raise ValueError("所选 Excel 不存在。")
    if not str(xlsx_path).lower().endswith(".xlsx"):
        raise ValueError("请选择 .xlsx 格式的事故表格。")
    rows = []
    with zipfile.ZipFile(xlsx_path) as zip_file:
        shared = _load_shared_strings(zip_file)
        sheet_path = _first_sheet_path(zip_file)
        root = ET.fromstring(zip_file.read(sheet_path))
        by_row = {}
        for row in root.findall("m:sheetData/m:row", NS):
            for cell in row.findall("m:c", NS):
                ref = cell.get("r")
                if not ref:
                    continue
                col, index = _col_row(ref)
                if col not in {"A", "B"} or index <= 0:
                    continue
                by_row.setdefault(index, {})[col] = _cell_text(cell, shared)
        for index in sorted(by_row):
            item = by_row[index]
            rows.append(
                {
                    "row": index,
                    "process": str(item.get("A", "") or "").strip(),
                    "determination": str(item.get("B", "") or "").strip(),
                }
            )
    if not rows:
        raise ValueError("Excel 中没有可读的 A/B 列内容。")
    return rows


def _looks_like_header(process, determination):
    blob = process + determination
    if not blob:
        return True
    if any(hint in process for hint in HEADER_HINTS) and len(process) <= 24:
        return True
    if any(hint in determination for hint in HEADER_HINTS) and len(determination) <= 24:
        return True
    return False


def sanitize_case_text(text, limit=MAX_BRIEF_CHARS):
    raw = str(text or "")
    raw = DATE_PATTERN.sub("", raw)
    raw = DIRECTION_PATTERN.sub("", raw)
    raw = NAME_PATTERN.sub("某", raw)
    raw = PLATE_PATTERN.sub("***", raw)
    raw = raw.replace("****", "***")
    raw = SPACE_PATTERN.sub(" ", raw)
    raw = re.sub(r"\n+", " ", raw)
    raw = re.sub(r"[，,]{2,}", "，", raw)
    raw = re.sub(r"^许[，,、]?\s*", "", raw)
    raw = raw.strip(" ，、；;。")
    if len(raw) > limit:
        raw = raw[: limit - 1].rstrip() + "…"
    return raw


def detect_scenario_tags(*texts):
    blob = "\n".join(str(item or "") for item in texts)
    tags = []
    for name, keywords in SCENARIO_RULES:
        if any(keyword in blob for keyword in keywords):
            tags.append(name)
    return tags


def extract_liabilities(determination):
    found = LIABILITY_PATTERN.findall(str(determination or ""))
    mapped = []
    for item in found:
        if item in {"无责", "无责任"}:
            mapped.append("无责")
        else:
            mapped.append(item)
    return mapped


def extract_articles(determination):
    text = str(determination or "")
    found = ARTICLE_PATTERN.findall(text)
    found.extend(BARE_ARTICLE_PATTERN.findall(text))
    unique = []
    seen = set()
    for item in found:
        key = str(item).replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
        if len(unique) >= 6:
            break
    return unique


def _compact_liability_summary(labels):
    if not labels:
        return ""
    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{name}{counts[name]}方" for name in counts]
    return "、".join(parts)


def build_case_card(row_index, process, determination, source_index):
    tags = detect_scenario_tags(process, determination)
    labels = extract_liabilities(determination)
    articles = extract_articles(determination)
    brief = sanitize_case_text(process, MAX_BRIEF_CHARS)
    if not brief:
        return None
    return {
        "id": source_index,
        "excelRow": row_index,
        "scenarioTags": tags,
        "brief": brief,
        "liabilities": labels[:8],
        "liabilitySummary": _compact_liability_summary(labels),
        "articles": articles,
    }


def rows_to_case_cards(rows, max_accidents=MAX_ACCIDENTS):
    data_rows = []
    for item in rows:
        process = str(item.get("process", "") or "").strip()
        determination = str(item.get("determination", "") or "").strip()
        if not process and not determination:
            continue
        data_rows.append(item)
    if data_rows and _looks_like_header(
        data_rows[0].get("process", ""), data_rows[0].get("determination", "")
    ):
        data_rows = data_rows[1:]
    source_rows = len(data_rows)
    truncated = source_rows > int(max_accidents)
    used_rows = data_rows[: int(max_accidents)]
    cards = []
    for offset, item in enumerate(used_rows, start=1):
        card = build_case_card(
            item.get("row"),
            item.get("process", ""),
            item.get("determination", ""),
            offset,
        )
        if card:
            cards.append(card)
    if not cards:
        raise ValueError("没有解析出有效事故经过，请确认 A 列为事故经过、B 列为责任认定。")
    return {
        "sourceRows": source_rows,
        "usedRows": len(used_rows),
        "truncated": truncated,
        "caseCards": cards,
    }
