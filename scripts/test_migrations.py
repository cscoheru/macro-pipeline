"""Schema migration tests; all databases are in-memory."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import ledger
import migrations


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _phase1_database():
    conn = _conn()
    conn.executescript(ledger._SCHEMA_SQL)
    conn.executescript(ledger._triggers_sql(ledger._BASE_ENTITIES))
    ledger.create_claim(conn, statement="legacy claim", actor="legacy")
    return conn


def test_new_database_migrates_to_latest_twice():
    conn = _conn()
    migrations.ensure_schema(conn)
    first_versions = conn.execute(
        "SELECT version, description FROM schema_version ORDER BY version"
    ).fetchall()
    migrations.ensure_schema(conn)
    assert migrations.current_version(conn) == migrations.LATEST_VERSION
    assert conn.execute(
        "SELECT version, description FROM schema_version ORDER BY version"
    ).fetchall() == first_versions
    assert [row[0] for row in first_versions] == [1, 2]
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generated_insight'"
    ).fetchone()
    conn.close()


def test_phase1_database_upgrade_preserves_rows_and_events():
    conn = _phase1_database()
    before_claims = conn.execute("SELECT * FROM claim").fetchall()
    before_events = conn.execute("SELECT * FROM ledger_event").fetchall()

    migrations.ensure_schema(conn)
    migrations.ensure_schema(conn)

    assert conn.execute("SELECT * FROM claim").fetchall() == before_claims
    assert conn.execute("SELECT * FROM ledger_event").fetchall() == before_events
    assert [row[0] for row in conn.execute(
        "SELECT version FROM schema_version ORDER BY version"
    )] == [1, 2]
    conn.close()


def test_failed_migration_does_not_advance_version():
    conn = _phase1_database()
    conn.executescript(migrations._VERSION_SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO schema_version(version, applied_at, description)"
            " VALUES (1, 't', 'legacy')"
        )
        conn.execute("CREATE TABLE insight_artifact (wrong TEXT)")

    with pytest.raises(sqlite3.OperationalError):
        migrations.ensure_schema(conn)

    assert migrations.current_version(conn) == 1
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generated_insight'"
    ).fetchone() is None
    conn.close()
