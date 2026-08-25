#!/usr/bin/env bash
# Cursor beforeShellExecution: deny second whisper / lock clobber.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$ROOT/scripts/cc_asr_guard.py" --harness cursor
