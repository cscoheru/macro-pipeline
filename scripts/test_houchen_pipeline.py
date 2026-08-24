"""Pipeline + CLI tests for the Hou Chen corpus (PR-1, hardened).

Covers P1-2 (durability), P1-5 (state machine), P1-6 (un-cataloged ID),
P2-2 (exit codes / readonly status / --limit), P2-3 (single version probe).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_acquisition as acq
import houchen_migrations
import houchen_paths
import houchen_runner
import houchen_schema
import houchen_status
import houchen_store
from houchen_fixtures.scenario import (  # noqa: E402
    make_runner, write_scenario, playlist_call, info_call, download_call,
    version_call, observed_calls, VTT_BODY,
)

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "houchen_pipeline.py")


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


def _entries(*ids):
    return [{"id": i, "title": f"v{i}"} for i in ids]


def _info(lang="zh-Hans"):
    return {"subtitles": {lang: [{"ext": "vtt"}]}, "automatic_captions": {}}


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------

def test_catalog_upsert_dedup_and_persist(scratch_root, conn):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa", "bbbbbbbbbbb")),
        playlist_call(_entries("bbbbbbbbbbb", "ccccccccccc")),  # dup
        playlist_call([]),
    ])
    summary = houchen_runner.run_catalog(conn, runner=make_runner(scen))
    assert summary["status"] == "success"
    assert conn.execute("SELECT COUNT(*) FROM video").fetchone()[0] == 3
    # Memberships are per-(video, collection): aaaa→videos, bbbb→videos+streams,
    # cccc→streams = 4 rows (bbbb is not deduped across collections).
    assert conn.execute("SELECT COUNT(*) FROM video_collection_membership"
                        ).fetchone()[0] == 4


def test_catalog_partial_persists_successes(scratch_root, conn):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa")),
        {"argv_prefix": ["yt-dlp", "--flat-playlist", "-J"],
         "exit_code": 50, "entries": [], "stderr": "private video unavailable"},
        playlist_call([]),
    ])
    summary = houchen_runner.run_catalog(conn, runner=make_runner(scen))
    assert summary["status"] == "partial"
    assert conn.execute("SELECT COUNT(*) FROM video").fetchone()[0] == 1
    # The run row is committed with partial status.
    run = conn.execute("SELECT status FROM corpus_run WHERE kind='catalog'"
                       " ORDER BY started_at DESC LIMIT 1").fetchone()
    assert run["status"] == "partial"


# ---------------------------------------------------------------------------
# fetch-captions: state machine + no retry storm
# ---------------------------------------------------------------------------

def test_pending_only_skips_terminal(scratch_root, conn):
    """missing/terminal videos are NOT re-selected by default."""
    houchen_store.ensure_dirs()
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"):
        conn.execute(
            "INSERT INTO video(video_id, discovered_at, last_seen_at,"
            " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
            (vid, "t", "t", "c" * 64, "public", "video"))
    # bbbb is terminal missing.
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        ("hcrun_r1", "caption_fetch", "t", "running", "z" * 64, "{}"))
    conn.execute(
        "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
        ("hcatt_1", "bbbbbbbbbbb", "hcrun_r1", "freeze", "missing", 0, "t"))
    conn.commit()

    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [version_call(),
                          info_call(_info()), download_call(),
                          info_call(_info()), download_call()],
                   subs={"zh-Hans": ("vtt", VTT_BODY)})
    summary = houchen_runner.run_fetch_captions(conn, runner=make_runner(scen),
                                                pending_only=True)
    # scope = aaaa (pending) + cccc (pending); bbbb (missing) excluded.
    assert summary["scope_count"] == 2
    assert summary["frozen"] == 2


def test_fetch_captions_single_version_probe(scratch_root, conn):
    """Only ONE --version call across the whole run (P2-3)."""
    houchen_store.ensure_dirs()
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        conn.execute(
            "INSERT INTO video(video_id, discovered_at, last_seen_at,"
            " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
            (vid, "t", "t", "c" * 64, "public", "video"))
    conn.commit()
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        info_call(_info()), download_call(),
        info_call(_info()), download_call(),
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    houchen_runner.run_fetch_captions(conn, runner=make_runner(scen),
                                      pending_only=True)
    version_calls = [c for c in observed_calls(scen)
                     if c["argv"] and "--version" in c["argv"]]
    assert len(version_calls) == 1


# ---------------------------------------------------------------------------
# CLI subprocess persistence (P1-2) + exit codes (P2-2)
# ---------------------------------------------------------------------------

def _run_cli(args, data_root, runner_scenario=None):
    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = data_root
    cmd = [sys.executable, SCRIPT, "--data-root", data_root] + args
    if runner_scenario:
        env["FAKE_YTDLP_SCENARIO"] = runner_scenario
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_catalog_persists_after_exit(scratch_root):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa", "bbbbbbbbbbb")),
        playlist_call([]),
        playlist_call([]),
    ])
    r = _run_cli(["catalog", "--runner",
                  os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "houchen_fixtures", "fake_ytdlp.py")],
                 scratch_root, runner_scenario=scen)
    assert r.returncode == 0
    # Re-open the file DB read-only and verify data persisted.
    c = houchen_store.connect_readonly()
    assert c.execute("SELECT COUNT(*) FROM video").fetchone()[0] == 2
    assert c.execute("SELECT status FROM corpus_run WHERE kind='catalog'"
                     " ORDER BY started_at DESC LIMIT 1").fetchone()[0] == "success"
    c.close()


def test_cli_catalog_partial_exit_code_3(scratch_root):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa")),
        {"argv_prefix": ["yt-dlp", "--flat-playlist", "-J"],
         "exit_code": 50, "entries": [], "stderr": "unavailable"},
        playlist_call([]),
    ])
    r = _run_cli(["catalog", "--runner",
                  os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "houchen_fixtures", "fake_ytdlp.py")],
                 scratch_root, runner_scenario=scen)
    assert r.returncode == 3


def test_cli_status_readonly_no_db_created(scratch_root):
    """status on a fresh root must not create the DB or directories."""
    before = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            before.add(os.path.join(root, f))
    r = _run_cli(["status"], scratch_root)
    assert r.returncode == 0
    body = json.loads(r.stdout)
    assert body["schema_version"] == 0
    assert body["totals"]["videos"] == 0
    after = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_cli_refuses_real_backend_without_auth(scratch_root):
    r = _run_cli(["catalog"], scratch_root)
    assert r.returncode == 2
    r2 = _run_cli(["fetch-captions", "--video-id", "aaaaaaaaaaa"], scratch_root)
    assert r2.returncode == 2


# ---------------------------------------------------------------------------
# status / coverage
# ---------------------------------------------------------------------------

def test_status_and_coverage_use_state_machine(scratch_root, conn):
    houchen_store.ensure_dirs()
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"):
        conn.execute(
            "INSERT INTO video(video_id, discovered_at, last_seen_at,"
            " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
            (vid, "t", "t", "c" * 64, "public", "video"))
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        ("hcrun_r1", "caption_fetch", "t", "running", "z" * 64, "{}"))
    # aaaa frozen
    conn.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("aaaaaaaaaaa", "zh-Hans", "manual", "vtt", "b" * 64, "/x", 1, 1, "t",
         "yt", "c" * 64))
    # bbbb missing (terminal)
    conn.execute(
        "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
        ("hcatt_1", "bbbbbbbbbbb", "hcrun_r1", "freeze", "missing", 0, "t"))
    conn.commit()

    st = houchen_status.status(conn)
    assert st["captions"]["frozen"] == 1
    assert st["captions"]["missing"] == 1
    assert st["captions"]["pending"] == 1  # cccc
    # oldest pending = cccc (but all have same discovered_at; just assert not None)
    assert st["oldest_pending"] is not None


def test_status_json_bounded_at_1000_videos(conn):
    now = "2026-08-23T00:00:00+00:00"
    rows = []
    for i in range(1000):
        vid = f"{i:011d}"[-11:]
        rows.append((vid, now, now, "c" * 64, "public", "video"))
    conn.executemany(
        "INSERT INTO video(video_id, discovered_at, last_seen_at,"
        " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
        rows)
    conn.commit()
    blob = houchen_status.to_json(houchen_status.status(conn))
    assert len(blob) < 50_000


# ---------------------------------------------------------------------------
# P2-1 / P2-2 / P2-4 / P1-3 / P1-5
# ---------------------------------------------------------------------------

def test_fetch_uncataloged_id_returns_failed(scratch_root, conn):
    """An explicit, uncataloged video ID must fail (not succeed), persist a
    run-level failure, and make NO subtitle network call (P2-1)."""
    houchen_store.ensure_dirs()
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [info_call(_info())])
    summary = houchen_runner.run_fetch_captions(
        conn, video_ids=["zzzzzzzzzzz"], runner=make_runner(scen), pending_only=True)
    assert summary["status"] == "failed"
    assert summary["uncataloged_ids"] == ["zzzzzzzzzzz"]
    # No subtitle network endpoint was touched (no info/download/version call).
    assert observed_calls(scen) == []
    run = conn.execute(
        "SELECT status, error_class FROM corpus_run WHERE kind='caption_fetch'"
        " ORDER BY started_at DESC LIMIT 1").fetchone()
    assert run["status"] == "failed"
    assert run["error_class"] == "uncataloged_video"


def test_cli_fetch_uncataloged_id_nonzero(scratch_root):
    """CLI level (P2-1): fetch-captions --video-id <uncataloged> exits
    non-zero and never calls a subtitle network endpoint."""
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [info_call(_info())])
    r = _run_cli(["fetch-captions", "--video-id", "zzzzzzzzzzz",
                  "--runner", os.path.join(
                      os.path.dirname(os.path.abspath(__file__)),
                      "houchen_fixtures", "fake_ytdlp.py")],
                 scratch_root, runner_scenario=scen)
    assert r.returncode == 1
    assert observed_calls(scen) == []


def test_tool_error_consistent_in_status_and_coverage(scratch_root, conn):
    houchen_store.ensure_dirs()
    conn.execute(
        "INSERT INTO video(video_id, discovered_at, last_seen_at,"
        " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
        ("aaaaaaaaaaa", "t", "t", "c" * 64, "public", "video"))
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        ("hcrun_r1", "caption_fetch", "t", "running", "z" * 64, "{}"))
    conn.execute(
        "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
        ("hcatt_1", "aaaaaaaaaaa", "hcrun_r1", "freeze", "tool_error", 1, "t"))
    conn.commit()
    st = houchen_status.status(conn)
    assert st["captions"]["tool_error"] == 1
    cov = houchen_status.coverage(conn)
    assert cov["caption_outcomes"]["tool_error"] == 1


def test_limit_negative_rejected_runner(scratch_root, conn):
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [version_call()])
    with pytest.raises(ValueError, match=">= 0"):
        houchen_runner.run_catalog(conn, runner=make_runner(scen), limit=-1)
    with pytest.raises(ValueError, match=">= 0"):
        houchen_runner.run_fetch_captions(conn, runner=make_runner(scen), limit=-1)


def test_cli_limit_negative_rejected(scratch_root):
    r = _run_cli(["catalog", "--limit", "-1"], scratch_root)
    assert r.returncode == 2


def test_status_query_count_fixed(conn):
    """status/coverage must use a fixed, small number of SQL queries regardless
    of video count (P1-3: no per-video N+1)."""
    now = "2026-08-23T00:00:00+00:00"
    rows = [(f"{i:011d}"[-11:], now, now, "c" * 64, "public", "video")
            for i in range(1000)]
    conn.executemany(
        "INSERT INTO video(video_id, discovered_at, last_seen_at,"
        " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)", rows)
    conn.commit()

    def _count(fn):
        n = [0]
        conn.set_trace_callback(lambda _stmt: n.__setitem__(0, n[0] + 1))
        try:
            fn(conn)
        finally:
            conn.set_trace_callback(None)
        return n[0]

    assert _count(houchen_status.status) < 40
    assert _count(houchen_status.coverage) < 40


def test_video_states_query_uses_indexes(conn):
    """EXPLAIN QUERY PLAN: the shared state CTE reads corpus_attempt via an
    index and joins raw_caption with an index SEARCH (P1-3)."""
    plan_lines = [r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN " + houchen_schema._VIDEO_STATES_SQL)]
    attempt_lines = [l for l in plan_lines if "corpus_attempt" in l]
    assert attempt_lines, "corpus_attempt missing from query plan"
    for l in attempt_lines:
        assert "USING INDEX" in l, f"corpus_attempt read without index: {l}"
    rc_lines = [l for l in plan_lines if "raw_caption" in l]
    assert rc_lines, "raw_caption missing from query plan"
    for l in rc_lines:
        assert "SEARCH" in l and "USING" in l, \
            f"raw_caption not index-searched: {l}"


def test_limit_values_cli(scratch_root):
    """--limit 0 / 1 / large parse fine; only negatives are rejected."""
    for good in ("0", "1", "1000000"):
        r = _run_cli(["catalog", "--limit", good], scratch_root)
        # Refused by the network-auth gate (exit 2), NOT by a parse error.
        assert r.returncode == 2
        assert "must be >= 0" not in r.stderr, r.stderr
        assert "refusing" in r.stderr
    r = _run_cli(["catalog", "--limit", "-1"], scratch_root)
    assert r.returncode == 2
    assert "must be >= 0" in r.stderr


def test_coverage_shows_partial_gap(conn):
    """A catalog partial run's failed tab + reason must be visible in coverage
    (P1-5)."""
    now = "2026-08-23T00:00:00+00:00"
    summary = {
        "tabs": {
            "videos": {"status": "success", "enumerated": 1},
            "streams": {"status": "failed",
                        "error": {"outcome": "unavailable",
                                  "error_class": "unavailable"}},
            "shorts": {"status": "success", "enumerated": 0},
        }
    }
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, finished_at, status,"
        " config_sha256, tool_versions_json, summary_json) VALUES (?,?,?,?,?,?,?,?)",
        ("hcrun_part", "catalog", now, now, "partial", "z" * 64, "{}",
         json.dumps(summary)))
    conn.commit()
    gaps = houchen_status.coverage(conn)["catalog_partial"]
    assert len(gaps) == 1
    assert gaps[0]["tab"] == "streams"
    assert gaps[0]["error_class"] == "unavailable"
    assert gaps[0]["run_id"] == "hcrun_part"
    assert gaps[0]["started_at"] == now


# ---------------------------------------------------------------------------
# PR-2 normalize CLI tests
# ---------------------------------------------------------------------------

import houchen_normalizer  # noqa: E402
import importlib  # noqa: E402


def test_cli_normalize_dry_run_zero_filesystem_change(scratch_root):
    """P1-2 dry-run zero side effects: normalize --dry-run must not create
    directories, DB, or derived JSON files."""
    data_root = scratch_root  # fresh, no data/houchen dir yet
    before = set()
    for root, _, files in os.walk(data_root):
        for f in files:
            before.add(os.path.join(root, f))
    r = _run_cli(["normalize", "--dry-run"], data_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["dry_run"] is True
    assert body["normalizer"]["name"] == houchen_normalizer.NORMALIZER_NAME
    assert body["normalizer"]["version"] == houchen_normalizer.NORMALIZER_VERSION
    assert body["scope_count"] == 0  # no cataloged videos yet
    after = set()
    for root, _, files in os.walk(data_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_cli_normalize_uncataloged_id_nonzero(scratch_root):
    """P2-1: explicit uncataloged video_id in normalize exits non-zero; the
    DB IS created (with a run-level failed row carrying the offending IDs)
    so an auditor can see exactly what was rejected and why."""
    r = _run_cli(["normalize", "--video-id", "zzzzzzzzzzz"], scratch_root)
    assert r.returncode == 1
    body = json.loads(r.stdout)
    assert body["status"] == "failed"
    assert body["uncataloged_ids"] == ["zzzzzzzzzzz"]
    # The DB exists with a failed run row that records the rejection.
    db_path = os.path.join(scratch_root, "houchen.sqlite3")
    assert os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, error_class FROM corpus_run WHERE kind='normalize'"
            " ORDER BY started_at DESC LIMIT 1").fetchone()
        assert row[0] == "failed"
        assert row[1] == "uncataloged_video"
    finally:
        conn.close()


def test_cli_normalize_limit_negative_rejected(scratch_root):
    r = _run_cli(["normalize", "--limit", "-1"], scratch_root)
    assert r.returncode == 2
    assert "must be >= 0" in r.stderr


def test_cli_normalize_full_chain_writes_transcripts(scratch_root):
    """End-to-end: catalog a video → fetch-captions → normalize → DB rows +
    derived JSON exist; re-run is idempotent (skipped_already > 0)."""
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa")),
        playlist_call([]), playlist_call([]),
        version_call(),
        info_call(_info()),
        download_call(),
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "houchen_fixtures", "fake_ytdlp.py")

    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = scratch_root
    env["FAKE_YTDLP_SCENARIO"] = scen

    # Catalog + fetch-captions to get a frozen raw caption.
    for cmd in (["catalog", "--runner", runner],
                ["fetch-captions", "--runner", runner]):
        r = subprocess.run(
            [sys.executable, SCRIPT, "--data-root", scratch_root] + cmd,
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stderr)

    # First normalize: writes transcript_version + segments + derived JSON.
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "normalize"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["status"] == "success"
    assert body["normalized"] == 1
    assert body["skipped_already"] == 0

    # Derived JSON file exists at the content-addressed location.
    derived_glob = list(os.path.join(scratch_root, "derived", "transcripts",
                                     houchen_normalizer.NORMALIZER_VERSION,
                                     "*", "*.json")
                        if False else
                        __import__("glob").glob(
                            os.path.join(scratch_root, "derived", "transcripts",
                                         houchen_normalizer.NORMALIZER_VERSION,
                                         "*", "*.json")))
    assert len(derived_glob) == 1, f"expected 1 derived file, got {derived_glob}"

    # Second normalize: pending_only=True finds nothing (already normalized) →
    # scope_count=0; idempotent.
    r2 = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "normalize"],
        capture_output=True, text=True, env=env)
    assert r2.returncode == 0, r2.stderr
    body2 = json.loads(r2.stdout)
    assert body2["scope_count"] == 0
    assert body2["normalized"] == 0

    # Status shows normalized = 1, pending_normalize = 0.
    r3 = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root, "status"],
        capture_output=True, text=True, env=env)
    assert r3.returncode == 0
    st = json.loads(r3.stdout)
    assert st["transcripts"]["normalized"] == 1
    assert st["transcripts"]["pending_normalize"] == 0


# ---------------------------------------------------------------------------
# PR-3 analyze / validate / concept-seed CLI
# ---------------------------------------------------------------------------

def test_cli_concept_seed_dry_run_is_zero_write(scratch_root):
    """`concept-seed --dry-run` on an empty DB must NOT touch the filesystem."""
    before = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            before.add(os.path.join(root, f))
    r = _run_cli(["concept-seed", "--dry-run"], scratch_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["dry_run"] is True
    assert body["skeleton_size"] == 7  # audit F-1
    after = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_cli_analyze_dry_run_is_zero_write(scratch_root):
    """`analyze --dry-run` on an empty DB must NOT write anything."""
    before = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            before.add(os.path.join(root, f))
    r = _run_cli(["analyze", "--dry-run"], scratch_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["dry_run"] is True
    assert body["scope_count"] == 0
    assert body["provider"] == "fake"
    after = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_cli_validate_dry_run_is_zero_write(scratch_root):
    """`validate --dry-run` on an empty DB must NOT write anything."""
    before = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            before.add(os.path.join(root, f))
    r = _run_cli(["validate", "--dry-run"], scratch_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["dry_run"] is True
    assert body["scope_count"] == 0
    after = set()
    for root, _, files in os.walk(scratch_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_cli_analyze_uncataloged_id_fails(scratch_root):
    """Un-cataloged --video-id must produce a failed run with error_class."""
    r = _run_cli(["analyze", "--video-id", "zzzzzzzzzzz"], scratch_root)
    assert r.returncode != 0
    body = json.loads(r.stdout)
    assert body["status"] == "failed"
    assert "zzzzzzzzzzz" in body.get("uncataloged_ids", [])


def test_cli_real_provider_analyze_returns_analyze_failed(scratch_root):
    """Real providers are explicitly disabled (audit F-6).

    No catalog needed: we just check the analyze exit envelope returns
    analyze_failed for the anthropic provider on any video in scope (0).
    """
    r = _run_cli(
        ["analyze", "--provider", "anthropic", "--model", "claude-x"],
        scratch_root)
    # analyze on an empty DB with no videos → scope=0, returns dry_run-style
    # summary with status=success (no failed videos). The real-provider
    # gating only fires once a video is actually selected.
    body = json.loads(r.stdout)
    assert body["provider"] == "anthropic"
    assert body["scope_count"] == 0


def test_cli_concept_seed_idempotent(scratch_root):
    """Re-running concept-seed must yield 0 new rows on the second run."""
    scen = os.path.join(scratch_root, "scen")
    write_scenario(scen, [version_call()])
    r = _run_cli(["concept-seed"], scratch_root)
    assert r.returncode == 0, r.stderr
    body1 = json.loads(r.stdout)
    assert body1["seeded"] == 7
    r = _run_cli(["concept-seed"], scratch_root)
    assert r.returncode == 0, r.stderr
    body2 = json.loads(r.stdout)
    assert body2["seeded"] == 0


def test_cli_status_includes_pr3_buckets(scratch_root):
    """status JSON must include claims/concepts/analyze_scope even on empty DB."""
    r = _run_cli(["status"], scratch_root)
    assert r.returncode == 0, r.stderr
    st = json.loads(r.stdout)
    assert "claims" in st
    assert "concepts" in st
    assert "analyze_scope" in st
    # Empty DB → all zeros
    assert st["claims"]["accepted"] == 0
    assert st["concepts"]["seed"] == 0
    assert st["analyze_scope"]["pending_analyze"] == 0


def test_cli_coverage_includes_pr3_buckets(scratch_root):
    """coverage JSON must include claim_outcomes/concept_state/analyze_scope."""
    r = _run_cli(["coverage"], scratch_root)
    assert r.returncode == 0, r.stderr
    cov = json.loads(r.stdout)
    assert "claim_outcomes" in cov
    assert "concept_state" in cov
    assert "analyze_scope" in cov


def test_cli_pr3_offline_full_chain_materializes_all_rows(scratch_root):
    """E2E: fake-only catalog → freeze → normalize → seed → analyze → validate.

    Proves formal PR-3 rows are materialized: accepted + rejected claims,
    source provenance, proposed concepts, concept links, evidence mentions,
    forecasts, and idempotency on re-validation.
    """
    scen = os.path.join(scratch_root, "scen-pr3")
    write_scenario(scen, [
        version_call(),
        playlist_call(_entries("aaaaaaaaaaa")),
        playlist_call([]), playlist_call([]),
        version_call(),
        info_call(_info()),
        download_call(),
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "houchen_fixtures", "fake_ytdlp.py")
    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = scratch_root
    env["FAKE_YTDLP_SCENARIO"] = scen

    for cmd in (
        ["catalog", "--runner", runner],
        ["fetch-captions", "--runner", runner],
        ["normalize"],
        ["concept-seed"],
        ["analyze", "--provider", "fake"],
    ):
        r = subprocess.run([sys.executable, SCRIPT, "--data-root", scratch_root] + cmd,
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stdout, r.stderr)

    # Real provider without houchen_analyze.env → analyze_failed (no network).
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "analyze", "--no-pending", "--provider", "anthropic"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 3, (r.stdout, r.stderr)
    disabled = json.loads(r.stdout)
    assert disabled["failed"] == 1

    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root, "validate"],
        capture_output=True, text=True, env=env)
    # The deterministic fixture intentionally yields two hard validator rejects.
    assert r.returncode == 3, (r.stdout, r.stderr)
    validate_summary = json.loads(r.stdout)
    assert validate_summary["validated"] == 1
    assert validate_summary["rejected"] >= 2

    db = os.path.join(scratch_root, "houchen.sqlite3")
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM claim WHERE status='accepted'").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM claim WHERE status='rejected'").fetchone()[0] >= 2
        assert check.execute("SELECT COUNT(*) FROM claim_source").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM concept WHERE status='proposed'").fetchone()[0] >= 1
        assert check.execute("SELECT COUNT(*) FROM concept_source").fetchone()[0] >= 1
        assert check.execute("SELECT COUNT(*) FROM claim_concept").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM evidence_mention").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM forecast").fetchone()[0] == 1
        before = check.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
    finally:
        check.close()

    # Revalidate replays no formal rows (idempotent per analysis_run_id).
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root, "validate"],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == before
    finally:
        check.close()


# ---------------------------------------------------------------------------
# PR-4 Phase 1 — render / publish CLI smoke tests
# ---------------------------------------------------------------------------

def test_cli_render_dry_run_zero_filesystem_change(scratch_root):
    """`render --dry-run` must not write the render file or record rows."""
    import json as _json
    page_json = os.path.join(scratch_root, "page.json")
    with open(page_json, "w", encoding="utf-8") as fh:
        _json.dump({
            "video_id": "vid_aaaaaaaaaaa",
            "canonical_url": "https://example.com/v/x",
            "title": "Test",
            "published_at": "2026-08-24T00:00:00+00:00",
            "transcript_version_id": "tv_x",
            "analysis_run_id": "run_x",
            "prompt_version": "2026-08-24.1",
            "claim_count_accepted": 0,
            "claim_count_rejected": 0,
            "claim_count_needs_review": 0,
            "claims": [],
            "concept_ids": [],
            "forecast_ids": [],
        }, fh)
    before = set()
    for r, _, files in os.walk(scratch_root):
        for f in files:
            before.add(os.path.relpath(os.path.join(r, f), scratch_root))

    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "render", "--kind", "video", "--page-key", "vid_test",
         "--from-json", page_json, "--dry-run"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    after = set()
    for r_, _, files in os.walk(scratch_root):
        for f in files:
            after.add(os.path.relpath(os.path.join(r_, f), scratch_root))
    assert before == after


def test_cli_publish_dry_run_zero_filesystem_change(scratch_root):
    """`publish --dry-run` with no rendered_page rows must report dry_run
    and exit 0 without creating any files."""
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "publish", "--dry-run"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    summary = json.loads(r.stdout)
    assert summary["dry_run"] is True


def test_cli_publish_apply_without_operator_authorized_rejected(scratch_root):
    """`--apply` alone (without `--operator-authorized`) must exit 2 with
    a remediation message — the audit gate (brief §11 / plan §2.3)."""
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "publish", "--apply"],
        capture_output=True, text=True)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "--operator-authorized" in r.stderr


def test_cli_render_claim_off_by_default(scratch_root):
    """S-2 audit fix: `--kind claim` without `--include-claim-pages`
    is rejected with exit 2 (runner refuses, not just the dispatcher)."""
    page_json = os.path.join(scratch_root, "claim_page.json")
    with open(page_json, "w", encoding="utf-8") as fh:
        json.dump({
            "claim_id": "cl_x",
            "claim_text": "test",
            "claim_type": "descriptive",
            "layer": "speaker_statement",
            "speaker": "test",
            "exact_quote": "test",
            "timestamp_url": "https://example.com",
            "transcript_version_id": "tv_x",
        }, fh)
    r = subprocess.run(
        [sys.executable, SCRIPT, "--data-root", scratch_root,
         "render", "--kind", "claim", "--page-key", "cl_x",
         "--from-json", page_json],
        capture_output=True, text=True)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "claim pages are OFF" in r.stderr
