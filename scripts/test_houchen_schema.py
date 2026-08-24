"""Schema + migration tests for the Hou Chen corpus (PR-1, hardened).

Verifies (P1-3):
    - empty DB migrates to LATEST_VERSION
    - migrations idempotent; schema_version append-only
    - wrong pre-existing same-named table does NOT advance the version
    - failed DDL rolls back fully (no partial tables / no version row)
    - two connections racing first migration: 100 rounds, both succeed,
      final version strictly [1]

Plus the frozen-raw triggers and FK (unchanged invariants).
"""
import os
import sqlite3
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import houchen_migrations
import houchen_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    houchen_migrations.ensure_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def test_empty_db_migrates_to_latest():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    houchen_migrations.ensure_schema(c)
    assert houchen_migrations.current_version(c) == houchen_schema.VERSION
    assert houchen_schema.validate_schema(c)
    c.close()


def test_migrations_repeated_is_noop():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    houchen_migrations.ensure_schema(c)
    rows = c.execute("SELECT version FROM schema_version").fetchall()
    houchen_migrations.ensure_schema(c)
    assert c.execute("SELECT version FROM schema_version").fetchall() == rows
    c.close()


def test_schema_version_append_only(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE schema_version SET description='x' WHERE version=1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM schema_version WHERE version=1")


def test_wrong_preexisting_table_does_not_advance_version():
    """A pre-existing `raw_caption(wrong)` must NOT let version reach 1."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("CREATE TABLE raw_caption (wrong TEXT)")
    with pytest.raises(sqlite3.DatabaseError, match="does not validate"):
        houchen_migrations.ensure_schema(c)
    assert houchen_migrations.current_version(c) == 0
    c.close()


def test_failed_ddl_rolls_back_fully(monkeypatch):
    """A genuinely broken DDL statement mid-migration must roll back the whole
    transaction: no tables and no version row remain (P1-3)."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    broken = (list(houchen_schema._V1_STATEMENTS[:3])
              + ["NOT A VALID STATEMENT",]
              + list(houchen_schema._V1_STATEMENTS[3:]))
    monkeypatch.setattr(houchen_schema, "_V1_STATEMENTS", broken)
    with pytest.raises(sqlite3.OperationalError):
        houchen_migrations.ensure_schema(c)
    assert houchen_migrations.current_version(c) == 0
    assert c.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0
    c.close()


# ---------------------------------------------------------------------------
# Exact schema validation (P1-1): wrong trigger body / index / FK / CHECK must
# all be rejected and must NOT advance the migration version.
# ---------------------------------------------------------------------------

def _fresh_v1_db():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    for stmt in houchen_schema._V1_STATEMENTS:
        c.execute(stmt)
    c.execute(
        "INSERT INTO schema_version(version, applied_at, description)"
        " VALUES (1, 't', 'x')")
    return c


def test_validate_schema_rejects_empty_trigger():
    """A same-named trigger whose body is `SELECT 1` (no RAISE(ABORT)) must
    fail validation — it cannot impersonate the frozen guard."""
    c = _fresh_v1_db()
    c.execute("DROP TRIGGER noguard_upd_raw_caption")
    c.execute("CREATE TRIGGER noguard_upd_raw_caption"
              " BEFORE UPDATE ON raw_caption BEGIN SELECT 1; END")
    assert houchen_schema.validate_schema(c) is False
    c.close()


def test_validate_schema_rejects_wrong_index_column():
    c = _fresh_v1_db()
    c.execute("DROP INDEX idx_attempt_outcome")
    c.execute("CREATE INDEX idx_attempt_outcome ON corpus_attempt(video_id)")
    assert houchen_schema.validate_schema(c) is False
    c.close()


def test_validate_schema_rejects_missing_fk():
    c = _fresh_v1_db()
    c.execute("DROP TABLE corpus_attempt")
    c.execute(
        "CREATE TABLE corpus_attempt ("
        " att_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,"
        " run_id TEXT NOT NULL, stage TEXT NOT NULL, outcome TEXT NOT NULL,"
        " error_class TEXT, detail TEXT, retryable INTEGER NOT NULL DEFAULT 0,"
        " occurred_at TEXT NOT NULL)")
    assert houchen_schema.validate_schema(c) is False
    c.close()


def test_validate_schema_rejects_wrong_check():
    c = _fresh_v1_db()
    c.execute("DROP TABLE raw_caption")
    c.execute(
        "CREATE TABLE raw_caption ("
        " video_id TEXT PRIMARY KEY REFERENCES video(video_id),"
        " language TEXT NOT NULL,"
        " caption_kind TEXT NOT NULL CHECK(caption_kind IN ('x','y')),"
        " format TEXT NOT NULL CHECK(format IN ('json3','vtt','srv1','srv2','srv3','ttml')),"
        " content_sha256 TEXT NOT NULL, local_path TEXT NOT NULL,"
        " byte_count INTEGER NOT NULL, cue_count INTEGER NOT NULL,"
        " fetched_at TEXT NOT NULL, yt_dlp_version TEXT NOT NULL,"
        " source_metadata_sha256 TEXT NOT NULL)")
    assert houchen_schema.validate_schema(c) is False
    c.close()


def test_concurrent_first_migration_100_rounds():
    """Two connections open a fresh file DB concurrently; both succeed;
    final version is exactly [1] and the schema validates."""
    for _ in range(100):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "mig.sqlite3")
            barrier = threading.Barrier(2)
            errors = []

            def worker():
                c = sqlite3.connect(db, timeout=30)
                c.execute("PRAGMA foreign_keys=ON")
                barrier.wait()
                try:
                    houchen_migrations.ensure_schema(c)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                finally:
                    c.close()

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start(); t2.start(); t1.join(); t2.join()

            assert errors == [], f"concurrent migration failed: {errors}"
            check = sqlite3.connect(db)
            check.execute("PRAGMA foreign_keys=ON")
            check.row_factory = sqlite3.Row
            versions = [r[0] for r in check.execute(
                "SELECT version FROM schema_version ORDER BY version").fetchall()]
            assert versions == [1, 2, 3]
            assert houchen_schema.validate_schema(check)
            check.close()


# ---------------------------------------------------------------------------
# Frozen raw triggers + FK (unchanged)
# ---------------------------------------------------------------------------

def _insert_video(c, vid="abcdefghijk"):
    c.execute(
        "INSERT INTO video(video_id, title, discovered_at, last_seen_at,"
        " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?,?)",
        (vid, "t", "t0", "t0", "a" * 64, "public", "video"))


def test_raw_caption_update_delete_rejected(conn):
    _insert_video(conn)
    conn.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("abcdefghijk", "zh-Hans", "manual", "vtt", "b" * 64, "/x.vtt",
         1, 1, "t", "yt", "c" * 64))
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        conn.execute("UPDATE raw_caption SET language='en' WHERE video_id='abcdefghijk'")
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        conn.execute("DELETE FROM raw_caption WHERE video_id='abcdefghijk'")


def test_raw_caption_video_id_unique(conn):
    _insert_video(conn)
    args = ("abcdefghijk", "zh-Hans", "manual", "vtt", "b" * 64, "/x.vtt",
            1, 1, "t", "yt", "c" * 64)
    conn.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        args)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
            " content_sha256, local_path, byte_count, cue_count, fetched_at,"
            " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("abcdefghijk", "zh-Hans", "manual", "json3", "d" * 64, "/y.json3",
             2, 2, "t", "yt", "c" * 64))


def test_corpus_attempt_fk_enforced(conn):
    _insert_video(conn)
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        ("hcrun_x", "catalog", "t", "running", "z" * 64, "{}"))
    # FK to a missing video
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
            " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
            ("hcatt_x", "zzzzzzzzzzz", "hcrun_x", "catalog", "success", 0, "t"))
    # FK to a missing run
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
            " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
            ("hcatt_y", "abcdefghijk", "hcrun_missing", "catalog", "success", 0, "t"))


def test_schema_validation_rejects_missing_column(conn):
    """validate_schema must be False if a table loses a column."""
    # Drop a column by recreating video without title (simulate corruption).
    conn.execute("DROP TABLE video")
    conn.execute(
        "CREATE TABLE video (video_id TEXT PRIMARY KEY, title TEXT)")
    assert houchen_schema.validate_schema(conn) is False


def test_run_and_attempt_id_prefix():
    rid = houchen_schema.new_run_id()
    aid = houchen_schema.new_attempt_id()
    assert rid.startswith("hcrun_") and len(rid) == 6 + 32
    assert aid.startswith("hcatt_") and len(aid) == 6 + 32


def test_state_machine_pending_retryable(conn):
    """is_pending: frozen/terminal are not pending; pending/retryable are."""
    _insert_video(conn, "aaaaaaaaaaa")
    _insert_video(conn, "bbbbbbbbbbb")
    _insert_video(conn, "ccccccccccc")
    _insert_video(conn, "ddddddddddd")
    run = "hcrun_x"
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run, "caption_fetch", "t", "running", "z" * 64, "{}"))
    # aaaa: frozen
    conn.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("aaaaaaaaaaa", "zh-Hans", "manual", "vtt", "b" * 64, "/x", 1, 1, "t",
         "yt", "c" * 64))
    # bbbb: missing (terminal)
    conn.execute(
        "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
        ("hcatt_1", "bbbbbbbbbbb", run, "freeze", "missing", 0, "t"))
    # cccc: retryable (re-selectable)
    conn.execute(
        "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage, outcome,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
        ("hcatt_2", "ccccccccccc", run, "freeze", "retryable", 1, "t"))
    conn.commit()

    assert houchen_schema.is_pending(conn, "aaaaaaaaaaa") is False  # frozen
    assert houchen_schema.is_pending(conn, "bbbbbbbbbbb") is False  # missing terminal
    assert houchen_schema.is_pending(conn, "ccccccccccc") is True   # retryable
    assert houchen_schema.is_pending(conn, "ddddddddddd") is True   # no attempt


# ---------------------------------------------------------------------------
# PR-3 v3 schema
# ---------------------------------------------------------------------------

def test_v3_migration_creates_pr3_tables(conn):
    """After v3, the 13 new tables (domain, concept, claim, ...) exist."""
    conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for required in (
        "domain", "concept", "concept_alias", "concept_domain",
        "concept_source", "claim", "claim_source", "claim_concept",
        "reasoning_edge", "evidence_mention", "external_evidence",
        "evaluation", "forecast",
    ):
        assert required in tables, f"missing table {required}"


def test_v3_corpus_run_kind_widened(conn):
    """corpus_run.kind CHECK must accept 'analyze', 'validate', 'concept_seed'."""
    run = "hcrun_v3_kind"
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run, "analyze", "t", "running", "z" * 64, "{}"))
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run + "v", "validate", "t", "running", "z" * 64, "{}"))
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run + "c", "concept_seed", "t", "running", "z" * 64, "{}"))
    conn.commit()


def test_v3_corpus_attempt_stage_widened(conn):
    """corpus_attempt.stage CHECK must accept analyze/validate/concept_seed."""
    run = "hcrun_v3_stage"
    _insert_video(conn, "aaaaaaaaaaa")
    conn.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, status,"
        " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
        (run, "analyze", "t", "running", "z" * 64, "{}"))
    for stage, outcome in (
        ("analyze", "analyze_failed"),
        ("validate", "validate_failed"),
        ("concept_seed", "concept_seed_failed"),
    ):
        conn.execute(
            "INSERT INTO corpus_attempt(att_id, video_id, run_id, stage,"
            " outcome, retryable, occurred_at) VALUES (?,?,?,?,?,?,?)",
            (f"hcatt_{stage}", "aaaaaaaaaaa", run, stage, outcome, 0, "t"))
    conn.commit()


def test_v3_claim_layer_check_rejects_unknown(conn):
    """claim.layer CHECK accepts only the three brief §3.1.5 values."""
    import pytest as _pytest
    _insert_video(conn, "aaaaaaaaaaa")
    with _pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim(claim_id, video_id, claim_text, claim_type,"
            " layer, status, analysis_run_id, created_at) "
            " VALUES (?,?,?,?,?,?,?,?)",
            ("hccl_x", "aaaaaaaaaaa", "x", "descriptive", "bogus_layer",
             "accepted", "hcrun_x", "t"))
    conn.commit()
