# -*- coding: utf-8 -*-
"""Matplotlib charts for the offline accident analysis report."""

import os
import tempfile

os.environ.setdefault("MPLBACKEND", "Agg")

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simkai.ttf",
]


def _prepare_pyplot():
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    plt.rcParams["axes.unicode_minus"] = False
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                font_manager.fontManager.addfont(path)
                name = font_manager.FontProperties(fname=path).get_name()
                plt.rcParams["font.sans-serif"] = [name, "Microsoft YaHei", "SimHei", "SimSun"]
                break
            except Exception:
                continue
    else:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi"]
    return plt


def _save_fig(fig):
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    fig.savefig(handle.name, dpi=140, bbox_inches="tight", facecolor="white")
    return handle.name


def hour_line_chart(hour_counts):
    plt = _prepare_pyplot()
    hours = list(range(24))
    counts = [int(hour_counts[index]) if index < len(hour_counts) else 0 for index in hours]
    fig, axes = plt.subplots(figsize=(8.4, 3.6))
    axes.plot(hours, counts, color="#0f766e", marker="o", linewidth=2)
    for hour, count in zip(hours, counts):
        axes.annotate(
            str(count),
            (hour, count),
            textcoords="offset points",
            xytext=(0, 7),
            ha="center",
            fontsize=8,
            color="#0f172a",
        )
    axes.set_title("事故时间分布（24小时）")
    axes.set_xlabel("小时")
    axes.set_ylabel("事故起数")
    axes.set_xticks(hours)
    axes.set_xlim(-0.5, 23.5)
    axes.grid(True, axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    path = _save_fig(fig)
    plt.close(fig)
    return path


def pie_chart(items, title):
    plt = _prepare_pyplot()
    labels = [str(label) for label, _count in items]
    sizes = [max(0, int(count)) for _label, count in items]
    if not sizes or sum(sizes) <= 0:
        return None
    fig, axes = plt.subplots(figsize=(6.4, 4.4))
    wedges, _texts, autotexts = axes.pie(
        sizes,
        labels=None,
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.72,
    )
    for text in autotexts:
        text.set_fontsize(8)
    axes.legend(
        wedges,
        ["%s（%d）" % (label, count) for label, count in zip(labels, sizes)],
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=8,
        frameon=False,
    )
    axes.set_title(title)
    fig.tight_layout()
    path = _save_fig(fig)
    plt.close(fig)
    return path


def bar_chart(items, title):
    plt = _prepare_pyplot()
    labels = [str(label) for label, _count in items]
    values = [max(0, int(count)) for _label, count in items]
    if not values:
        return None
    width = max(6.4, min(10.5, 0.7 * len(labels) + 2.5))
    fig, axes = plt.subplots(figsize=(width, 4.0))
    bars = axes.bar(labels, values, color="#0f766e")
    axes.bar_label(bars, labels=[str(value) for value in values], padding=3, fontsize=8)
    axes.set_title(title)
    axes.set_ylabel("事故起数")
    axes.set_xlabel("")
    if len(labels) > 6:
        for tick in axes.get_xticklabels():
            tick.set_rotation(30)
            tick.set_ha("right")
    axes.grid(True, axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    path = _save_fig(fig)
    plt.close(fig)
    return path
