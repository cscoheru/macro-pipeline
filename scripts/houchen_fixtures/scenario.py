"""Shared test scenario helpers for the Hou Chen PR-1 suite.

Builds data-driven scenarios for the contract-faithful fake_ytdlp.py and
provides a `make_runner()` that invokes it exactly as production does (via
`python3 fake.py <argv>`). Tests assert on the OBSERVED call log, never on the
response script.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

FIXTURE_DIR = os.path.dirname(os.path.abspath(__file__))
FAKE_PATH = os.path.join(FIXTURE_DIR, "fake_ytdlp.py")

JSON3_BODY = json.dumps({
    "events": [{"segs": [{"utf8": "中央政治局会议承认经济面临困难挑战"}]},
               {"segs": [{"utf8": "但会议没有触及收入分配问题"}]}],
}, ensure_ascii=False)

# Richer JSON3 with timestamps (PR-2): events carry tStartMs + dDurationMs so
# the parser can compute per-cue millisecond ranges. Same two sentences as
# JSON3_BODY but in real YouTube shape.
JSON3_BODY_WITH_TS = json.dumps({
    "events": [
        {"tStartMs": 0, "dDurationMs": 1500,
         "segs": [{"utf8": "中央政治局会议承认经济面临困难挑战"}]},
        {"tStartMs": 1500, "dDurationMs": 1800,
         "segs": [{"utf8": "但会议没有触及收入分配问题"}]},
    ],
}, ensure_ascii=False)

VTT_BODY = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n中央政治局\n\n00:00:01.000 --> 00:00:02.000\n第二个 cue\n"

# PR-2 fixtures covering normalization edge cases.
VTT_BODY_REPEAT = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:01.000\n"
    "滚动字幕\n\n"
    "00:00:01.000 --> 00:00:02.000\n"
    "滚动字幕\n\n"
    "00:00:02.000 --> 00:00:03.000\n"
    "滚动字幕\n\n"
    "00:00:03.000 --> 00:00:04.000\n"
    "下一段主题\n"
)

# Empty cue: has timestamp but no body text — must be dropped.
VTT_BODY_EMPTY = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:01.000\n"
    "\n\n"
    "00:00:01.000 --> 00:00:02.000\n"
    "第二个 cue\n"
)

# Long cue that exceeds MAX_MERGE_SEGMENT_MS — must not be merged across.
VTT_BODY_LONG = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:03.000\n"
    "第一段主题\n\n"
    "00:00:04.500 --> 00:00:08.000\n"
    "第二段主题\n\n"
    "00:00:08.500 --> 00:00:10.000\n"
    "中间过渡\n\n"
    "00:00:10.500 --> 00:00:13.500\n"
    "第三段完全不同的主题\n"
)

# VTT with HTML-ish formatting tags — must be stripped before text normalize.
VTT_BODY_TAGS = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.000\n"
    "<i>斜体片段</i> 与 <b>粗体</b>\n\n"
    "00:00:02.500 --> 00:00:04.500\n"
    "下一段没有格式\n"
)


def make_runner(scenario_dir: str):
    def runner(argv, *, timeout_sec, stdin_bytes=None, cwd=None):
        env = dict(os.environ)
        env["FAKE_YTDLP_SCENARIO"] = scenario_dir
        return subprocess.run(
            [sys.executable, FAKE_PATH] + list(argv),
            shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_sec, check=False, cwd=cwd, env=env,
        )
    return runner


def write_scenario(scenario_dir: str, calls, subs=None):
    os.makedirs(scenario_dir, exist_ok=True)
    os.makedirs(os.path.join(scenario_dir, "subs"), exist_ok=True)
    with open(os.path.join(scenario_dir, "calls.jsonl"), "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    if subs:
        for lang, (fmt, body) in subs.items():
            with open(os.path.join(scenario_dir, "subs", f"{lang}.{fmt}"),
                      "w", encoding="utf-8") as f:
                f.write(body)


def playlist_call(entries, *, argv_prefix=None):
    return {
        "argv_prefix": argv_prefix or ["yt-dlp", "--flat-playlist", "-J"],
        "exit_code": 0,
        "entries": entries,
        "stderr": "",
    }


def version_call(version="2026.01\n"):
    """The single `yt-dlp --version` probe every run performs (P2-3)."""
    return {
        "argv_prefix": ["yt-dlp", "--version"],
        "exit_code": 0,
        "stdout": version,
        "stderr": "",
    }


def info_call(info, *, argv_prefix=None):
    return {
        "argv_prefix": argv_prefix or ["yt-dlp", "--skip-download", "--dump-json"],
        "exit_code": 0,
        "info": info,
        "stderr": "",
    }


def download_call(language="zh-Hans", *, auto=False):
    flag = "--write-auto-subs" if auto else "--write-subs"
    return {
        "argv_prefix": ["yt-dlp", "--skip-download", flag],
        "exit_code": 0,
        "stderr": "",
    }


def observed_calls(scenario_dir: str):
    path = os.path.join(scenario_dir, "observed_calls.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def assert_no_media_flags(observed):
    """Assert no observed call carried a media-download flag."""
    bad = ("--extract-audio", "--audio-format", "-f", "--format",
           "--merge-output-format")
    for call in observed:
        argv = call.get("argv", [])
        for flag in bad:
            assert flag not in argv, f"media flag {flag} seen in {argv}"
