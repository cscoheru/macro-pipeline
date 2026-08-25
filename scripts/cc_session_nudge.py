#!/usr/bin/env python3
"""JSON nudge for Claude Code SessionStart / PreCompact. Stdin drained."""
from __future__ import annotations

import json
import sys

NUDGE = (
    "CC Autopilot 巡检（压缩后禁止 idle）。"
    "git pull --ff-only。读 reviews/CC_INBOX.md 与 reviews/CC_AUTOPILOT_CC.md。"
    "DO：立刻执行工单，不问用户。"
    "WAIT_CURSOR：Stop，让 hook poll；不要等用户。"
    "WAIT_USER：才停。"
    "有 asr-transcribe pid 或 .lock 时禁止再开转写。"
)


def main() -> int:
    event = "SessionStart"
    if "--event" in sys.argv:
        i = sys.argv.index("--event")
        if i + 1 < len(sys.argv):
            event = sys.argv[i + 1]
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    source = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            source = str(payload.get("source") or payload.get("reason") or "")
    except Exception:
        payload = {}
    extra = "（本次为 compact 后唤醒）" if "compact" in source.lower() else ""
    msg = NUDGE + extra
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": msg,
        }
    }, ensure_ascii=False))
    print(f"cc_session_nudge source={source or 'startup'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
