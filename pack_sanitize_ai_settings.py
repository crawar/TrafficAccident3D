"""Write a packaging copy of ai_settings.json with the API key cleared."""

from __future__ import annotations

import json
import os
import sys


DEFAULTS = {
    "deepseekApiKey": "",
    "enableLiabilityAnalysis": False,
    "regenerateLiabilityEachTime": True,
    "requestUrl": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-v4-pro",
    "reasoningEffort": "high",
    "thinkingMode": "enabled",
    "temperature": 0.1,
    "requestTimeoutSec": 120,
}


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: pack_sanitize_ai_settings.py <src> <dst>", file=sys.stderr)
        return 2

    src = sys.argv[1]
    dst = sys.argv[2]
    data = dict(DEFAULTS)

    if os.path.isfile(src):
        try:
            with open(src, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[WARN] Failed to read source ai_settings.json: {exc}", file=sys.stderr)

    data["deepseekApiKey"] = ""
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[OK] Wrote sanitized ai_settings.json -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
