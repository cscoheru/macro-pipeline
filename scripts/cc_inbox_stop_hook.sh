#!/usr/bin/env bash
# Claude Code Stop hook: keep session until inbox is idle or watch window ends.
# Logs -> stderr. JSON decision -> stdout.
set -euo pipefail
# Drain stdin (hook payload)
cat >/dev/null || true

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$ROOT" || ! -f "$ROOT/reviews/CC_INBOX.md" ]]; then
  exit 0
fi
cd "$ROOT"

inbox_status() {
  grep -E '^STATUS=' reviews/CC_INBOX.md | head -1 | sed 's/^STATUS=//' | tr -d '[:space:]' || echo UNKNOWN
}

watch_expired() {
  python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import json
p = Path("reviews/bus/state.json")
if not p.exists():
    raise SystemExit(1)
until = json.loads(p.read_text()).get("watch_until") or ""
if not until:
    raise SystemExit(1)
# accept Z or +00:00
until = until.replace("Z", "+00:00")
try:
    t = datetime.fromisoformat(until)
except ValueError:
    raise SystemExit(1)
if t.tzinfo is None:
    t = t.replace(tzinfo=timezone.utc)
raise SystemExit(0 if datetime.now(timezone.utc) > t else 1)
PY
}

emit_block() {
  python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.argv[1]}))' "$1"
}

git pull --ff-only origin main >/dev/null 2>&1 || true
STATUS=$(inbox_status)
echo "cc_stop_hook status=$STATUS" >&2

if [[ "$STATUS" == "WAIT_USER" ]]; then
  exit 0
fi

if [[ "$STATUS" == "DO" ]]; then
  asr_n=$(python3 scripts/cc_autopilot_inspect.py 2>/dev/null \
    | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("asr_n") or 0))' \
    || echo 0)
  if [[ "${asr_n}" -ge 1 ]]; then
    echo "cc_stop_hook whisper asr_n=$asr_n, allow stop" >&2
    exit 0
  fi
  if pgrep -f 'data/houchen/asr/audio/%\(id\)s' >/dev/null 2>&1; then
    echo "cc_stop_hook serial ASR loop alive, allow stop" >&2
    exit 0
  fi
  emit_block "CC Autopilot. git pull. Read reviews/CC_INBOX.md and reviews/CC_AUTOPILOT_CC.md. Execute the ticket now. After compact do not idle — inspect again. Do not ask the user. Do not stop until WAIT_CURSOR or WAIT_USER."
  exit 0
fi

if [[ "$STATUS" != "WAIT_CURSOR" ]]; then
  exit 0
fi

# WAIT_CURSOR: poll git inside the hook (no model). Then either continue (DO) or keep session.
if watch_expired; then
  echo "cc_stop_hook watch_until passed" >&2
  exit 0
fi

for _ in 1 2 3 4 5; do
  sleep 90
  git pull --ff-only origin main >/dev/null 2>&1 || true
  STATUS=$(inbox_status)
  echo "cc_stop_hook poll status=$STATUS" >&2
  if [[ "$STATUS" == "DO" ]]; then
    emit_block "CC Autopilot: Cursor posted DO (git pull). Read reviews/CC_INBOX.md and reviews/CC_AUTOPILOT_CC.md. Execute. After compact do not idle."
    exit 0
  fi
  if [[ "$STATUS" == "WAIT_USER" ]]; then
    exit 0
  fi
  if watch_expired; then
    exit 0
  fi
done

# Still WAIT_CURSOR: Autopilot standby — do not go idle after compact
emit_block "CC Autopilot 待命. git pull. Read reviews/CC_INBOX.md and reviews/CC_AUTOPILOT_CC.md. If DO, execute. If still WAIT_CURSOR, Stop (hook polls). After compact do not wait for the user."
exit 0
