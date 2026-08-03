#!/usr/bin/env python3
"""Warn before Codex compacts a conversation."""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, json.JSONDecodeError):
        payload = {}
    trigger = payload.get("trigger", "auto") if isinstance(payload, dict) else "auto"
    message = (
        "Shrinkydink context warning: Codex is about to compact this session "
        f"({trigger}). Checkpoint the objective, decisions, changed files, tests, "
        "unresolved items, and next command. Consider starting a new session when "
        "the current task has a clean boundary."
    )
    json.dump({"systemMessage": message}, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
