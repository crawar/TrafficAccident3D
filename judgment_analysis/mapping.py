# -*- coding: utf-8 -*-
"""Persist header-row and column mapping as JSON next to the runnable app."""

import json
import os

from judgment_analysis.fields import ALL_FIELDS, DEFAULT_MAPPING, UNMAPPED_SENTINEL
from utils.app_paths import app_path

MAPPING_FILENAME = "column_mapping.json"
HEADER_ROW_KEY = "headerRow"
HEADER_LABELS_KEY = "headerLabels"
COLUMNS_KEY = "columns"


def mapping_path():
    return app_path("config", MAPPING_FILENAME)


def _clean_columns(raw):
    cleaned = {}
    source = raw if isinstance(raw, dict) else {}
    for field in ALL_FIELDS:
        key = field["key"]
        value = source.get(key, DEFAULT_MAPPING.get(key, UNMAPPED_SENTINEL))
        cleaned[key] = str(value or "").strip()
    return cleaned


def _parse_header_row(value):
    if value is None or value == "":
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return index


def _parse_header_labels(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def empty_state():
    return {
        "columns": _clean_columns(DEFAULT_MAPPING),
        "header_row_index": None,
        "header_labels": [],
    }


def _parse_state(parsed):
    state = empty_state()
    if not isinstance(parsed, dict):
        return state
    if isinstance(parsed.get(COLUMNS_KEY), dict):
        state["columns"] = _clean_columns(parsed.get(COLUMNS_KEY))
        state["header_row_index"] = _parse_header_row(parsed.get(HEADER_ROW_KEY))
        state["header_labels"] = _parse_header_labels(parsed.get(HEADER_LABELS_KEY))
        return state
    state["columns"] = _clean_columns(parsed)
    state["header_row_index"] = _parse_header_row(parsed.get(HEADER_ROW_KEY))
    state["header_labels"] = _parse_header_labels(parsed.get(HEADER_LABELS_KEY))
    return state


def load_mapping_state():
    path = mapping_path()
    if not os.path.isfile(path):
        return empty_state()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, ValueError, TypeError):
        return empty_state()
    return _parse_state(parsed)


def save_mapping_state(columns, header_row_index=None, header_labels=None):
    payload = {
        HEADER_ROW_KEY: header_row_index,
        HEADER_LABELS_KEY: list(header_labels or []),
        COLUMNS_KEY: _clean_columns(columns),
    }
    path = mapping_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {
        "columns": payload[COLUMNS_KEY],
        "header_row_index": header_row_index,
        "header_labels": payload[HEADER_LABELS_KEY],
    }


def load_mapping():
    return load_mapping_state()["columns"]


def save_mapping(mapping, header_row_index=None, header_labels=None):
    current = load_mapping_state()
    if header_row_index is None:
        header_row_index = current["header_row_index"]
    if header_labels is None:
        header_labels = current["header_labels"]
    saved = save_mapping_state(mapping, header_row_index, header_labels)
    return saved["columns"]


def missing_required(mapping, headers):
    from judgment_analysis.fields import REQUIRED_FIELDS

    header_set = set(headers or [])
    missing = []
    for field in REQUIRED_FIELDS:
        column = str((mapping or {}).get(field["key"]) or "").strip()
        if not column or column not in header_set:
            missing.append(field["label"])
    return missing
