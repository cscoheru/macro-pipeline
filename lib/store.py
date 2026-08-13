"""SQLite time-series store. One row per (source, series, observation date)."""
import sqlite3
import paths
import ledger


def _connect():
    conn = sqlite3.connect(paths.STORE_DB)
    # Connection-level pragmas (not persisted across connections): referential
    # integrity on, and tolerate brief lock contention instead of failing fast.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS observations (
            source  TEXT NOT NULL,
            series  TEXT NOT NULL,
            date    TEXT NOT NULL,
            value   REAL,
            PRIMARY KEY (source, series, date)
        )"""
    )
    # Co-locate the append-only judgement ledger alongside observations.
    # Idempotent: only builds the 7 ledger tables + triggers when absent.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_event'"
    ).fetchone() is None:
        ledger.init_schema(conn)
    return conn


def upsert_observations(source: str, series: str, rows) -> int:
    """Upsert (date, value) pairs for a source/series. rows: iterable of (date, float)."""
    conn = _connect()
    n = 0
    with conn:
        n = conn.executemany(
            "INSERT OR REPLACE INTO observations(source, series, date, value) VALUES (?, ?, ?, ?)",
            [(source, series, d, v) for d, v in rows],
        ).rowcount
    conn.close()
    return n


def get_history(source: str, series: str, limit: int = 30):
    """Return history oldest -> newest, up to `limit` most recent observations."""
    conn = _connect()
    cur = conn.execute(
        """SELECT date, value FROM observations
           WHERE source = ? AND series = ?
           ORDER BY date DESC LIMIT ?""",
        (source, series, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))  # oldest -> newest


def latest_observation(source: str, series: str):
    """Return (date, value) of the most recent observation, or None."""
    conn = _connect()
    cur = conn.execute(
        """SELECT date, value FROM observations
           WHERE source = ? AND series = ?
           ORDER BY date DESC LIMIT 1""",
        (source, series),
    )
    row = cur.fetchone()
    conn.close()
    return row  # None if empty
