"""Deterministic transcript normalizer for the Hou Chen research corpus (PR-2).

The whole module is pure-functional: every public function takes only strings /
lists / dataclasses, has no side effects beyond content-addressed writes, and
produits a stable output for a stable input. NO model is ever called — the
brief §8.4 explicitly defers model-polished text to a separate derived
version. The PR-2 normalizer is the FIRST version of a `transcript_version`
row; later versions may be added without breaking this one.

Brief §8 invariants enforced here:

    1. Pure-functional / deterministic — re-running on identical input gives
       identical JSON, SHA-256, and DB rows.
    2. json3 / vtt cue parsing keeps millisecond timestamps.
    3. Pure format marks, empty cues, and deterministic scrolling repetitions
       are removed.
    4. Merge rules are bounded: `MAX_MERGE_GAP_MS` joins adjacent cues;
       `MAX_MERGE_SEGMENT_MS` is a hard upper bound (brief §8.3 "不能把跨主题
       长段合成一个片段"). Cross-topic long segments never get merged.
    5. Each segment retains a `(raw_cue_start, raw_cue_end)` reverse mapping.
    6. `text` is NFC + whitespace-folded only. The same routine lives in
       `houchen_quote.normalize_for_compare` and is reused here.
    7. The output JSON is SHA-256-stamped; same input + same normalizer
       version = same SHA.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_paths  # noqa: E402
import houchen_quote  # noqa: E402


# ---------------------------------------------------------------------------
# Identifiers (also written into transcript_version.normalizer_* columns)
# ---------------------------------------------------------------------------

NORMALIZER_NAME = "vtt_json3_v1"
NORMALIZER_VERSION = "2026-08-24.1"


# Bounded merge rules. Constants live here so tests can reference them by name.
MAX_MERGE_GAP_MS = 1500           # adjacent cues joined if gap <= this
MAX_MERGE_SEGMENT_MS = 8000       # hard upper bound on segment span
MAX_REPEAT_WINDOW = 5             # collapse up to N consecutive same-text cues
EMPTY_CUE_TEXT_OK = False         # we drop cues with empty text after NFC


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cue:
    """A single raw cue from json3 / vtt, before any merging.

    Fields:
      ordinal    — 0-based position in the source file's cue list.
      start_ms   — start timestamp (inclusive).
      end_ms     — end timestamp (inclusive/exclusive depending on format;
                   kept as the source declared; the normalizer never expands
                   a cue beyond [start_ms, end_ms]).
      text       — raw text (NOT yet normalized). May contain `<i>` etc.
    """
    ordinal: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Segment:
    """A normalized segment. May correspond to one or more raw cues; the
    mapping is preserved via `raw_cue_start` / `raw_cue_end` (both inclusive,
    0-based)."""
    ordinal: int        # ordinal inside the transcript_version (0-based)
    start_ms: int
    end_ms: int
    text: str           # already NFC + whitespace-folded
    raw_cue_start: int
    raw_cue_end: int
    speaker: str | None = None


@dataclass(frozen=True)
class TranscriptResult:
    """Bundled return for `transcribe_video`. Callers persist this to DB +
    on-disk JSON."""
    video_id: str
    raw_caption_sha256: str
    normalizer_name: str
    normalizer_version: str
    created_at: str
    content_sha256: str            # sha256 of the derived JSON
    local_path: str                # absolute path under data/houchen/derived/...
    segments: list[Segment]


# ---------------------------------------------------------------------------
# Parsers (deterministic, no I/O)
# ---------------------------------------------------------------------------

_VTT_TS_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


def _ts_to_ms(h, m, s, ms) -> int:
    return ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(ms)


def parse_vtt(text: str) -> list[Cue]:
    """Parse a `WEBVTT`-prefixed cue sheet.

    Returns cues in source order; cue ordinal is 0-based. Empty-text cues
    after NFC + whitespace fold are dropped (brief §8.2). Cues with
    missing/unparseable timestamps raise ValueError — the caller treats
    that as `normalize_failed`.
    """
    if not text or not text.lstrip().startswith("WEBVTT"):
        raise ValueError("not a WEBVTT document (missing WEBVTT header)")
    cues: list[Cue] = []
    ordinal = 0
    # Split on blank-line boundaries.
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("WEBVTT") or block.startswith("NOTE"):
            continue
        # Optional cue identifier line (anything before the timestamp).
        lines = block.split("\n")
        ts_line_idx = None
        for i, line in enumerate(lines):
            if _VTT_TS_RE.search(line):
                ts_line_idx = i
                break
        if ts_line_idx is None:
            # Malformed cue — skip silently (some VTT files include STYLE blocks).
            continue
        m = _VTT_TS_RE.search(lines[ts_line_idx])
        if not m:
            continue
        start_ms = _ts_to_ms(*m.group(1, 2, 3, 4))
        end_ms = _ts_to_ms(*m.group(5, 6, 7, 8))
        body = "\n".join(lines[ts_line_idx + 1:]).strip()
        if not body:
            continue
        cues.append(Cue(ordinal=ordinal, start_ms=start_ms, end_ms=end_ms,
                         text=body))
        ordinal += 1
    return cues


def parse_json3(text: str) -> list[Cue]:
    """Parse a YouTube-style JSON3 caption document.

    Each event has `tStartMs` and `dDurationMs`. Two special line-break cases:

    - `segs[0].aAppend == 1` → the FIRST segment of this event is treated as
      a continuation of the previous cue (an inline line break). The actual
      text segments that follow are appended to the previous cue.
    - `segs == [{"utf8": "\\n"}]` (no aAppend) → a standalone newline event;
      this is a hard cue boundary that flushes the pending cue.

    Anything else starts a NEW cue. Without a newline / aAppend event, two
    adjacent text events become two separate cues — YouTube emits the
    newline events explicitly and we trust them.
    """
    if not text:
        raise ValueError("empty json3 input")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid json3: {e}") from e
    events = doc.get("events") or []
    if not isinstance(events, list):
        raise ValueError("json3 'events' is not a list")

    cues: list[Cue] = []
    ordinal = 0
    pending_text: list[str] = []
    pending_start: int | None = None
    pending_end: int | None = None

    def _flush():
        nonlocal pending_text, pending_start, pending_end, ordinal
        body = "".join(pending_text).strip()
        pending_text = []
        if body and pending_start is not None and pending_end is not None:
            cues.append(Cue(ordinal=ordinal, start_ms=pending_start,
                             end_ms=pending_end, text=body))
            ordinal += 1
        pending_start = None
        pending_end = None

    for ev in events:
        segs = ev.get("segs") or []
        if not isinstance(segs, list):
            _flush()
            continue

        # Hard newline boundary: a single newline-only segment without aAppend.
        if (len(segs) == 1 and isinstance(segs[0], dict)
                and segs[0].get("utf8") == "\n"
                and segs[0].get("aAppend") != 1):
            _flush()
            continue

        # Extract text segments, respecting aAppend on the first.
        aappend = (segs and isinstance(segs[0], dict)
                   and segs[0].get("aAppend") == 1)
        text_parts: list[str] = []
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                continue
            if i == 0 and aappend:
                continue
            t = seg.get("utf8", "")
            if t:
                text_parts.append(t)
        text_chunk = "".join(text_parts)
        if not text_chunk:
            # Pure formatting event with no text → just flush.
            _flush()
            continue

        ev_start = int(ev.get("tStartMs", 0))
        ev_end = ev_start + int(ev.get("dDurationMs", 0))

        if aappend and pending_start is not None:
            # Continuation: keep the original start, append text, extend end.
            pending_text.append(text_chunk)
            pending_end = ev_end
        else:
            # New cue: flush any pending then start.
            _flush()
            pending_start = ev_start
            pending_end = ev_end
            pending_text = [text_chunk]
    _flush()
    return cues


# ---------------------------------------------------------------------------
# Normalization (deterministic, no I/O)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_PUNCT_BREAK_RE = re.compile(r"[。！？!?]")


def _strip_formatting(text: str) -> str:
    """Strip HTML-style tags and decode entities (brief §8.2)."""
    s = _TAG_RE.sub("", text)
    s = html.unescape(s)
    return s


def _merge_adjacent(segments: list[Segment]) -> list[Segment]:
    """Apply bounded merge (brief §8.3). Adjacent segments are joined if:

        - 0 < gap = next.start_ms - cur.end_ms  ≤  MAX_MERGE_GAP_MS
            (strictly positive gap — back-to-back cues are NOT merged, since
            subtitle authors who left them as separate cues meant them as
            separate cues)
        - cur.text does NOT end with a sentence terminator (`。！？!?`)
        - merged.end_ms - merged.start_ms ≤ MAX_MERGE_SEGMENT_MS (hard cap)

    `raw_cue_start` / `raw_cue_end` are extended to cover the merged span.
    `ordinal` of the survivor is preserved; later ordinals are dropped.
    """
    if not segments:
        return segments
    merged: list[Segment] = [segments[0]]
    for nxt in segments[1:]:
        cur = merged[-1]
        gap = nxt.start_ms - cur.end_ms
        ends_with_break = bool(_PUNCT_BREAK_RE.search(cur.text[-1:]))
        if 0 < gap <= MAX_MERGE_GAP_MS and not ends_with_break:
            merged_span = nxt.end_ms - cur.start_ms
            if merged_span <= MAX_MERGE_SEGMENT_MS:
                # Concatenate normalized texts with a single space boundary.
                merged[-1] = Segment(
                    ordinal=cur.ordinal,
                    start_ms=cur.start_ms,
                    end_ms=nxt.end_ms,
                    text=houchen_quote.normalize_for_compare(cur.text + " " + nxt.text),
                    raw_cue_start=cur.raw_cue_start,
                    raw_cue_end=nxt.raw_cue_end,
                    speaker=cur.speaker,   # speaker is never inferred (brief §7.1)
                )
                continue
        merged.append(nxt)
    return merged


def _collapse_repeats(segments: list[Segment]) -> list[Segment]:
    """Collapse deterministic scrolling repetitions (brief §8.2).

    For each run of consecutive segments sharing identical text:

      - If the run length N ≤ MAX_REPEAT_WINDOW: keep only the FIRST segment
        and drop the rest. This is the deterministic-scroll dedup case.
      - If N > MAX_REPEAT_WINDOW: the run is too long to be a scrolling bug
        (might be intentional repetition like an end-credit loop). Truncate
        to the first MAX_REPEAT_WINDOW segments and drop the rest.

    In both cases the surviving run is a contiguous prefix of the original,
    preserving raw_cue_start / raw_cue_end mapping.
    """
    if not segments:
        return segments
    out: list[Segment] = []
    run_start = 0  # index of the first segment in the current run
    run_text = segments[0].text
    for i in range(1, len(segments)):
        if segments[i].text == run_text:
            continue
        out.extend(_take_run(segments[run_start:i]))
        run_text = segments[i].text
        run_start = i
    out.extend(_take_run(segments[run_start:]))
    return out


def _take_run(run: list[Segment]) -> list[Segment]:
    """Apply the window cap to a run of identical-text segments."""
    if len(run) <= MAX_REPEAT_WINDOW:
        return [run[0]]  # collapse the (short) scroll-repetition to one
    return list(run[:MAX_REPEAT_WINDOW])  # long run: keep only the window prefix


def normalize_cues(cues: Iterable[Cue]) -> list[Segment]:
    """Convert raw cues to normalized segments (brief §8).

    Steps, in order (each is pure / deterministic):
      1. Drop empty-text cues (after NFC + whitespace fold).
      2. Strip HTML-style tags / decode entities.
      3. NFC + whitespace fold the text. The speaker is left as `None`
         (never defaulted to "李厚辰" — brief §7.1).
      4. Merge adjacent cues (bounded per `_merge_adjacent`).
      5. Collapse deterministic scrolling repetitions.
      6. Re-number ordinals 0..N-1.
    """
    if cues is None:
        return []
    out: list[Segment] = []
    ordinal = 0
    last_n: int | None = None
    for c in cues:
        if c is None:
            continue
        cleaned = _strip_formatting(c.text)
        norm = houchen_quote.normalize_for_compare(cleaned)
        if not norm:
            continue
        if c.end_ms < c.start_ms:
            # Defensive: malformed timestamp, skip.
            continue
        out.append(Segment(
            ordinal=ordinal,
            start_ms=c.start_ms,
            end_ms=c.end_ms,
            text=norm,
            raw_cue_start=c.ordinal,
            raw_cue_end=c.ordinal,
            speaker=None,
        ))
        ordinal += 1
    # Preserve caller-visible ordinals (1..N); the merge may collapse some.
    merged = _merge_adjacent(out)
    collapsed = _collapse_repeats(merged)
    # Re-number ordinals to a contiguous 0..N-1 (DB UNIQUE constraint).
    return [
        Segment(ordinal=i, start_ms=s.start_ms, end_ms=s.end_ms,
                text=s.text, raw_cue_start=s.raw_cue_start,
                raw_cue_end=s.raw_cue_end, speaker=s.speaker)
        for i, s in enumerate(collapsed)
    ]


# ---------------------------------------------------------------------------
# Atomic derived-file install
# ---------------------------------------------------------------------------

def _atomic_install_json(target_path: str, payload: dict) -> None:
    """Write JSON to target atomically: `tmp` + `os.fsync()` + `os.replace`.

    The directory tree is created via `os.makedirs(..., exist_ok=True)` after
    the per-component symlink walk has validated it (caller's responsibility).
    Mode 0700 on directories, 0600 on the resulting file.
    """
    parent = os.path.dirname(target_path)
    houchen_paths.assert_no_symlink_components(parent)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    tmp = f"{target_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, sort_keys=True,
                  separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, target_path)


def _payload_for(video_id: str, raw_caption_sha256: str, segments: list[Segment],
                 created_at: str) -> dict:
    return {
        "schema": "houchen/transcript_version/v1",
        "video_id": video_id,
        "raw_caption_sha256": raw_caption_sha256,
        "normalizer": {
            "name": NORMALIZER_NAME,
            "version": NORMALIZER_VERSION,
        },
        "created_at": created_at,
        "segments": [
            {
                "ordinal": s.ordinal,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
                "raw_cue_start": s.raw_cue_start,
                "raw_cue_end": s.raw_cue_end,
                "speaker": s.speaker,
            } for s in segments
        ],
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def transcribe_video(*, video_id: str, raw_caption_path: str,
                     raw_caption_sha256: str, raw_format: str,
                     created_at: str,
                     normalizer_name: str = NORMALIZER_NAME,
                     normalizer_version: str = NORMALIZER_VERSION
                     ) -> TranscriptResult:
    """Read the frozen raw caption from `raw_caption_path`, parse + normalize,
    write the derived JSON to its content-addressed location, and return the
    full `TranscriptResult`.

    Raises:
      - `ValueError` for invalid inputs (bad video_id, unsupported
        normalizer_name/version, unsupported format, malformed VTT/JSON3).
        The caller is expected to record these as `outcome='normalize_failed'`
        in a `corpus_attempt` row.
      - `OSError` if the derived directory cannot be created or the file
        cannot be written (propagated, not caught).

    Idempotency: if the content-addressed JSON already exists with the same
    `content_sha256`, the existing file is reused (no rewrite, no SHA change).
    """
    if normalizer_name != NORMALIZER_NAME:
        raise ValueError(f"unsupported normalizer_name: {normalizer_name!r}")
    if normalizer_version != NORMALIZER_VERSION:
        raise ValueError(
            f"normalizer_version mismatch: expected {NORMALIZER_VERSION!r},"
            f" got {normalizer_version!r}")
    if not re.fullmatch(houchen_paths.VIDEO_ID_RE, video_id):
        raise ValueError(f"invalid video_id: {video_id!r}")
    if not (isinstance(raw_caption_sha256, str) and len(raw_caption_sha256) == 64):
        raise ValueError("raw_caption_sha256 must be 64-char hex")

    with open(raw_caption_path, "r", encoding="utf-8", errors="replace") as f:
        body = f.read()

    fmt = raw_format.lower()
    if fmt == "vtt":
        cues = parse_vtt(body)
    elif fmt == "json3":
        cues = parse_json3(body)
    else:
        raise ValueError(
            f"unsupported format for normalization: {raw_format!r}")

    segments = normalize_cues(cues)
    payload = _payload_for(video_id, raw_caption_sha256, segments, created_at)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    content_sha = hashlib.sha256(blob).hexdigest()
    target = houchen_paths.transcript_target_path(
        normalizer_version, content_sha)
    # Idempotent install: write only if absent or different bytes.
    if not os.path.isfile(target):
        _atomic_install_json(target, payload)
    else:
        # Re-check: round-trip the existing file and verify its hash matches.
        with open(target, "rb") as f:
            existing = f.read()
        if hashlib.sha256(existing).hexdigest() != content_sha:
            raise ValueError(
                f"derived file {target} exists with different bytes")

    return TranscriptResult(
        video_id=video_id,
        raw_caption_sha256=raw_caption_sha256,
        normalizer_name=normalizer_name,
        normalizer_version=normalizer_version,
        created_at=created_at,
        content_sha256=content_sha,
        local_path=target,
        segments=segments,
    )