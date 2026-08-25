"""Tests for houchen_asr local transcription module."""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import houchen_asr  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def houchen_db(tmp_path):
    """In-memory houchen DB with minimal video + collection schema."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript("""
        CREATE TABLE video (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            content_kind TEXT NOT NULL
        );
        CREATE TABLE video_collection (
            collection_id TEXT PRIMARY KEY,
            collection_name TEXT NOT NULL CHECK(collection_name IN ('videos','streams','shorts'))
        );
        CREATE TABLE video_collection_membership (
            video_id TEXT NOT NULL,
            collection_id TEXT NOT NULL,
            PRIMARY KEY (video_id, collection_id)
        );
        INSERT INTO video_collection VALUES ('c_videos', 'videos');
        INSERT INTO video_collection VALUES ('c_streams', 'streams');
        INSERT INTO video_collection VALUES ('c_shorts', 'shorts');
    """)
    yield c
    c.close()


def _add_video(c, video_id, collection):
    c.execute("INSERT INTO video VALUES (?, ?, ?)",
              (video_id, "Test", "video"))
    cid = {"videos": "c_videos", "streams": "c_streams",
           "shorts": "c_shorts"}[collection]
    c.execute("INSERT INTO video_collection_membership VALUES (?, ?)",
              (video_id, cid))
    c.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIsShort:
    def test_short_detected(self, houchen_db, tmp_path):
        _add_video(houchen_db, "v_short1", "shorts")
        # Write to disk to satisfy is_short
        db_path = tmp_path / "houchen.sqlite3"
        disk = sqlite3.connect(str(db_path))
        for row in houchen_db.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
            disk.execute(row[0])
        for row in houchen_db.execute("SELECT * FROM video"):
            disk.execute("INSERT INTO video VALUES (?,?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection"):
            disk.execute("INSERT INTO video_collection VALUES (?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection_membership"):
            disk.execute("INSERT INTO video_collection_membership VALUES (?,?)", row)
        disk.commit()

        assert houchen_asr.is_short("v_short1", db_path) is True

    def test_stream_not_short(self, houchen_db, tmp_path):
        _add_video(houchen_db, "v_stream1", "streams")
        db_path = tmp_path / "houchen.sqlite3"
        disk = sqlite3.connect(str(db_path))
        for row in houchen_db.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
            disk.execute(row[0])
        for row in houchen_db.execute("SELECT * FROM video"):
            disk.execute("INSERT INTO video VALUES (?,?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection"):
            disk.execute("INSERT INTO video_collection VALUES (?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection_membership"):
            disk.execute("INSERT INTO video_collection_membership VALUES (?,?)", row)
        disk.commit()

        assert houchen_asr.is_short("v_stream1", db_path) is False


class TestFindAudio:
    def test_finds_webm(self, tmp_path):
        audio_dir = tmp_path / "asr" / "audio"
        audio_dir.mkdir(parents=True)
        (audio_dir / "v1.webm").write_bytes(b"")
        # Monkeypatch AUDIO_DIR
        orig = houchen_asr.AUDIO_DIR
        houchen_asr.AUDIO_DIR = audio_dir
        try:
            assert houchen_asr.find_audio("v1") == audio_dir / "v1.webm"
        finally:
            houchen_asr.AUDIO_DIR = orig

    def test_returns_none_for_missing(self, tmp_path):
        orig = houchen_asr.AUDIO_DIR
        houchen_asr.AUDIO_DIR = tmp_path
        try:
            assert houchen_asr.find_audio("nonexistent") is None
        finally:
            houchen_asr.AUDIO_DIR = orig


class TestEmptyVttNotCached:
    def test_tiny_vtt_not_treated_as_cache(self, tmp_path):
        p = tmp_path / "E9uJV2bwzjM.vtt"
        p.write_text("")
        assert not (p.exists() and p.stat().st_size > 32)


class TestMsToVtt:
    def test_basic(self):
        assert houchen_asr._ms_to_vtt(0) == "00:00:00.000"
        assert houchen_asr._ms_to_vtt(1000) == "00:00:01.000"
        assert houchen_asr._ms_to_vtt(3661001) == "01:01:01.001"


class TestTranscribeShortGuard:
    """The transcribe function MUST refuse shorts."""

    def test_short_raises(self, houchen_db, tmp_path):
        _add_video(houchen_db, "v_short1", "shorts")
        db_path = tmp_path / "houchen.sqlite3"
        disk = sqlite3.connect(str(db_path))
        for row in houchen_db.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
            disk.execute(row[0])
        for row in houchen_db.execute("SELECT * FROM video"):
            disk.execute("INSERT INTO video VALUES (?,?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection"):
            disk.execute("INSERT INTO video_collection VALUES (?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection_membership"):
            disk.execute("INSERT INTO video_collection_membership VALUES (?,?)", row)
        disk.commit()
        disk.close()

        with pytest.raises(RuntimeError, match="REFUSED.*short"):
            houchen_asr.transcribe("v_short1", houchen_db=db_path)

    def test_missing_audio_raises(self, houchen_db, tmp_path):
        _add_video(houchen_db, "v_stream1", "streams")
        db_path = tmp_path / "houchen.sqlite3"
        disk = sqlite3.connect(str(db_path))
        for row in houchen_db.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
            disk.execute(row[0])
        for row in houchen_db.execute("SELECT * FROM video"):
            disk.execute("INSERT INTO video VALUES (?,?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection"):
            disk.execute("INSERT INTO video_collection VALUES (?,?)", row)
        for row in houchen_db.execute("SELECT * FROM video_collection_membership"):
            disk.execute("INSERT INTO video_collection_membership VALUES (?,?)", row)
        disk.commit()
        disk.close()

        # AUDIO_DIR points to empty tmp_path
        orig = houchen_asr.AUDIO_DIR
        houchen_asr.AUDIO_DIR = tmp_path
        try:
            with pytest.raises(RuntimeError, match="audio not found"):
                houchen_asr.transcribe("v_stream1", houchen_db=db_path)
        finally:
            houchen_asr.AUDIO_DIR = orig