# -*- coding: utf-8 -*-
"""System fields for column mapping and report chapters."""

REQUIRED_FIELDS = [
    {
        "key": "road",
        "label": "道路",
        "meaning": "事故发生道路（路号、路名等）",
        "example": "路号",
        "section": "事故道路分布、多发路段",
    },
    {
        "key": "accident_type",
        "label": "类型",
        "meaning": "事故程序类型（一般程序 / 简易程序）",
        "example": "事故类型",
        "section": "事故整体情况（一般程序 / 简易程序起数）",
    },
    {
        "key": "time",
        "label": "时间",
        "meaning": "事故发生时间",
        "example": "事故发生时间",
        "section": "事故时间分布（24 小时折线图）",
    },
    {
        "key": "deaths",
        "label": "死亡人数",
        "meaning": "该起事故死亡人数",
        "example": "死亡人数",
        "section": "整体情况、道路分布、管辖分布",
    },
    {
        "key": "injuries",
        "label": "受伤人数",
        "meaning": "该起事故受伤人数",
        "example": "受伤人数",
        "section": "整体情况、道路分布、管辖分布",
    },
    {
        "key": "jurisdiction",
        "label": "管辖",
        "meaning": "处理单位 / 管理部门",
        "example": "管理部门",
        "section": "事故管辖分布情况",
    },
]

OPTIONAL_FIELDS = [
    {
        "key": "kilometer",
        "label": "公里数",
        "meaning": "事故桩号",
        "example": "公里数",
        "section": "多发路段定位精度",
    },
    {
        "key": "direction",
        "label": "方向",
        "meaning": "行驶方向或地点描述",
        "example": "事故地点",
        "section": "多发路段方向（提取「往X」）",
    },
    {
        "key": "cause",
        "label": "事故原因",
        "meaning": "认定原因",
        "example": "事故认定原因",
        "section": "原因饼图",
    },
    {
        "key": "weather",
        "label": "天气",
        "meaning": "事发天气",
        "example": "天气",
        "section": "天气柱状图",
    },
    {
        "key": "form",
        "label": "事故形态",
        "meaning": "碰撞形态等",
        "example": "事故形态",
        "section": "形态饼图",
    },
]

ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
REQUIRED_KEYS = [item["key"] for item in REQUIRED_FIELDS]
OPTIONAL_KEYS = [item["key"] for item in OPTIONAL_FIELDS]
FIELD_BY_KEY = {item["key"]: item for item in ALL_FIELDS}

DEFAULT_MAPPING = {
    "road": "路号",
    "accident_type": "事故类型",
    "time": "事故发生时间",
    "deaths": "死亡人数",
    "injuries": "受伤人数",
    "jurisdiction": "管理部门",
    "kilometer": "公里数",
    "direction": "事故地点",
    "cause": "事故认定原因",
    "weather": "天气",
    "form": "事故形态",
}

UNMAPPED_SENTINEL = ""


def field_tooltip(field, required):
    lines = [
        "含义：%s" % field["meaning"],
        "示例列名：%s" % field["example"],
        "影响章节：%s" % field["section"],
    ]
    if required:
        lines.append("开始分析前必须映射到表格中实际存在的列。")
    else:
        lines.append("不映射也能出报告，对应章节会写「未找到相关数据」或「无法分析」。")
    return "\n".join(lines)
