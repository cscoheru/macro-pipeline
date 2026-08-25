"""
houchen_import_transcript.py — Import human-written transcripts (WPS etc.)

Supports .txt (plain text), .vtt (WebVTT), .srt (SubRip).
Creates raw_caption + transcript_version + transcript_segment records
so downstream normalize/analyze can consume them.

Normalizer identity: wps_import / 2026-08-25.1
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import houchen_paths

NORMALIZER_NAME = "wps_import"
NORMALIZER_VERSION = "2026-08-25.1"

# ~300 Chinese chars per minute for timing estimation
CHARS_PER_MINUTE = 300


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_timestamp(ts: str) -> int:
    """Parse VTT/SRT timestamp to milliseconds.

    Accepts: HH:MM:SS.mmm or HH:MM:SS,mmm or MM:SS.mmm
    """
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600000 + int(m) * 60000 + int(float(s) * 1000)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60000 + int(float(s) * 1000)
    else:
        return int(float(parts[0]) * 1000)


def parse_txt(text: str) -> list[dict]:
    """Parse plain text into segments.

    Splits on double newlines (paragraphs) or single newlines if no doubles.
    Estimates timing at CHARS_PER_MINUTE chars/min.
    """
    # Split by double newline first, then single if only one block
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip() for b in text.split("\n") if b.strip()]

    segments = []
    current_ms = 0
    for i, block in enumerate(blocks):
        # Estimate duration: chars / rate
        duration_ms = max(1000, int(len(block) / CHARS_PER_MINUTE * 60000))
        segments.append({
            "start_ms": current_ms,
            "end_ms": current_ms + duration_ms,
            "text": block,
            "raw_cue_start": i,
            "raw_cue_end": i,
        })
        current_ms += duration_ms

    return segments


def parse_vtt(text: str) -> list[dict]:
    """Parse WebVTT format into segments."""
    segments = []
    # VTT: timestamp lines like "00:00:01.000 --> 00:00:05.000"
    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[\.,]\d{3})"
    )
    lines = text.split("\n")
    cue_idx = 0
    i = 0
    while i < len(lines):
        m = pattern.search(lines[i])
        if m:
            start_ms = _parse_timestamp(m.group(1))
            end_ms = _parse_timestamp(m.group(2))
            # Collect text lines until blank or next timestamp
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() and not pattern.search(lines[i]):
                # Strip VTT tags like <c> </c>
                clean = re.sub(r"<[^>]+>", "", lines[i])
                text_lines.append(clean.strip())
                i += 1
            full_text = " ".join(t for t in text_lines if t)
            if full_text:
                segments.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": full_text,
                    "raw_cue_start": cue_idx,
                    "raw_cue_end": cue_idx,
                })
                cue_idx += 1
        else:
            i += 1

    return segments


def parse_srt(text: str) -> list[dict]:
    """Parse SubRip format into segments."""
    segments = []
    # SRT: "00:00:01,000 --> 00:00:05,000"
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})"
    )
    lines = text.split("\n")
    cue_idx = 0
    i = 0
    while i < len(lines):
        m = pattern.search(lines[i])
        if m:
            start_ms = _parse_timestamp(m.group(1))
            end_ms = _parse_timestamp(m.group(2))
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            full_text = " ".join(text_lines)
            if full_text:
                segments.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": full_text,
                    "raw_cue_start": cue_idx,
                    "raw_cue_end": cue_idx,
                })
                cue_idx += 1
        else:
            i += 1

    return segments


PARSERS = {
    ".txt": parse_txt,
    ".vtt": parse_vtt,
    ".srt": parse_srt,
}


def _ms_to_vtt(ms: int) -> str:
    """Convert milliseconds to VTT timestamp HH:MM:SS.mmm."""
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def _segments_to_vtt(segments: list[dict]) -> str:
    """Synthesize a VTT file from parsed segments."""
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments):
        lines.append(f"{i + 1}")
        lines.append(f"{_ms_to_vtt(seg['start_ms'])} --> {_ms_to_vtt(seg['end_ms'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def _read_docx_text(path: Path) -> str:
    """Extract plain text from .docx file (paragraph by paragraph)."""
    import docx
    doc = docx.Document(str(path))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _parse_file(path: Path) -> list[dict]:
    """Parse a file based on extension. Handles .docx by converting to text first."""
    ext = path.suffix.lower()
    if ext == ".docx":
        text = _read_docx_text(path)
        return parse_txt(text)
    parser = PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported format: {ext}. Use .txt, .vtt, .srt, or .docx")
    raw_text = path.read_text(encoding="utf-8")
    return parser(raw_text)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_transcript(
    conn: sqlite3.Connection,
    video_id: str,
    file_path: Path,
    language: str = "zh",
) -> dict:
    """Import a human-written transcript file.

    Args:
        conn: houchen DB connection (write mode)
        video_id: YouTube video ID
        file_path: path to .txt/.vtt/.srt file
        language: language code (default 'zh')

    Returns:
        Summary dict with counts and IDs.
    """
    ext = file_path.suffix.lower()
    supported = set(PARSERS.keys()) | {".docx"}
    if ext not in supported:
        raise ValueError(f"Unsupported format: {ext}. Use .txt, .vtt, .srt, or .docx")

    # Read and hash
    raw_bytes = file_path.read_bytes()

    # Parse
    segments = _parse_file(file_path)
    if not segments:
        return {"video_id": video_id, "status": "empty",
                "segments": 0, "transcript_version_id": None}

    # For .txt/.docx: synthesize VTT for storage (format CHECK constraint)
    store_ext = ext
    store_bytes = raw_bytes
    if ext in (".txt", ".docx"):
        store_ext = ".vtt"
        store_bytes = _segments_to_vtt(segments).encode("utf-8")

    # Final content SHA (of stored bytes, not original)
    content_sha = hashlib.sha256(store_bytes).hexdigest()

    # Check idempotency: existing transcript_version with same sha?
    existing = conn.execute(
        "SELECT transcript_version_id, status FROM transcript_version "
        "WHERE video_id=? AND raw_caption_sha256=? "
        "AND normalizer_name=? AND normalizer_version=?",
        (video_id, content_sha, NORMALIZER_NAME, NORMALIZER_VERSION),
    ).fetchone()
    if existing and existing["status"] == "ok":
        return {"video_id": video_id, "status": "already_imported",
                "segments": 0,
                "transcript_version_id": existing["transcript_version_id"]}

    # Save file to raw/captions (content-addressed)
    raw_dir = Path(houchen_paths.raw_captions_dir())
    sub_dir = raw_dir / content_sha[:2]
    sub_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_dir / f"{content_sha}{store_ext}"
    if not dest.exists():
        dest.write_bytes(store_bytes)

    # Insert raw_caption (idempotent via INSERT OR IGNORE)
    byte_count = dest.stat().st_size
    cue_count = len(segments)
    store_format = "vtt" if ext in (".txt", ".docx") else ext.lstrip(".")
    try:
        conn.execute(
            "INSERT INTO raw_caption "
            "(video_id, language, caption_kind, format, content_sha256, "
            " local_path, byte_count, cue_count, fetched_at, "
            " yt_dlp_version, source_metadata_sha256) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, language, "manual",
             store_format,
             content_sha, str(dest), byte_count, cue_count,
             datetime.now(timezone.utc).isoformat(),
             "wps_import", content_sha),
        )
    except sqlite3.IntegrityError:
        # raw_caption already exists for this video_id (PK conflict)
        # Update is forbidden by trigger; if same sha, just proceed
        pass

    # Create transcript_version
    tv_id = f"tv_{uuid.uuid7()}"
    conn.execute(
        "INSERT INTO transcript_version "
        "(transcript_version_id, video_id, raw_caption_sha256, "
        " normalizer_name, normalizer_version, created_at, "
        " content_sha256, status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (tv_id, video_id, content_sha,
         NORMALIZER_NAME, NORMALIZER_VERSION,
         datetime.now(timezone.utc).isoformat(),
         content_sha, "ok"),
    )

    # Insert segments
    for i, seg in enumerate(segments):
        conn.execute(
            "INSERT INTO transcript_segment "
            "(transcript_version_id, ordinal, start_ms, end_ms, text, "
            " raw_cue_start, raw_cue_end, speaker) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tv_id, i, seg["start_ms"], seg["end_ms"], seg["text"],
             seg["raw_cue_start"], seg["raw_cue_end"], None),
        )

    conn.commit()

    return {
        "video_id": video_id,
        "status": "success",
        "transcript_version_id": tv_id,
        "segments": len(segments),
        "content_sha256": content_sha,
        "format": ext.lstrip("."),
        "normalizer": f"{NORMALIZER_NAME}/{NORMALIZER_VERSION}",
    }
