"""SQLite connection management for the Hou Chen research corpus (P0-2/P1-4).

Hardened responsibilities:

    - `connect()` (write) enforces the data-root isolation contract via
      `houchen_paths.verify_data_root()` BEFORE opening or creating the DB,
      then opens with `foreign_keys=ON` + `busy_timeout` and runs migrations.
    - `connect_readonly()` opens `file:…?mode=ro` with NO directory creation
      and NO migration (P2-2: status/coverage must be truly read-only). If the
      DB file does not exist, it raises FileNotFoundError; callers surface an
      empty status instead of creating anything.
    - The DB leaf itself must not be a symlink (P0-2).

Isolation: we never import lib/store.py. The DB path comes solely from
`houchen_paths.sqlite_path()`, which is derived from the validated canonical
root.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import houchen_migrations
import houchen_paths


def ensure_dirs() -> None:
    """Create the write-time directory layout. Called by WRITE entry points
    only (never by read-only status/coverage).

    Every directory is validated component-by-component BEFORE creation so a
    symlinked `raw`/`derived`/… cannot redirect `makedirs` outside the data
    root (P0-2)."""
    root = houchen_paths.verify_data_root()
    for d in (
        os.path.join(root, "raw", "captions"),
        os.path.join(root, "raw", "metadata"),
        os.path.join(root, "raw", ".tmp"),
        os.path.join(root, "derived"),
        os.path.join(root, "artifacts"),
        os.path.join(root, "failures"),
    ):
        houchen_paths.assert_no_symlink_components(d)
        os.makedirs(d, exist_ok=True)


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open the research DB for read-write, applying pragmas + migrations.

    `db_path` is only honored for tests; in production it is ignored and the
    validated data-root path is used. The DB file is created if absent (after
    the root isolation check passes).

    P0-1: a symlinked DB leaf is rejected unconditionally — for BOTH the
    default production path and an explicit path — BEFORE `sqlite3.connect`
    creates or opens anything, so an external SQLite is never touched.
    """
    target = db_path or houchen_paths.sqlite_path()
    if db_path is None:
        # Enforce isolation on the real path and reject any symlink in the
        # DB path (leaf + parent components under the root).
        houchen_paths.verify_data_root()
        target = houchen_paths.sqlite_path()
        houchen_paths.assert_no_symlink_components(target)
    elif os.path.islink(target):
        raise houchen_paths.DataRootError(
            f"database path is a symlink: {target}"
        )
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    houchen_migrations.ensure_schema(conn)
    return conn


def connect_readonly(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a strictly read-only connection (URI mode). No dir creation, no
    migration. Raises FileNotFoundError if the DB does not exist."""
    target = db_path or houchen_paths.sqlite_path()
    if db_path is None:
        target = houchen_paths.sqlite_path()
    if os.path.islink(target):
        raise houchen_paths.DataRootError(f"database path is a symlink: {target}")
    if not os.path.exists(target):
        raise FileNotFoundError(f"research DB not found: {target}")
    uri = f"file:{target}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    # foreign_keys in read-only mode is harmless (no writes can occur anyway).
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def db_exists(db_path: Optional[str] = None) -> bool:
    return os.path.exists(db_path or houchen_paths.sqlite_path())
