# -*- coding: utf-8 -*-
"""Aggregate mapped accident rows into report chapter data."""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time

from judgment_analysis.fields import OPTIONAL_KEYS

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日 %H时%M分",
    "%Y年%m月%d日%H时%M分",
    "%Y年%m月%d日",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d/%m/%Y %H:%M",
    "%H:%M:%S",
    "%H:%M",
)


def mapped_value(record, mapping, key):
    column = str((mapping or {}).get(key) or "").strip()
    if not column:
        return None
    if column not in record:
        return None
    return record[column]


def is_mapped(mapping, key):
    return bool(str((mapping or {}).get(key) or "").strip())


def _text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value).strip()


def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def to_number(value):
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return 0
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0
    try:
        number = float(match.group(0))
    except ValueError:
        return 0
    if number == int(number):
        return int(number)
    return number


def is_simple_procedure(value):
    return "简易" in _text(value)


def parse_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, time):
        today = date.today()
        return datetime.combine(today, value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        serial = float(value)
        if 20000 <= serial <= 80000:
            try:
                from datetime import timedelta

                base = datetime(1899, 12, 30)
                return base + timedelta(days=serial)
            except Exception:
                pass
    text = _text(value)
    if not text:
        return None
    try:
        import pandas as pd

        parsed = pd.to_datetime(text, errors="coerce")
        if parsed is not None and not pd.isna(parsed):
            return parsed.to_pydatetime()
    except Exception:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _km_int(value):
    if _is_blank(value):
        return None
    text = _text(value)
    text = (
        text.replace("公里", "")
        .replace("千米", "")
        .replace("K", "")
        .replace("k", "")
        .replace("+", ".")
        .strip()
    )
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return int(float(match.group(0)))
    except ValueError:
        return None


def normalize_road_name(value):
    name = _text(value)
    if not name:
        return ""
    if not name.startswith("G"):
        name = "G" + name
    return name


def extract_direction(value):
    text = _text(value)
    if not text:
        return ""
    index = text.find("往")
    if index < 0 or index + 1 >= len(text):
        return ""
    return "往" + text[index + 1]


def hotspot_location(road, kilometer, direction, has_kilometer):
    road_name = normalize_road_name(road)
    if not road_name:
        return ""
    km_value = _km_int(kilometer) if has_kilometer else None
    if km_value is not None:
        location = "%s-%d公里" % (road_name, km_value)
    else:
        location = road_name
    heading = extract_direction(direction)
    if heading:
        location += heading
    return location


def top_n_with_other(counter, limit=10):
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if len(items) <= limit:
        return items
    head = items[:limit]
    other_count = sum(count for _label, count in items[limit:])
    head.append(("其他", other_count))
    return head


def records_from_table(headers, rows):
    records = []
    width = len(headers)
    for raw in rows:
        record = {}
        for index, header in enumerate(headers):
            record[header] = raw[index] if index < len(raw) else ""
        if width and any(not _is_blank(record.get(header)) for header in headers):
            records.append(record)
    return records


def _group_table(records, mapping, name_key):
    buckets = defaultdict(lambda: {"count": 0, "deaths": 0, "injuries": 0})
    for record in records:
        name = _text(mapped_value(record, mapping, name_key)) or "（空白）"
        bucket = buckets[name]
        bucket["count"] += 1
        bucket["deaths"] += to_number(mapped_value(record, mapping, "deaths"))
        bucket["injuries"] += to_number(mapped_value(record, mapping, "injuries"))
    rows = []
    for name, bucket in buckets.items():
        rows.append(
            {
                "name": name,
                "count": bucket["count"],
                "deaths": bucket["deaths"],
                "injuries": bucket["injuries"],
            }
        )
    rows.sort(key=lambda item: (-item["count"], item["name"]))
    return rows


def _count_labels(records, mapping, key):
    counter = Counter()
    nonempty = 0
    for record in records:
        label = _text(mapped_value(record, mapping, key))
        if not label:
            continue
        nonempty += 1
        counter[label] += 1
    return counter, nonempty


def build_report_data(headers, rows, mapping):
    records = records_from_table(headers, rows)
    total = len(records)
    simple = 0
    general = 0
    deaths = 0
    injuries = 0
    for record in records:
        if is_simple_procedure(mapped_value(record, mapping, "accident_type")):
            simple += 1
        else:
            general += 1
        deaths += to_number(mapped_value(record, mapping, "deaths"))
        injuries += to_number(mapped_value(record, mapping, "injuries"))

    hour_counts = [0] * 24
    parsed_times = 0
    for record in records:
        parsed = parse_datetime(mapped_value(record, mapping, "time"))
        if parsed is None:
            continue
        hour_counts[parsed.hour] += 1
        parsed_times += 1
    time_ok = parsed_times > 0
    peak_hour = 0
    peak_count = 0
    if time_ok:
        peak_count = max(hour_counts)
        peak_hour = hour_counts.index(peak_count)

    has_km = is_mapped(mapping, "kilometer")
    hotspot_counter = Counter()
    for record in records:
        location = hotspot_location(
            mapped_value(record, mapping, "road"),
            mapped_value(record, mapping, "kilometer") if has_km else None,
            mapped_value(record, mapping, "direction"),
            has_km,
        )
        if location:
            hotspot_counter[location] += 1
    hotspot_rows = [
        {"location": name, "count": count}
        for name, count in sorted(
            hotspot_counter.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]

    optional = {}
    for key in OPTIONAL_KEYS:
        mapped = is_mapped(mapping, key)
        counter, nonempty = _count_labels(records, mapping, key) if mapped else (Counter(), 0)
        items = top_n_with_other(counter) if nonempty else []
        top_label = items[0][0] if items else ""
        top_count = items[0][1] if items else 0
        top_pct = (100.0 * top_count / nonempty) if nonempty else 0.0
        optional[key] = {
            "mapped": mapped,
            "nonempty": nonempty,
            "items": items,
            "top_label": top_label,
            "top_count": top_count,
            "top_pct": top_pct,
        }

    return {
        "total": total,
        "simple": simple,
        "general": general,
        "deaths": deaths,
        "injuries": injuries,
        "road_rows": _group_table(records, mapping, "road"),
        "jurisdiction_rows": _group_table(records, mapping, "jurisdiction"),
        "time_ok": time_ok,
        "parsed_times": parsed_times,
        "hour_counts": hour_counts,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "hotspot_rows": hotspot_rows,
        "optional": optional,
    }
