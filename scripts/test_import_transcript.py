"""Tests for PR-5 P2b import-transcript module.

Covers:
  - Parsers: txt, vtt, srt
  - Import flow: success, idempotency, empty file
  - CLI smoke test
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import houchen_import_transcript  # noqa: E402
import houchen_migrations  # noqa: E402


SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "houchen_pipeline.py")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    houchen_migrations.ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def video(conn):
    """Insert a test video."""
    vid = "abcdefghijk"
    conn.execute(
        "INSERT INTO video (video_id, channel_id, channel_handle, "
        "canonical_url, title, description, published_at, "
        "content_kind, availability, discovered_at, last_seen_at, "
        "metadata_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (vid, "ch_test", "@test", "https://youtube.com/watch?v=" + vid,
         "Test Video", "", "2026-01-01T00:00:00Z",
         "video", "public", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
         "a" * 64),
    )
    conn.commit()
    return vid


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseTxt:
    def test_paragraphs(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        segs = houchen_import_transcript.parse_txt(text)
        assert len(segs) == 3
        assert segs[0]["text"] == "第一段。"
        assert segs[0]["start_ms"] == 0
        assert segs[0]["end_ms"] > 0
        assert segs[1]["start_ms"] == segs[0]["end_ms"]

    def test_single_block_splits_by_newline(self):
        text = "行一\n行二\n行三"
        segs = houchen_import_transcript.parse_txt(text)
        assert len(segs) == 3

    def test_empty_text(self):
        segs = houchen_import_transcript.parse_txt("")
        assert segs == []

    def test_whitespace_only(self):
        segs = houchen_import_transcript.parse_txt("  \n  \n  ")
        assert segs == []

    def test_timing_increases(self):
        text = "短\n\n" + "很长的段落" * 50
        segs = houchen_import_transcript.parse_txt(text)
        assert len(segs) == 2
        assert segs[1]["start_ms"] > segs[0]["start_ms"]
        # Longer text → longer duration
        assert segs[1]["end_ms"] - segs[1]["start_ms"] > \
               segs[0]["end_ms"] - segs[0]["start_ms"]


class TestParseVtt:
    def test_basic_vtt(self):
        text = """WEBVTT

00:00:01.000 --> 00:00:05.000
你好世界

00:00:06.000 --> 00:00:10.000
第二行"""
        segs = houchen_import_transcript.parse_vtt(text)
        assert len(segs) == 2
        assert segs[0]["start_ms"] == 1000
        assert segs[0]["end_ms"] == 5000
        assert segs[0]["text"] == "你好世界"

    def test_vtt_with_tags_stripped(self):
        text = """WEBVTT

00:00:01.000 --> 00:00:05.000
<c.colorCCCCCC>带标签</c>"""
        segs = houchen_import_transcript.parse_vtt(text)
        assert len(segs) == 1
        assert "带标签" in segs[0]["text"]
        assert "<c" not in segs[0]["text"]

    def test_empty_vtt(self):
        segs = houchen_import_transcript.parse_vtt("WEBVTT\n\n")
        assert segs == []


class TestParseSrt:
    def test_basic_srt(self):
        text = """1
00:00:01,000 --> 00:00:05,000
第一行字幕

2
00:00:06,000 --> 00:00:10,000
第二行字幕"""
        segs = houchen_import_transcript.parse_srt(text)
        assert len(segs) == 2
        assert segs[0]["start_ms"] == 1000
        assert segs[0]["text"] == "第一行字幕"
        assert segs[1]["start_ms"] == 6000

    def test_multiline_srt(self):
        text = """1
00:00:01,000 --> 00:00:05,000
第一行
第二行"""
        segs = houchen_import_transcript.parse_srt(text)
        assert len(segs) == 1
        assert "第一行 第二行" == segs[0]["text"]


# ---------------------------------------------------------------------------
# Import flow tests
# ---------------------------------------------------------------------------

class TestImportTranscript:
    def test_import_txt(self, conn, video, tmp_path, monkeypatch):
        """Import a .txt file creates transcript records."""
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "test.txt"
        f.write_text("段落一。\n\n段落二。", encoding="utf-8")

        result = houchen_import_transcript.import_transcript(
            conn, video, f)
        assert result["status"] == "success"
        assert result["segments"] == 2
        assert result["format"] == "txt"

        # Verify DB records
        tv = conn.execute(
            "SELECT * FROM transcript_version WHERE video_id=?",
            (video,)
        ).fetchone()
        assert tv is not None
        assert tv["normalizer_name"] == "wps_import"
        assert tv["status"] == "ok"

        segs = conn.execute(
            "SELECT COUNT(*) as cnt FROM transcript_segment "
            "WHERE transcript_version_id=?",
            (tv["transcript_version_id"],)
        ).fetchone()
        assert segs["cnt"] == 2

    def test_import_vtt(self, conn, video, tmp_path, monkeypatch):
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "test.vtt"
        f.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:05.000\n你好\n",
                      encoding="utf-8")

        result = houchen_import_transcript.import_transcript(
            conn, video, f)
        assert result["status"] == "success"
        assert result["segments"] == 1
        assert result["format"] == "vtt"

    def test_import_srt(self, conn, video, tmp_path, monkeypatch):
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "test.srt"
        f.write_text(
            "1\n00:00:01,000 --> 00:00:05,000\n字幕一\n\n"
            "2\n00:00:06,000 --> 00:00:10,000\n字幕二\n",
            encoding="utf-8")

        result = houchen_import_transcript.import_transcript(
            conn, video, f)
        assert result["status"] == "success"
        assert result["segments"] == 2

    def test_idempotent(self, conn, video, tmp_path, monkeypatch):
        """Re-importing same file returns already_imported."""
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "test.txt"
        f.write_text("同一段内容。", encoding="utf-8")

        r1 = houchen_import_transcript.import_transcript(conn, video, f)
        assert r1["status"] == "success"

        r2 = houchen_import_transcript.import_transcript(conn, video, f)
        assert r2["status"] == "already_imported"
        assert r2["transcript_version_id"] == r1["transcript_version_id"]

    def test_empty_file(self, conn, video, tmp_path, monkeypatch):
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        result = houchen_import_transcript.import_transcript(
            conn, video, f)
        assert result["status"] == "empty"

    def test_unsupported_format(self, conn, video, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_text("not a transcript")
        with pytest.raises(ValueError, match="Unsupported format"):
            houchen_import_transcript.import_transcript(conn, video, f)

    def test_segments_in_fts(self, conn, video, tmp_path, monkeypatch):
        """Imported segments should be searchable via FTS."""
        monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path / "hdata"))
        f = tmp_path / "test.txt"
        f.write_text("Searchable unique content here.", encoding="utf-8")

        houchen_import_transcript.import_transcript(conn, video, f)

        # Query FTS — use English for reliable tokenization
        rows = conn.execute(
            "SELECT * FROM transcript_fts WHERE transcript_fts MATCH 'Searchable'"
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class TestCLI:
    def test_import_transcript_cli(self, tmp_path):
        """CLI import-transcript with --data-root."""
        f = tmp_path / "cli_test.txt"
        f.write_text("CLI测试段落。\n\n第二段。", encoding="utf-8")

        env = os.environ.copy()
        env["HOUCHEN_DATA_ROOT"] = str(tmp_path / "hdata")

        # First need to set up a DB with the video
        import sqlite3 as _sqlite3
        db_dir = tmp_path / "hdata"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "houchen.sqlite3"
        c = _sqlite3.connect(str(db_path))
        c.execute("PRAGMA foreign_keys=ON")
        houchen_migrations.ensure_schema(c)
        c.execute(
            "INSERT INTO video (video_id, channel_id, channel_handle, "
            "canonical_url, title, description, published_at, "
            "content_kind, availability, discovered_at, last_seen_at, "
            "metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("abcdefghijk", "ch", "@h", "url", "T", "", "2026-01-01",
             "video", "public", "2026-01-01", "2026-01-01", "a" * 64),
        )
        c.commit()
        c.close()

        r = subprocess.run(
            [sys.executable, SCRIPT,
             "--data-root", str(db_dir),
             "import-transcript",
             "--video-id", "abcdefghijk",
             "--from-file", str(f)],
            capture_output=True, text=True, env=env,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        result = json.loads(r.stdout)
        assert result["status"] == "success"
        assert result["segments"] == 2
