"""Acquisition tests for the Hou Chen corpus (PR-1, hardened).

Uses the contract-faithful fake_ytdlp.py via scripts/houchen_fixtures/scenario.py.
Every test that claims "no download" / "no media" asserts on the OBSERVED
call log, not the response script (P1-7).
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_acquisition as acq
import houchen_migrations
import houchen_paths
import houchen_schema
import houchen_store
from houchen_fixtures.scenario import (  # noqa: E402
    make_runner, write_scenario, playlist_call, info_call, download_call,
    observed_calls, assert_no_media_flags, JSON3_BODY, VTT_BODY,
)


@pytest.fixture
def scratch_root():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("HOUCHEN_DATA_ROOT")
        os.environ["HOUCHEN_DATA_ROOT"] = tmp
        try:
            yield tmp
        finally:
            if old is None:
                os.environ.pop("HOUCHEN_DATA_ROOT", None)
            else:
                os.environ["HOUCHEN_DATA_ROOT"] = old


@pytest.fixture
def conn(scratch_root):
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    houchen_migrations.ensure_schema(c)
    yield c
    c.close()


def _seed_video(c, vid="aaaaaaaaaaa", availability="public"):
    c.execute(
        "INSERT INTO video(video_id, title, discovered_at, last_seen_at,"
        " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?,?)",
        (vid, "t", "t", "t", "c" * 64, availability, "video"))


def _seed_run(c, run_id):
    c.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run_id, "caption_fetch", "t", "running", "z" * 64, "{}"))
    c.commit()


def _info_with_subtitle(lang="zh-Hans", kind="manual", fmt="vtt"):
    return {
        "id": "aaaaaaaaaaa",
        "subtitles" if kind == "manual" else "automatic_captions": {
            lang: [{"ext": fmt, "url": "https://example/signed?v=1"}],
        },
    }


# ---------------------------------------------------------------------------
# Real contract: playlist / info / JSON3 / output naming
# ---------------------------------------------------------------------------

def test_playlist_entries_contract(scratch_root):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [playlist_call([{"id": "aaaaaaaaaaa", "title": "x"}])])
    entries = acq.playlist_entries("https://youtube.com/@c/videos",
                                   runner=make_runner(scen))
    assert entries == [{"id": "aaaaaaaaaaa", "title": "x"}]


def test_playlist_rejects_top_level_array(scratch_root):
    """The old bug: expecting a top-level JSON array. We now require entries."""
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [{
        "argv_prefix": ["yt-dlp", "--flat-playlist", "-J"],
        "exit_code": 0, "stdout": json.dumps([{"id": "x"}]), "stderr": "",
    }])
    with pytest.raises(acq.PermanentError, match="entries"):
        acq.playlist_entries("https://youtube.com/@c/videos",
                             runner=make_runner(scen))


def test_info_json_and_subtitle_tracks(scratch_root):
    scen = os.path.join(scratch_root, "scen")
    info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt"}]},
        "automatic_captions": {"zh": [{"ext": "json3"}]},
    }
    write_scenario(scen, [info_call(info)])
    got = acq.info_json("aaaaaaaaaaa", runner=make_runner(scen))
    tracks = acq.subtitle_tracks_from_info(got)
    kinds = {(t.language, t.caption_kind, t.format) for t in tracks}
    assert ("zh-Hans", "manual", "vtt") in kinds
    assert ("zh", "auto", "json3") in kinds


def test_json3_events_segs_contract():
    text = json.dumps({"events": [{"segs": [{"utf8": "中央政治局"}]},
                                  {"segs": [{"utf8": "第二个"}]}]}, ensure_ascii=False)
    assert acq._parse_json3(text) == 2


def test_json3_rejects_zero_cues():
    with pytest.raises(acq.PermanentError, match="zero non-empty"):
        acq._parse_json3(json.dumps({"events": []}))


# ---------------------------------------------------------------------------
# Selection rules (unchanged logic)
# ---------------------------------------------------------------------------

def test_select_manual_over_auto_and_language_and_format():
    tracks = [
        acq.SubtitleTrack("zh", "auto", "vtt"),
        acq.SubtitleTrack("zh-Hans", "manual", "vtt"),
        acq.SubtitleTrack("zh-Hans", "manual", "json3"),
    ]
    chosen = acq.select_subtitle(tracks)
    assert (chosen.caption_kind, chosen.language, chosen.format) == \
        ("manual", "zh-Hans", "json3")


def test_select_no_chinese_returns_none():
    assert acq.select_subtitle([acq.SubtitleTrack("en", "manual", "vtt")]) is None


# ---------------------------------------------------------------------------
# Redaction (P0-3)
# ---------------------------------------------------------------------------

def test_redact_strips_secrets():
    dirty = ("ERROR https://www.youtube.com/api/timedtext?signature=ABCDEF123456 "
             "Authorization: Bearer supersecrettoken "
             "cookie=sessionid=abc123 /Users/kjonekong/secret/path")
    clean = acq.redact(dirty)
    assert "signature=" not in clean
    assert "supersecrettoken" not in clean
    assert "Bearer" not in clean
    assert "/Users/kjonekong" not in clean
    assert "<redacted" in clean


def test_truncate_stderr_redacts():
    raw = b"sign in to confirm\nhttps://youtube.com/api?signature=DEADBEEF\n"
    text = acq._truncate_stderr(raw)
    assert "signature=" not in text
    assert "<redacted-url>" in text


# ---------------------------------------------------------------------------
# no-replace install + verify_frozen_raw (P0-1)
# ---------------------------------------------------------------------------

def test_install_content_addressed_no_replace(scratch_root):
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target, created = acq.install_content_addressed(src, sha, "vtt")
    assert created is True
    assert os.path.exists(target)
    # Re-install same content → reuse, not overwrite (bytes/mtime unchanged).
    mtime = os.stat(target).st_mtime_ns
    src2 = os.path.join(scratch_root, "src2.vtt")
    with open(src2, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    target2, created2 = acq.install_content_addressed(src2, sha, "vtt")
    assert created2 is False
    assert target2 == target
    assert os.stat(target).st_mtime_ns == mtime


def test_install_content_addressed_rejects_mismatch(scratch_root):
    houchen_store.ensure_dirs()
    # Pre-create a target with content A under a sha that belongs to content B.
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target, _ = acq.install_content_addressed(src, sha, "vtt")
    # Corrupt the target.
    with open(target, "w", encoding="utf-8") as f:
        f.write("corrupted")
    # Now install a file whose sha equals `sha` again → mismatch → error.
    src2 = os.path.join(scratch_root, "src2.vtt")
    with open(src2, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    with pytest.raises(acq.RawIntegrityError, match="mismatched SHA"):
        acq.install_content_addressed(src2, sha, "vtt")


def test_verify_frozen_raw_detects_tamper_and_symlink(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn)
    src = os.path.join(scratch_root, "s.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target, _ = acq.install_content_addressed(src, sha, "vtt")
    conn.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("aaaaaaaaaaa", "zh-Hans", "manual", "vtt", sha, target,
         os.path.getsize(target), 1, "t", "yt", "c" * 64))
    conn.commit()
    assert acq.verify_frozen_raw(conn, "aaaaaaaaaaa") is not None

    # Tamper: overwrite the first byte in place (same size) so the SHA branch
    # fires (not the size-mismatch branch).
    with open(target, "r+b") as f:
        first = f.read(1)
        f.seek(0)
        f.write(b"X" if first != b"X" else b"Y")
    with pytest.raises(acq.RawIntegrityError, match="SHA mismatch"):
        acq.verify_frozen_raw(conn, "aaaaaaaaaaa")
    # Restore.
    with open(target, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)

    # Symlink escape: replace the file with a symlink.
    os.remove(target)
    link_dest = os.path.join(scratch_root, "outside.vtt")
    with open(link_dest, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    os.symlink(link_dest, target)
    with pytest.raises(acq.RawIntegrityError, match="not a regular file"):
        acq.verify_frozen_raw(conn, "aaaaaaaaaaa")

    # Deletion: file gone → lstat fails → RawIntegrityError.
    os.remove(target)  # remove the symlink itself
    with pytest.raises(acq.RawIntegrityError, match="lstat failed"):
        acq.verify_frozen_raw(conn, "aaaaaaaaaaa")


def test_install_content_addressed_fsync_failure_no_install(scratch_root, monkeypatch):
    """P0-1 durability: a file-fsync failure must abort BEFORE install, so no
    content-addressed target (and transitively no raw row) is ever created."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")

    def _boom(_fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(acq.os, "fsync", _boom)
    with pytest.raises(OSError, match="injected fsync"):
        acq.install_content_addressed(src, sha, "vtt")
    assert not os.path.exists(target)
    assert os.path.exists(src)  # source untouched (not installed/moved)


def test_install_content_addressed_rejects_symlink_target(scratch_root):
    """P0-3: a symlink at the target (even with matching content) is rejected."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    link_dest = os.path.join(scratch_root, "dest.vtt")
    with open(link_dest, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)  # same content → same sha
    os.symlink(link_dest, target)
    with pytest.raises(acq.RawIntegrityError, match="not a regular file"):
        acq.install_content_addressed(src, sha, "vtt")


def test_install_content_addressed_rejects_directory_target(scratch_root):
    """P0-3: a directory at the target is rejected (never installed over)."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")
    os.makedirs(target, exist_ok=True)  # target is a directory
    with pytest.raises(acq.RawIntegrityError, match="not a regular file"):
        acq.install_content_addressed(src, sha, "vtt")


def test_install_content_addressed_rejects_fifo_target(scratch_root):
    """P0-3: a FIFO at the target is rejected (never installed over)."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.mkfifo(target)
    with pytest.raises(acq.RawIntegrityError, match="not a regular file"):
        acq.install_content_addressed(src, sha, "vtt")


def test_install_content_addressed_hardlink_fail_racing_target_untouched(
        scratch_root, monkeypatch):
    """P0-3: hard-link unsupported + a racing competitor's target appearing in
    the window: the competitor's bytes are NEVER overwritten (no rename
    fallback) and the install fails closed."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")

    def _boom(s, d):
        # A competitor installs a target, THEN our link fails (EXDEV).
        with open(d, "wb") as f:
            f.write(b"competitor bytes")
        raise OSError(18, "cross-device link")

    monkeypatch.setattr(acq.os, "link", _boom)
    with pytest.raises(acq.RawIntegrityError, match="no-replace install failed"):
        acq.install_content_addressed(src, sha, "vtt")
    with open(target, "rb") as f:
        assert f.read() == b"competitor bytes"  # untouched


def test_install_content_addressed_hardlink_failure_fails_closed(scratch_root, monkeypatch):
    """P0-3: when hard-link is unsupported (EXDEV), install FAILS CLOSED — it
    never falls back to a plain rename that could overwrite a racing target."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")

    def _boom_link(src, dst):
        raise OSError(18, "cross-device link")

    monkeypatch.setattr(acq.os, "link", _boom_link)
    with pytest.raises(acq.RawIntegrityError, match="no-replace install failed"):
        acq.install_content_addressed(src, sha, "vtt")
    assert not os.path.exists(target)
    assert os.path.exists(src)  # source untouched


def test_install_content_addressed_dir_fsync_failure(scratch_root, monkeypatch):
    """P0-4: a directory-fsync failure propagates (not swallowed) so the
    caller never writes a raw row. The already-linked file is an allowed orphan."""
    houchen_store.ensure_dirs()
    src = os.path.join(scratch_root, "src.vtt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(VTT_BODY)
    sha = acq.sha256_file(src)
    target = houchen_paths.caption_target_path(sha, "vtt")

    def _boom_dir(path):
        raise OSError(5, "injected dir fsync EIO")

    monkeypatch.setattr(acq, "_fsync_dir", _boom_dir)
    with pytest.raises(OSError, match="EIO"):
        acq.install_content_addressed(src, sha, "vtt")
    assert os.path.exists(target)  # installed but not reported durable


def test_freeze_dir_fsync_failure_no_raw_row(scratch_root, conn, monkeypatch):
    """P0-4: a directory-fsync failure during freeze aborts BEFORE the raw
    INSERT, so no raw_caption row is written."""
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = _freeze_scenario(scratch_root)

    def _boom_dir(path):
        raise OSError(5, "injected dir fsync EIO")

    monkeypatch.setattr(acq, "_fsync_dir", _boom_dir)
    with pytest.raises(OSError):
        acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert conn.execute("SELECT COUNT(*) FROM raw_caption").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Freeze: atomicity, concurrency, no second download
# ---------------------------------------------------------------------------

def _freeze_scenario(scratch_root, vid="aaaaaaaaaaa", info=None):
    scen = os.path.join(scratch_root, "scen")
    info = info or _info_with_subtitle()
    write_scenario(scen, [
        info_call(info),
        download_call("zh-Hans"),
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    return scen


def test_freeze_first_run_and_rerun_noop(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = _freeze_scenario(scratch_root)
    r1 = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                        runner=make_runner(scen), yt_version="2026.01")
    assert r1.outcome == acq.OUT_SUCCESS

    row = conn.execute(
        "SELECT content_sha256, local_path FROM raw_caption WHERE video_id=?",
        ("aaaaaaaaaaa",)).fetchone()
    assert os.path.exists(row["local_path"])
    mtime = os.stat(row["local_path"]).st_mtime_ns

    # rerun: must verify integrity and return skipped WITHOUT a second download.
    r2 = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                        runner=make_runner(scen), yt_version="2026.01")
    assert r2.outcome == acq.OUT_SKIPPED
    assert os.stat(row["local_path"]).st_mtime_ns == mtime

    obs = observed_calls(scen)
    downloads = [c for c in obs if "--write-subs" in c["argv"]]
    # info (dump-json) + download happened once, then rerun short-circuited.
    assert len(downloads) == 1


def test_freeze_concurrent_first_freeze_one_winner(scratch_root):
    """P0-1: two INDEPENDENT connections, barrier-synchronized, first-freeze the
    same video at the same time. Exactly one wins; the loser reuses (never
    deletes) the winner's content-addressed file and reports skipped/race_lost."""
    import threading
    houchen_store.ensure_dirs()
    db = os.path.join(scratch_root, "freeze.sqlite3")
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    houchen_migrations.ensure_schema(c)
    _seed_video(c)
    _seed_run(c, "hcrun_r1")
    c.commit()
    c.close()

    # Identical per-worker scenario dirs → same subtitle content → same sha →
    # same content-addressed target. Isolating the scenario avoids a fake state
    # race, so only the install + DB INSERT race is exercised.
    scen_a = os.path.join(scratch_root, "scen_a")
    scen_b = os.path.join(scratch_root, "scen_b")
    for s in (scen_a, scen_b):
        write_scenario(s, [info_call(_info_with_subtitle()), download_call()],
                       subs={"zh-Hans": ("vtt", VTT_BODY)})

    barrier = threading.Barrier(2)
    results = []

    def worker(scen):
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        barrier.wait(timeout=30)
        try:
            r = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                               runner=make_runner(scen), yt_version="y")
            results.append(("ok", r.outcome))
        except Exception as e:  # noqa: BLE001
            import traceback
            results.append(("exc", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
        finally:
            conn.close()

    t1 = threading.Thread(target=worker, args=(scen_a,))
    t2 = threading.Thread(target=worker, args=(scen_b,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results) == 2, results
    assert [tag for tag, _ in results] == ["ok", "ok"], results
    assert sorted(s for _, s in results) == [acq.OUT_SKIPPED, acq.OUT_SUCCESS]

    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT local_path, content_sha256 FROM raw_caption"
                    " WHERE video_id=?", ("aaaaaaaaaaa",)).fetchone()
    assert row is not None
    assert os.path.exists(row["local_path"])
    assert acq.sha256_file(row["local_path"]) == row["content_sha256"]
    # Exactly ONE caption file under raw/captions (winner's file, not deleted).
    cap_root = houchen_paths.raw_captions_dir()
    files = [os.path.join(d, f) for d, _, fs in os.walk(cap_root) for f in fs]
    assert len(files) == 1
    # No temp residue from either worker.
    tmp_root = houchen_paths.raw_tmp_dir()
    if os.path.isdir(tmp_root):
        assert os.listdir(tmp_root) == []
    c.close()


def test_freeze_missing_when_no_chinese(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [info_call({
        "subtitles": {"en": [{"ext": "vtt"}]},
        "automatic_captions": {},
    })], subs={})
    r = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert r.outcome == acq.OUT_MISSING


def test_freeze_unavailable_video(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn, availability="private")
    _seed_run(conn, "hcrun_r1")
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [info_call(_info_with_subtitle())])
    r = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert r.outcome == acq.OUT_UNAVAILABLE


def test_freeze_un_cataloged_video_no_fk_violation(scratch_root, conn):
    """Explicit valid-format but un-cataloged video → structured missing, no FK."""
    houchen_store.ensure_dirs()
    _seed_run(conn, "hcrun_r1")
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [info_call(_info_with_subtitle())])
    r = acq.freeze_one(conn, "zzzzzzzzzzz", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert r.outcome == acq.OUT_MISSING
    assert r.error_class == "video_not_cataloged"
    # No attempt row was created that violates FK.
    assert conn.execute(
        "SELECT COUNT(*) FROM corpus_attempt WHERE video_id='zzzzzzzzzzz'"
    ).fetchone()[0] == 0


def test_freeze_auth_required_classified(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [{
        "argv_prefix": ["yt-dlp", "--skip-download", "--dump-json"],
        "exit_code": 1,
        "stderr": "Sign in to confirm you're not a bot. https://x/api?signature=SECRET",
        "stdout": "",
    }])
    r = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert r.outcome == acq.OUT_AUTH_REQUIRED
    # Secret must not persist in the attempt detail.
    detail = conn.execute(
        "SELECT detail FROM corpus_attempt WHERE video_id='aaaaaaaaaaa'"
        " AND stage='freeze' ORDER BY occurred_at DESC LIMIT 1").fetchone()[0]
    assert "SECRET" not in (detail or "")
    assert "signature=" not in (detail or "")


def test_observed_call_log_no_media_flags(scratch_root, conn):
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = _freeze_scenario(scratch_root)
    acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                   runner=make_runner(scen), yt_version="y")
    assert_no_media_flags(observed_calls(scen))
    # No media FILE was written anywhere under the data root (P1-1).
    root = houchen_paths.resolve_data_root()
    media_ext = (".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".opus", ".aac", ".flv")
    for d, _, fs in os.walk(root):
        for f in fs:
            assert not f.lower().endswith(media_ext), f"media file written: {f}"


# ---------------------------------------------------------------------------
# Hostile inputs
# ---------------------------------------------------------------------------

def test_hostile_video_id_rejected():
    for bad in ("../../outside", "$(rm -rf /)", "aaaaaaaaaaa;ls", "short"):
        with pytest.raises(acq.PermanentError):
            acq.info_json(bad)


def test_caption_target_path_rejects_bad_inputs():
    with pytest.raises(houchen_paths.DataRootError):
        houchen_paths.caption_target_path("not-hex", "vtt")
    with pytest.raises(houchen_paths.DataRootError):
        houchen_paths.caption_target_path("a" * 64, "../vtt")


def test_classify_exit_mapping():
    """classify_exit maps 101 → retryable; tool errors → tool_error."""
    assert acq.classify_exit(101, "some network error") == acq.OUT_RETRYABLE
    assert acq.classify_exit(1, "unrecognized") == acq.OUT_TOOL_ERROR
    assert acq.classify_exit(0, "") == acq.OUT_SUCCESS


# ---------------------------------------------------------------------------
# P2-3: active resource limits — subprocess timeout + overflow kill the group
# ---------------------------------------------------------------------------

def test_run_bounded_timeout_kills_group():
    """An actual subprocess timeout raises TimeoutExpired (not a hang)."""
    code = "import time; time.sleep(60)"
    argv = [sys.executable, "-c", code]
    with pytest.raises(subprocess.TimeoutExpired):
        acq._run_bounded(argv, timeout_sec=0.3)


def test_run_bounded_kills_on_stderr_overflow():
    """stderr flooding past the limit kills the group and raises a stable
    ResourceLimitError (P2-3), not a misleading timeout."""
    code = "import sys; [sys.stderr.write('x' * 4096) for _ in range(100000)]"
    argv = [sys.executable, "-c", code]
    with pytest.raises(acq.ResourceLimitError, match="stderr"):
        acq._run_bounded(argv, timeout_sec=30, stderr_limit=1024)


def test_run_bounded_kills_on_stdout_overflow():
    code = "import sys; [sys.stdout.write('y' * 4096) for _ in range(100000)]"
    argv = [sys.executable, "-c", code]
    with pytest.raises(acq.ResourceLimitError, match="stdout"):
        acq._run_bounded(argv, timeout_sec=30, stdout_limit=1024)


def test_run_bounded_watch_path_byte_limit(tmp_path):
    """A watched output file exceeding byte_limit kills the whole process
    group during the run (P2-3) — not after it finishes."""
    out_file = tmp_path / "out.bin"
    code = (
        "import time;"
        f"f=open({str(out_file)!r},'wb');"
        "[f.write(b'z'*65536) for _ in range(2000)];"
        "f.flush(); time.sleep(30)"
    )
    argv = [sys.executable, "-c", code]
    with pytest.raises(acq.ResourceLimitError, match="byte_limit"):
        acq._run_bounded(argv, timeout_sec=30, byte_limit=1024,
                         watch_path=str(out_file))


def test_freeze_manual_download_fails_falls_back_to_auto(scratch_root, conn):
    """P1-4: a high-priority manual json3 download failure must NOT abort the
    run; it records evidence and falls back to the auto vtt candidate."""
    houchen_store.ensure_dirs()
    _seed_video(conn)
    _seed_run(conn, "hcrun_r1")
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        info_call({
            "subtitles": {"zh-Hans": [{"ext": "json3"}]},
            "automatic_captions": {"zh-Hans": [{"ext": "vtt"}]},
        }),
        {"argv_prefix": ["yt-dlp", "--skip-download", "--write-subs"],
         "exit_code": 1, "stderr": "some download error", "stdout": ""},
        download_call("zh-Hans", auto=True),
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    r = acq.freeze_one(conn, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
    assert r.outcome == acq.OUT_SUCCESS
    assert r.caption_kind == "auto"
    # First candidate failure is observable in the attempt log.
    rows = conn.execute(
        "SELECT error_class FROM corpus_attempt"
        " WHERE video_id='aaaaaaaaaaa' AND stage='subtitle_download'"
        " ORDER BY occurred_at").fetchall()
    assert any(row["error_class"] == "download_failed" for row in rows)
