#!/usr/bin/env bash
# Claude Code PreToolUse (Bash): deny second whisper / lock clobber.
set -euo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
exec python3 "$ROOT/scripts/cc_asr_guard.py" --harness claude
