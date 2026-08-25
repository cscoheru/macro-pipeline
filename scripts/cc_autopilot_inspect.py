#!/usr/bin/env python3
"""CC Autopilot inspect — read-only health snapshot for Cursor ticks.

Exit 0 always. JSON stdout. severity: OK | WARN | ACTION.
Never starts whisper. Never writes store.db.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PILOT_IDS = ("epg0aoUbPN4", "E9uJV2bwzjM", "jfXAn1dgkyw")
EXPAND5_IDS = (
    "7L9X75dL1Dg",
    "TFjqgua7jKk",
    "Xp4GBvKBPww",
    "XUKmvcu9sss",
    "Ft5Xg-Wv52U",
)
WATCH_IDS = PILOT_IDS + EXPAND5_IDS
STALL_SEC = 25 * 60
FROZEN_DEFAULT = (
    "4a8e409b7279b72a57364ef735f5f6066a20b6d99352d676dc94d9a549e8a43c"
)


def repo_root() -> Path:
    override = os.environ.get("CC_AUTOPILOT_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def inbox_status(text: str) -> str:
    m = re.search(r"^STATUS=(\S+)", text, re.M)
    return m.group(1) if m else "UNKNOWN"


def list_asr_pids(ps_out: str | None = None) -> list[int]:
    """Python asr-transcribe PIDs only (ignore zsh wrappers)."""
    if ps_out is None:
        r = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True, text=True)
        ps_out = r.stdout or ""
    pids: list[int] = []
    for raw in ps_out.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            if line.isdigit():
                pids.append(int(line))
            continue
        pid_s, cmd = parts
        if not pid_s.isdigit():
            continue
        head = cmd.split(None, 1)[0]
        if "python" not in head.lower():
            continue
        if "asr-transcribe" in cmd:
            pids.append(int(pid_s))
    return sorted(set(pids))


def _file_info(path: Path) -> dict | None:
    if not path.exists():
        return None
    st = path.stat()
    return {"bytes": st.st_size, "mtime": int(st.st_mtime)}


def vtt_view(vtt_dir: Path, video_ids: tuple[str, ...] = WATCH_IDS) -> dict:
    out = {}
    now = time.time()
    for vid in video_ids:
        tmp = _file_info(vtt_dir / f"{vid}.vtt.tmp")
        final = _file_info(vtt_dir / f"{vid}.vtt")
        lock = (vtt_dir / f"{vid}.lock").exists()
        growing = False
        if tmp:
            growing = (now - tmp["mtime"]) < 180
        out[vid] = {"tmp": tmp, "vtt": final, "lock": lock, "growing": growing}
    return out


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def frozen_store_sha(state: dict) -> str:
    return (state.get("store_sha_frozen") or FROZEN_DEFAULT).strip()


def transcript_ok_count(root: Path, video_id: str) -> int:
    db = root / "data" / "houchen" / "houchen.sqlite3"
    if not db.exists():
        return -1
    import sqlite3
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM transcript_version "
            "WHERE video_id=? AND status='ok'",
            (video_id,)).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return -1
    finally:
        conn.close()


def accepted_count(root: Path, video_id: str) -> int:
    db = root / "data" / "houchen" / "houchen.sqlite3"
    if not db.exists():
        return -1
    import sqlite3
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM claim WHERE video_id=? AND status='accepted'",
            (video_id,)).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return -1
    finally:
        conn.close()


def classify(inbox: str, pids: list[int], vtts: dict,
             store_ok: bool, pending_import: list[str] | None = None
             ) -> tuple[str, list[str], str]:
    actions: list[str] = []
    if len(pids) > 1:
        actions.append("kill_duplicate_whisper")
    if inbox == "WAIT_CURSOR" and not pids:
        actions.append("accept_inbox")
    if inbox == "DO" and not pids and pending_import:
        actions.append("finish_import_analyze")
    stalled = False
    if inbox == "DO" and len(pids) <= 1:
        for inf in vtts.values():
            tmp = inf.get("tmp")
            if tmp and not inf.get("growing") and not inf.get("vtt"):
                if time.time() - tmp["mtime"] >= STALL_SEC:
                    stalled = True
        if stalled:
            actions.append("mark_stalled")
    if actions and any(a in (
        "kill_duplicate_whisper", "accept_inbox", "finish_import_analyze"
    ) for a in actions):
        sev = "ACTION"
    elif (not store_ok) or stalled:
        sev = "WARN"
    else:
        sev = "OK"
    line = (
        f"inbox={inbox} asr_n={len(pids)} store_ok={store_ok} "
        f"severity={sev} actions={actions}"
    )
    return sev, actions, line


def inspect(root: Path | None = None) -> dict:
    root = root or repo_root()
    inbox_path = root / "reviews" / "CC_INBOX.md"
    state_path = root / "reviews" / "bus" / "state.json"
    vtt_dir = root / "data" / "houchen" / "asr" / "vtt"
    store_path = Path(os.environ.get(
        "CC_AUTOPILOT_STORE", str(root / "data" / "store.db")))
    inbox_text = inbox_path.read_text(encoding="utf-8") if inbox_path.exists() else ""
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    pids_env = os.environ.get("CC_AUTOPILOT_PIDS")
    if pids_env is not None:
        pids = [int(x) for x in pids_env.split(",") if x.strip().isdigit()]
    else:
        pids = list_asr_pids()
    vtts = vtt_view(vtt_dir)
    got = sha256_file(store_path)
    frozen = frozen_store_sha(state)
    store_ok = got == frozen
    inbox = inbox_status(inbox_text)
    pending: list[str] = []
    if inbox == "DO" and not pids:
        for vid, inf in vtts.items():
            vtt = inf.get("vtt")
            if vtt and vtt["bytes"] > 32 and not inf.get("tmp"):
                if (transcript_ok_count(root, vid) == 0
                        and accepted_count(root, vid) == 0):
                    pending.append(vid)
    sev, actions, line = classify(inbox, pids, vtts, store_ok, pending)
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inbox": inbox,
        "asr_pids": pids,
        "asr_n": len(pids),
        "vtt": vtts,
        "store_sha": got,
        "store_frozen": frozen,
        "store_ok": store_ok,
        "severity": sev,
        "actions": actions,
        "user_line": line,
    }


def main() -> int:
    print(json.dumps(inspect(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
