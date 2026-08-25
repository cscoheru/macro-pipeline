#!/usr/bin/env python3
"""Block a second asr-transcribe / lock-clobber. Cursor + Claude Code hooks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc_autopilot_inspect import list_asr_pids  # noqa: E402


def extract_command(payload: dict) -> str:
    if isinstance(payload.get("command"), str):
        return payload["command"]
    for key in ("tool_input", "arguments"):
        inner = payload.get(key)
        if isinstance(inner, dict) and isinstance(inner.get("command"), str):
            return inner["command"]
    return ""


def should_block(command: str, pids: list[int]) -> str | None:
    cmd = command or ""
    if "cc_autopilot_inspect.py" in cmd or "cc_asr_guard.py" in cmd:
        return None
    has_asr = bool(re.search(r"asr-transcribe", cmd))
    clobber = bool(re.search(
        r"\brm\b.*(?:asr/vtt|\.lock|\.vtt\.tmp)", cmd, re.I))
    if has_asr and pids:
        return (
            f"ASR already running pids={pids}; do not start a second whisper"
        )
    if clobber and pids:
        return (
            f"Refusing to rm ASR lock/tmp while whisper pids={pids}"
        )
    return None


def emit(harness: str, reason: str | None) -> None:
    if harness == "cursor":
        if reason:
            print(json.dumps({
                "permission": "deny",
                "agent_message": reason,
                "user_message": reason,
            }))
        else:
            print(json.dumps({"permission": "allow"}))
        return
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    else:
        print(json.dumps({"decision": "allow"}))


def main(argv: list[str]) -> int:
    harness = "claude"
    if "--harness" in argv:
        i = argv.index("--harness")
        harness = argv[i + 1] if i + 1 < len(argv) else "claude"
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cmd = extract_command(payload)
    pids = list_asr_pids()
    emit(harness, should_block(cmd, pids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
