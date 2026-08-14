"""Idempotent SQLite schema migrations for the judgement ledger."""
import sqlite3

import ledger

LATEST_VERSION = 2

_VERSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS noguard_upd_schema_version
BEFORE UPDATE ON schema_version
BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: UPDATE forbidden'); END;
CREATE TRIGGER IF NOT EXISTS noguard_del_schema_version
BEFORE DELETE ON schema_version
BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: DELETE forbidden'); END;
"""


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def current_version(conn):
    if not _table_exists(conn, "schema_version"):
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def _apply(conn, version, description, sql):
    if current_version(conn) >= version:
        return
    # Parameterized INSERT: description comes from code constants today, but
    # string-built SQL is forbidden by project rules regardless of source.
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + sql)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at, description)"
            " VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
            (version, description),
        )
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def ensure_schema(conn):
    """Upgrade a new or Phase-1 database to the current schema."""
    conn.executescript(_VERSION_SCHEMA)

    version = current_version(conn)
    if version == 0 and _table_exists(conn, "ledger_event"):
        with conn:
            conn.execute(
                "INSERT INTO schema_version(version, applied_at, description)"
                " VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?)",
                ("adopt existing Phase-1 ledger",),
            )
        version = 1

    if version == 0:
        _apply(
            conn,
            1,
            "initial append-only judgement ledger",
            ledger._SCHEMA_SQL + "\n" + ledger._triggers_sql(ledger._BASE_ENTITIES),
        )

    _apply(
        conn,
        2,
        "generated insight lifecycle and provenance",
        ledger._INSIGHT_SCHEMA_SQL
        + "\n"
        + ledger._triggers_sql(
            [
                "generated_insight",
                "insight_artifact",
                "insight_provenance",
                "insight_attempt",
            ]
        ),
    )

    if current_version(conn) != LATEST_VERSION:
        raise sqlite3.DatabaseError(
            f"schema migration incomplete: expected {LATEST_VERSION},"
            f" got {current_version(conn)}"
        )
