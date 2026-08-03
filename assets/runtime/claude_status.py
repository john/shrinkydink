#!/usr/bin/env python3
"""Claude Code status-line renderer with a configurable context warning."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLD = 70


def root_from_script() -> Path:
    installed_root = Path(__file__).resolve().parents[2]
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return installed_root


def load_config(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / ".shrinkydink.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except (OSError, json.JSONDecodeError):
        return 0

    config = load_config(root_from_script())
    try:
        threshold = int(config.get("context_warning_percent", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    threshold = max(1, min(99, threshold))

    window = payload.get("context_window") or {}
    used = window.get("used_percentage") if isinstance(window, dict) else None
    model = payload.get("model") or {}
    model_name = model.get("display_name") if isinstance(model, dict) else None

    if used is None:
        label = f"{model_name} | context: --" if model_name else "context: --"
        print(label)
        return 0

    try:
        used_value = float(used)
    except (TypeError, ValueError):
        return 0

    prefix = f"{model_name} | " if model_name else ""
    if used_value >= threshold:
        print(
            f"{prefix}CONTEXT {used_value:.0f}% - checkpoint work; consider a new session"
        )
    else:
        print(f"{prefix}context {used_value:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
