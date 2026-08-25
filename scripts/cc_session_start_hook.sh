#!/usr/bin/env bash
# Claude Code SessionStart: sync inbox from origin.
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$ROOT" ]]; then
  exit 0
fi
cd "$ROOT"
git pull --ff-only origin main >/dev/null 2>&1 || true
if [[ -f reviews/CC_INBOX.md ]]; then
  echo "=== CC_INBOX (SessionStart) ===" >&2
  grep -E 'STATUS=|工单|剩余|还要做' reviews/CC_INBOX.md | head -20 >&2
fi
python3 "$ROOT/scripts/cc_session_nudge.py"
exit 0
