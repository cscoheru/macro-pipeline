#!/usr/bin/env python3
"""Fake yt-dlp for offline tests — contract-faithful + observed-call log.

Two responsibilities (P1-7):

    1. Reproduce the REAL yt-dlp I/O contract, so production code cannot pass
       tests while being incompatible with real yt-dlp:
         - `--flat-playlist -J <url>`  → prints `{"entries": [...]}`.
         - `--skip-download --dump-json <url>` → prints one info dict with
           `subtitles` / `automatic_captions` maps.
         - `--skip-download --write-subs|--write-auto-subs --sub-langs L
            --sub-format F --output <dir>/<stem>` → writes
           `<dir>/<stem>.<L>.<F>`.
         - JSON3 files contain `{"events": [{"segs": [{"utf8": "..."}]}]}`.

    2. Write an OBSERVED-CALL LOG that records every argv it actually received
       (plus cwd, wall-clock and exit code), kept SEPARATE from the response
       script. Tests assert on the observed log — never on the response script —
       to prove "no media download" and "no second download" claims.

Scenario layout (the response script, under FAKE_YTDLP_SCENARIO):

    <scenario>/
      calls.jsonl        # response script: list of {argv_prefix, exit_code,
                         #   stdout, stderr, delay_sec, info, entries}
      subs/<lang>.<fmt>  # subtitle bodies, emitted on download calls
      observed_calls.jsonl   # APPENDED by the fake (actual argv received)
"""
from __future__ import annotations

import json
import os
import sys
import time


def _scenario_dir() -> str:
    sd = os.environ.get("FAKE_YTDLP_SCENARIO", "")
    if not sd or not os.path.isdir(sd):
        print("FAKE_YTDLP_SCENARIO must be an existing directory", file=sys.stderr)
        sys.exit(64)
    return sd


def _load_calls(sd: str):
    path = os.path.join(sd, "calls.jsonl")
    if not os.path.exists(path):
        return []
    calls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                calls.append(json.loads(line))
    return calls


def _record_observed(sd: str, argv, rc, cwd, t0):
    entry = {
        "argv": argv[1:] if len(argv) > 1 else argv,  # drop fake script name
        "cwd": cwd,
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "exit_code": rc,
    }
    try:
        with open(os.path.join(sd, "observed_calls.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def _argv_prefix(argv, prefix):
    if len(argv) < len(prefix):
        return False
    return argv[: len(prefix)] == prefix


def _find_call(calls, argv, call_index):
    seen = 0
    for c in calls:
        if _argv_prefix(argv[1:], c["argv_prefix"]):
            if seen == call_index:
                return c
            seen += 1
    return None


def _state_path(sd):
    return os.path.join(sd, "_invocation_state.json")


def _load_state(sd):
    try:
        with open(_state_path(sd), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(sd, state):
    try:
        with open(_state_path(sd), "w", encoding="utf-8") as f:
            json.dump(state, f, sort_keys=True)
    except OSError:
        pass


def _emit_flat_playlist(call):
    if "entries" in call:
        return json.dumps({"entries": call["entries"]}, ensure_ascii=False)
    if "stdout" in call:
        return call["stdout"]
    return ""


def _emit_dump_json(call):
    if "info" in call:
        return json.dumps(call["info"], ensure_ascii=False)
    if "stdout" in call:
        return call["stdout"]
    return "{}"


def _emit_download(argv, sd, call):
    sub_format = sub_langs = output_template = None
    for i, tok in enumerate(argv):
        if tok == "--sub-format" and i + 1 < len(argv):
            sub_format = argv[i + 1]
        elif tok == "--sub-langs" and i + 1 < len(argv):
            sub_langs = argv[i + 1]
        elif tok == "--output" and i + 1 < len(argv):
            output_template = argv[i + 1]
    if not (sub_format and sub_langs and output_template):
        return 0
    # Real yt-dlp names the file <stem>.<lang>.<ext>.
    resolved = f"{output_template}.{sub_langs}.{sub_format}"
    src = os.path.join(sd, "subs", f"{sub_langs}.{sub_format}")
    if os.path.exists(src):
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(src, "rb") as f:
            data = f.read()
        with open(resolved, "wb") as f:
            f.write(data)
        return 0
    return 1


def _stdout_for(argv, call):
    if "--dump-json" in argv:
        return _emit_dump_json(call)
    if "--flat-playlist" in argv:
        return _emit_flat_playlist(call)
    return call.get("stdout", "")


def main(argv):
    sd = _scenario_dir()
    calls = _load_calls(sd)
    state = _load_state(sd)
    t0 = time.monotonic()

    # Key the per-kind invocation counter by the call's IDENTITY (binary + first
    # two flags), NOT by argv[1:5] — that slice includes the trailing URL for
    # `--flat-playlist`/`--dump-json`, which would give each tab/video its own
    # counter and make the response sequence restart instead of advance.
    prefix_key = " ".join(argv[1:4])
    idx = state.get(prefix_key, 0)
    call = _find_call(calls, argv, idx)
    if call is not None:
        state[prefix_key] = idx + 1
        _save_state(sd, state)
        if call.get("delay_sec"):
            time.sleep(call["delay_sec"])

    if call is None:
        _record_observed(sd, argv, 0, os.getcwd(), t0)
        return 0

    rc = call.get("exit_code", 0)
    if "--skip-download" in argv and ("--write-subs" in argv or "--write-auto-subs" in argv):
        rc2 = _emit_download(argv, sd, call)
        if rc2 != 0:
            rc = rc2
    elif rc == 0:
        sys.stdout.write(_stdout_for(argv, call))
        sys.stdout.flush()

    if call.get("stderr"):
        sys.stderr.write(call["stderr"])
        sys.stderr.flush()

    _record_observed(sd, argv, rc, os.getcwd(), t0)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
