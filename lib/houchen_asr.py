"""houchen_asr.py — Local ASR transcription for streams.

Uses faster-whisper on CPU to transcribe YouTube audio.
Strict: refuses shorts collection.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "data" / "houchen" / "asr" / "audio"
VTT_DIR = PROJECT_ROOT / "data" / "houchen" / "asr" / "vtt"


def find_audio(video_id: str) -> Path | None:
    for ext in ("webm", "mp3", "m4a", "opus", "wav"):
        p = AUDIO_DIR / f"{video_id}.{ext}"
        if p.exists():
            return p
    return None


def is_short(video_id: str, houchen_db: Path) -> bool:
    """True if video_id belongs to shorts collection."""
    conn = sqlite3.connect(str(houchen_db))
    try:
        row = conn.execute("""
            SELECT 1 FROM video_collection_membership m
            JOIN video_collection c ON m.collection_id=c.collection_id
            WHERE m.video_id=? AND c.collection_name='shorts'
            LIMIT 1
        """, (video_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def transcribe(video_id: str, model_name: str = "small",
               houchen_db: Path | None = None) -> dict:
    """Transcribe audio for video_id using faster-whisper.

    Returns: {video_id, duration_sec, segments, vtt_path}.
    Raises: RuntimeError if video is short or audio not found.
    """
    houchen_db = houchen_db or (PROJECT_ROOT / "data" / "houchen" / "houchen.sqlite3")

    if is_short(video_id, houchen_db):
        raise RuntimeError(f"REFUSED: {video_id} is a short (slice); ASR skipped")

    audio_path = find_audio(video_id)
    if audio_path is None:
        raise RuntimeError(f"audio not found for {video_id}")

    vtt_path = VTT_DIR / f"{video_id}.vtt"
    if vtt_path.exists() and vtt_path.stat().st_size > 32:
        return {
            "video_id": video_id,
            "cached": True,
            "vtt_path": str(vtt_path),
        }

    VTT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = VTT_DIR / f"{video_id}.vtt.tmp"

    from faster_whisper import WhisperModel

    print(f"Loading {model_name} model...", file=sys.stderr)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    print(f"Transcribing {audio_path.name}...", file=sys.stderr)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        vad_filter=True,
    )

    segs = []
    try:
        with open(tmp_path, "w") as f:
            f.write("WEBVTT\n\n")
            i = 0
            for seg in segments_iter:
                i += 1
                f.write(f"{i}\n")
                f.write(f"{_ms_to_vtt(int(seg.start * 1000))} --> "
                        f"{_ms_to_vtt(int(seg.end * 1000))}\n")
                f.write(f"{seg.text.strip()}\n\n")
                segs.append({"start": round(seg.start, 2),
                             "end": round(seg.end, 2),
                             "text": seg.text.strip()})
                if i % 100 == 0:
                    print(f"  ...{i} segments", file=sys.stderr)
        tmp_path.replace(vtt_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return {
        "video_id": video_id,
        "duration_sec": round(info.duration, 1),
        "segments": len(segs),
        "vtt_path": str(vtt_path),
    }


def _ms_to_vtt(ms: int) -> str:
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"