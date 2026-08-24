"""Append-only migrations for the Hou Chen research corpus (P1-3 hardened).

Guarantees:

    1. A migration version is recorded ONLY after `houchen_schema.validate_schema()`
       confirms the schema is EXACTLY v1 — a wrong pre-existing same-named table
       cannot trick the migrator into claiming success.
    2. Version re-check + DDL + version insert happen inside ONE explicit
       `BEGIN IMMEDIATE` transaction. Two processes racing the first migration
       both open the lock; the loser re-reads version inside the lock, sees the
       winner completed + validates the schema, and treats it as success (no
       primary-key collision).
    3. Any IntegrityError that is NOT "the same migration already completed by
       a competitor, and the schema validates" is re-raised. A failed migration
       rolls back DDL + version row together (executescript already ran in the
       same transaction, so ROLLBACK undoes both).

`ensure_schema(conn)` is idempotent and safe to call repeatedly.
"""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import houchen_schema


LATEST_VERSION = houchen_schema.VERSION


def current_version(conn) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        # schema_version does not exist yet → version 0.
        return 0
    return row[0] or 0


def _apply_v1(conn) -> None:
    """Apply v1 atomically inside one IMMEDIATE transaction with in-lock re-check.

    DDL is run statement-by-statement via `conn.execute()` (NOT `executescript`,
    which would auto-commit) so a failure rolls back BOTH the DDL and the
    version row together (P1-3: no partial tables / no stray version row).
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Re-read version INSIDE the lock (P1-3): a competitor may have
        # completed between our earlier check and acquiring the write lock.
        ver = current_version(conn)
        if ver >= 1:
            if houchen_schema.validate_schema(conn):
                conn.execute("COMMIT")
                return
            conn.execute("ROLLBACK")
            raise sqlite3.DatabaseError(
                "schema_version claims v1 but schema does not validate; "
                "refusing to adopt foreign schema"
            )
        for stmt in houchen_schema._V1_STATEMENTS:
            conn.execute(stmt)
        # A pre-existing wrong same-named table (blocked by IF NOT EXISTS)
        # must NOT be silently accepted: require exact v1 before recording the
        # version row (P1-3).
        if not houchen_schema.validate_schema(conn):
            conn.execute("ROLLBACK")
            raise sqlite3.DatabaseError(
                "schema does not validate after migration; refusing to record v1"
            )
        conn.execute(
            "INSERT INTO schema_version(version, applied_at, description)"
            " VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
            ("PR-1: corpus foundation + frozen raw captions",),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if houchen_schema.validate_schema(conn):
            return
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


# Tables whose CHECK constraints v2 widens. SQLite has no ALTER CONSTRAINT,
# so the migration must recreate the table with the new DDL and copy data
# over. The two frozen triggers on raw_caption / schema_version are NOT in
# this list and remain untouched.
_V2_CHECK_WIDEN = ("corpus_run", "corpus_attempt")


def _recreate_with_widened_check(conn, table) -> None:
    """Drop-and-recreate a v1 table with its v2 CHECKs; copy data over.

    Uses SQLite's built-in table-rename-recreate pattern. PR-1's triggers on
    raw_caption / schema_version are NOT affected by this function (only
    corpus_run and corpus_attempt are widened).

    Ordering note: the backup keeps the OLD table's indexes (still bound to
    `idx_corpus_run_started` etc.) so CREATE INDEX on the new table would
    collide. We therefore drop the backup BEFORE recreating indexes. The row
    data was captured into memory first, so the data loss window is zero.
    """
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    cols = [r[1] for r in conn.execute(f"PRAGMA table_xinfo({table})").fetchall()]
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v1_backup")
    if table == "corpus_run":
        new_ddl = """CREATE TABLE corpus_run (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('catalog','caption_fetch','preflight','normalize')),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed')),
            config_sha256 TEXT NOT NULL,
            tool_versions_json TEXT NOT NULL,
            summary_json TEXT,
            error_class TEXT,
            error_detail TEXT
        )"""
        new_indexes = [
            "CREATE INDEX idx_corpus_run_started ON corpus_run(started_at)",
        ]
    elif table == "corpus_attempt":
        new_ddl = """CREATE TABLE corpus_attempt (
            att_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL REFERENCES video(video_id),
            run_id TEXT NOT NULL REFERENCES corpus_run(run_id),
            stage TEXT NOT NULL CHECK(stage IN ('catalog','subtitle_inventory',
                                                 'subtitle_download','subtitle_parse',
                                                 'freeze','normalize')),
            outcome TEXT NOT NULL CHECK(outcome IN ('success','skipped','missing',
                                                    'auth_required','unavailable',
                                                    'retryable','tool_error',
                                                    'permanent_error','raw_integrity_error',
                                                    'normalize_failed')),
            error_class TEXT,
            detail TEXT,
            retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0,1)),
            occurred_at TEXT NOT NULL
        )"""
        new_indexes = [
            "CREATE INDEX idx_attempt_video ON corpus_attempt(video_id, occurred_at)",
            "CREATE INDEX idx_attempt_outcome ON corpus_attempt(outcome)",
            "CREATE INDEX idx_attempt_run ON corpus_attempt(run_id, occurred_at)",
        ]
    else:
        raise sqlite3.DatabaseError(f"unsupported recreate: {table}")
    conn.execute(new_ddl)
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    conn.executemany(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows)
    # Drop the backup BEFORE creating indexes — the backup still carries the
    # OLD table's indexes under their original names (idx_corpus_run_started,
    # idx_attempt_*) which would collide with CREATE INDEX on the new table.
    conn.execute(f"DROP TABLE {table}_v1_backup")
    for idx in new_indexes:
        conn.execute(idx)


def _apply_v2(conn) -> None:
    """Apply v2 atomically (PR-2: transcript_version + transcript_segment +
    widened CHECKs on corpus_run / corpus_attempt).

    Mirrors _apply_v1's invariants:
      - One BEGIN IMMEDIATE, in-lock re-check.
      - Schema validation GATE before recording the version row.
      - Any non-recognition failure raises; ROLLBACK undoes DDL + version row.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        ver = current_version(conn)
        if ver >= 2:
            if houchen_schema.validate_schema(conn):
                conn.execute("COMMIT")
                return
            conn.execute("ROLLBACK")
            raise sqlite3.DatabaseError(
                "schema_version claims v2 but schema does not validate; "
                "refusing to adopt foreign schema"
            )
        if ver < 1:
            # v2 must build on top of v1; refuse to recreate corpus_run /
            # corpus_attempt if they don't exist yet.
            conn.execute("ROLLBACK")
            raise sqlite3.DatabaseError(
                "cannot apply v2: schema_version is below v1"
            )

        # 1. New v2 tables (transcript_version, transcript_segment).
        for stmt in houchen_schema._V2_STATEMENTS:
            conn.execute(stmt)

        # 2. Recreate corpus_run + corpus_attempt with widened CHECKs.
        #    SQLite has no ALTER CONSTRAINT; the canonical pattern is
        #    rename → create new → copy data → drop backup, all inside one tx.
        for table in _V2_CHECK_WIDEN:
            _recreate_with_widened_check(conn, table)

        # 3. Validate the full schema (v1 widened + v2 added).
        if not houchen_schema.validate_schema(conn):
            conn.execute("ROLLBACK")
            raise sqlite3.DatabaseError(
                "schema does not validate after v2 migration; refusing to record"
            )
        conn.execute(
            "INSERT INTO schema_version(version, applied_at, description)"
            " VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
            ("PR-2: deterministic transcript normalizer layer",),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if houchen_schema.validate_schema(conn):
            return
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def ensure_schema(conn) -> None:
    """Idempotent, crash-safe migration to LATEST_VERSION.

    Refuses to run if the connection already holds a transaction (the caller
    must commit first); the migration manages its own transaction boundary.
    """
    if conn.in_transaction:
        raise sqlite3.OperationalError(
            "ensure_schema called while a transaction is open"
        )
    _apply_v1(conn)
    _apply_v2(conn)
    if current_version(conn) != LATEST_VERSION:
        raise sqlite3.DatabaseError(
            f"houchen migration incomplete: expected {LATEST_VERSION},"
            f" got {current_version(conn)}"
        )
