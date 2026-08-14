"""SQLite time-series store. One row per (source, series, observation date)."""
import sqlite3
import paths
import migrations


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
    migrations.ensure_schema(conn)
    return conn


def upsert_observations(source: str, series: str, rows, conn=None) -> int:
    """Upsert rows, optionally participating in the caller's transaction."""
    own_conn = conn is None
    conn = conn or _connect()
    values = [(source, series, d, v) for d, v in rows]
    try:
        if own_conn:
            with conn:
                n = conn.executemany(
                    "INSERT OR REPLACE INTO observations(source, series, date, value)"
                    " VALUES (?, ?, ?, ?)",
                    values,
                ).rowcount
        else:
            n = conn.executemany(
                "INSERT OR REPLACE INTO observations(source, series, date, value)"
                " VALUES (?, ?, ?, ?)",
                values,
            ).rowcount
        return n
    finally:
        if own_conn:
            conn.close()


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
