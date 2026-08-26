"""Verify a packaged release: settings JSON present, YOLO weights present, API key absent."""

from __future__ import annotations

import json
import os
import sys


SKIP_SCAN_EXT = {
    ".pt",
    ".glb",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".dll",
    ".pyd",
    ".so",
    ".lib",
    ".exp",
    ".obj",
    ".whl",
    ".bin",
    ".pyd",
}

REQUIRED_CONFIG_FILES = (
    "ai_settings.json",
    "ai_experts.json",
    "ai_prompt.json",
    "measurement_port.json",
    "vehicle_model_defaults.json",
    "vehicle_model_settings.json",
    "animation_settings.json",
    "recognition_settings.json",
)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _source_api_key(src_ai_settings):
    if not os.path.isfile(src_ai_settings):
        return ""
    try:
        data = _read_json(src_ai_settings)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("deepseekApiKey", "") or "").strip()


def _ensure_default_settings(config_dir, downloads_dir):
    animation_path = os.path.join(config_dir, "animation_settings.json")
    if not os.path.isfile(animation_path):
        _write_json(animation_path, {"playbackSpeedFactor": 0.1})
        print("[OK] Wrote default animation_settings.json")

    recognition_path = os.path.join(config_dir, "recognition_settings.json")
    if not os.path.isfile(recognition_path):
        models = []
        if os.path.isdir(downloads_dir):
            for name in sorted(os.listdir(downloads_dir)):
                if name.lower().endswith(".pt"):
                    models.append(name)
        preferred = ""
        for name in models:
            if "obb" not in name.lower():
                preferred = name
                break
        if not preferred and models:
            preferred = models[0]
        _write_json(recognition_path, {"modelFile": preferred})
        print("[OK] Wrote default recognition_settings.json")


def _scan_for_key(root, key):
    if not key:
        return []
    needle = key.encode("utf-8")
    hits = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_SCAN_EXT:
                continue
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size <= 0 or size > 80 * 1024 * 1024:
                continue
            try:
                with open(path, "rb") as f:
                    blob = f.read()
            except OSError:
                continue
            if needle in blob:
                hits.append(os.path.relpath(path, root))
    return hits


def _verify_packed_knowledge(project_dir, app_out):
    src_dir = os.path.join(project_dir, "knowledge")
    dst_dir = os.path.join(app_out, "knowledge")
    failed = False
    if not os.path.isdir(dst_dir):
        print("[ERROR] Missing knowledge folder")
        return True

    for name in ("playbook.json", "index.json"):
        src_path = os.path.join(src_dir, name)
        dst_path = os.path.join(dst_dir, name)
        if os.path.isfile(src_path) and not os.path.isfile(dst_path):
            print(f"[ERROR] Missing knowledge\\{name}")
            failed = True
        elif os.path.isfile(dst_path):
            print(f"[OK] knowledge\\{name}")

    example_name = "ExampleTable.xlsx"
    src_example = os.path.join(src_dir, example_name)
    dst_example = os.path.join(dst_dir, example_name)
    if not os.path.isfile(src_example):
        print("[ERROR] Missing source knowledge\\ExampleTable.xlsx")
        failed = True
    elif not os.path.isfile(dst_example):
        print("[ERROR] Missing knowledge\\ExampleTable.xlsx")
        failed = True
    else:
        print("[OK] knowledge\\ExampleTable.xlsx")

    src_packs = os.path.join(src_dir, "packs")
    dst_packs = os.path.join(dst_dir, "packs")
    src_files = []
    if os.path.isdir(src_packs):
        src_files = [
            name
            for name in sorted(os.listdir(src_packs))
            if name.lower().endswith(".json")
        ]
    for name in src_files:
        dst_path = os.path.join(dst_packs, name)
        if not os.path.isfile(dst_path):
            print(f"[ERROR] Missing knowledge\\packs\\{name}")
            failed = True
        else:
            print(f"[OK] knowledge\\packs\\{name}")
    return failed


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: pack_verify_release.py <project_dir> <app_out>", file=sys.stderr)
        return 2

    project_dir = os.path.abspath(sys.argv[1])
    app_out = os.path.abspath(sys.argv[2])
    config_dir = os.path.join(app_out, "config")
    downloads_dir = os.path.join(app_out, "downloads")
    src_ai_settings = os.path.join(project_dir, "config", "ai_settings.json")
    packed_ai_settings = os.path.join(config_dir, "ai_settings.json")
    failed = False

    _ensure_default_settings(config_dir, downloads_dir)

    for name in REQUIRED_CONFIG_FILES:
        path = os.path.join(config_dir, name)
        if not os.path.isfile(path):
            print(f"[ERROR] Missing config\\{name}")
            failed = True
        else:
            print(f"[OK] config\\{name}")

    pt_files = []
    if os.path.isdir(downloads_dir):
        pt_files = [
            name
            for name in sorted(os.listdir(downloads_dir))
            if name.lower().endswith(".pt")
        ]
    if len(pt_files) < 2:
        print(f"[ERROR] Expected at least 2 YOLO .pt files in downloads, found {len(pt_files)}.")
        failed = True
    else:
        for name in pt_files:
            print(f"[OK] downloads\\{name}")

    if os.path.isfile(packed_ai_settings):
        try:
            packed = _read_json(packed_ai_settings)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ERROR] Failed to read packed ai_settings.json: {exc}")
            failed = True
            packed = {}
        key = str(packed.get("deepseekApiKey", "") or "").strip() if isinstance(packed, dict) else "invalid"
        if key:
            print("[ERROR] Packaged ai_settings.json still contains an API key.")
            failed = True
        else:
            print("[OK] Packaged ai_settings.json API key is empty.")
    else:
        print("[ERROR] Packaged ai_settings.json is missing.")
        failed = True

    source_key = _source_api_key(src_ai_settings)
    if source_key:
        hits = _scan_for_key(app_out, source_key)
        if hits:
            print("[ERROR] Source API key was found inside the release package:")
            for rel in hits:
                print(f"  - {rel}")
            failed = True
        else:
            print("[OK] Source API key was not found in the release package.")
    else:
        print("[OK] Source ai_settings.json has no API key to scan for.")

    knowledge_failed = _verify_packed_knowledge(project_dir, app_out)
    if knowledge_failed:
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
