"""Tests for `lib/presnapshot.py`.

Covers the launchd pre-snapshot mechanism that protects `data/store.db`
from the red-line dispute raised during PR-1 R3 verification (the 09:07
launchd run rewrites store.db between snapshots and there is no git
history to restore from).

All tests run on temp dirs and do NOT touch the real repo's `data/`.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import presnapshot  # noqa: E402


@pytest.fixture
def repo_root():
    """A scratch repo with a fake `data/store.db`. Never the real repo."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "data"))
        with open(os.path.join(tmp, "data", "store.db"), "wb") as f:
            f.write(b"SQLite format 3\x00" + b"x" * 4096)
        yield tmp


def _store_bytes(repo_root):
    with open(os.path.join(repo_root, "data", "store.db"), "rb") as f:
        return f.read()


def _store_sha(repo_root):
    return hashlib.sha256(_store_bytes(repo_root)).hexdigest()


# ---------------------------------------------------------------------------
# P1 — happy path
# ---------------------------------------------------------------------------

def test_snapshot_writes_gz_with_matching_sha_and_0600(repo_root):
    result = presnapshot.snapshot_store_db(repo_root=repo_root)
    assert result is not None
    target, sha = result
    assert sha == _store_sha(repo_root)
    assert re.match(r"store-\d{8}-\d{6}\.db\.gz$", os.path.basename(target))
    mode = oct(os.stat(target).st_mode & 0o777)
    assert mode == "0o600", mode
    # gzip round-trip equals source
    with gzip.open(target, "rb") as f:
        assert f.read() == _store_bytes(repo_root)


def test_snapshot_creates_data_backups_dir(repo_root):
    assert not os.path.isdir(os.path.join(repo_root, "data", "backups"))
    presnapshot.snapshot_store_db(repo_root=repo_root)
    bdir = os.path.join(repo_root, "data", "backups")
    assert os.path.isdir(bdir)
    assert oct(os.stat(bdir).st_mode & 0o777) == "0o700"


def test_snapshot_uses_injected_clock_for_filename(repo_root):
    fixed = datetime.datetime(2026, 8, 24, 9, 7, 0)
    target, _ = presnapshot.snapshot_store_db(repo_root=repo_root, now=fixed)
    assert os.path.basename(target) == "store-20260824-090700.db.gz"


# ---------------------------------------------------------------------------
# P2 — idempotency, rotation, edge cases
# ---------------------------------------------------------------------------

def test_snapshot_is_idempotent_within_same_second(repo_root):
    a = presnapshot.snapshot_store_db(repo_root=repo_root)
    b = presnapshot.snapshot_store_db(repo_root=repo_root)
    assert a is not None and b is not None
    assert a[0] == b[0]  # same filename
    # no extra file created
    snaps = presnapshot.list_snapshots(repo_root)
    assert len(snaps) == 1


def test_snapshot_takes_new_file_when_source_changes(repo_root):
    """Distinct source content + later timestamp => distinct snapshot file.

    NOTE: same-second snapshots are intentionally idempotent (see
    `test_snapshot_is_idempotent_within_same_second`). This test forces a
    later timestamp via `now=` so the filenames differ.
    """
    base = datetime.datetime(2026, 8, 24, 9, 7, 0)
    a = presnapshot.snapshot_store_db(repo_root=repo_root, now=base)
    with open(os.path.join(repo_root, "data", "store.db"), "ab") as f:
        f.write(b"\n-- extra --\n")
    b = presnapshot.snapshot_store_db(repo_root=repo_root,
                                      now=base + datetime.timedelta(seconds=10))
    assert a[0] != b[0]
    assert b[1] == _store_sha(repo_root)
    assert len(presnapshot.list_snapshots(repo_root)) == 2


def test_rotation_keeps_n_most_recent(repo_root):
    # Take 4 snapshots with monotonically-increasing injected timestamps so
    # rotation has something to delete.
    base = datetime.datetime(2026, 8, 24, 9, 7, 0)
    for i in range(4):
        # re-write source so each snapshot has a distinct SHA (cosmetic)
        with open(os.path.join(repo_root, "data", "store.db"), "wb") as f:
            f.write(f"round={i}\n".encode() + b"y" * 1024)
        r = presnapshot.snapshot_store_db(repo_root=repo_root, keep=2,
                                         now=base + datetime.timedelta(seconds=i))
        assert r is not None
    snaps = presnapshot.list_snapshots(repo_root)
    paths = [p for p, _ in snaps]
    assert len(paths) == 2
    # the two oldest mtimes (round=0 and round=1) must be gone
    assert not any("090700" in os.path.basename(p) for p in paths)
    assert not any("090701" in os.path.basename(p) for p in paths)
    # the two newest stay
    assert any("090702" in os.path.basename(p) for p in paths)
    assert any("090703" in os.path.basename(p) for p in paths)


def test_snapshot_missing_source_returns_none_and_creates_no_dir(repo_root):
    os.unlink(os.path.join(repo_root, "data", "store.db"))
    r = presnapshot.snapshot_store_db(repo_root=repo_root)
    assert r is None
    # Per design: do not create the backups dir if there was nothing to snapshot
    assert not os.path.isdir(os.path.join(repo_root, "data", "backups"))


def test_snapshot_never_raises_on_permission_error(tmp_path, caplog):
    # source is unreadable: snapshot must return None, never raise
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "data").mkdir()
    src = repo / "data" / "store.db"
    src.write_bytes(b"x" * 16)
    os.chmod(src, 0o000)
    try:
        r = presnapshot.snapshot_store_db(repo_root=str(repo))
        assert r is None
    finally:
        os.chmod(src, 0o644)  # cleanup so tmp_path teardown works


def test_snapshot_handles_corrupt_target_via_re_read(tmp_path):
    """If a same-second snapshot file already exists with DIFFERENT bytes
    (e.g. left over from a crashed prior run), the new run must replace it
    rather than silently reuse the stale one."""
    repo = tmp_path / "r"
    (repo / "data" / "backups").mkdir(parents=True)
    with open(repo / "data" / "store.db", "wb") as f:
        f.write(b"new content here")
    # Pre-create a same-name snapshot with WRONG content (gzip of garbage).
    bad = repo / "data" / "backups" / "store-20260824-090700.db.gz"
    with gzip.open(bad, "wb") as f:
        f.write(b"stale corrupt content")
    r = presnapshot.snapshot_store_db(repo_root=str(repo),
                                      now=datetime.datetime(2026, 8, 24, 9, 7, 0))
    assert r is not None
    target, sha = r
    assert sha == hashlib.sha256(b"new content here").hexdigest()
    # After replacement, decompressed content matches the fresh source.
    with gzip.open(target, "rb") as f:
        assert f.read() == b"new content here"


# ---------------------------------------------------------------------------
# P3 — wiring into run.py
# ---------------------------------------------------------------------------

_RUN_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "run.py")


def test_run_py_imports_presnapshot_module():
    """`run.py` must import and call `presnapshot.snapshot_store_db(...)` so
    that every launchd-triggered (and manual) run leaves a recoverable
    snapshot of `data/store.db` behind."""
    src = open(_RUN_PY, encoding="utf-8").read()
    assert "import presnapshot" in src or "from presnapshot" in src, \
        "run.py does not import presnapshot"
    assert "snapshot_store_db" in src, \
        "run.py does not call presnapshot.snapshot_store_db"


def test_run_py_snapshot_call_happens_before_setup_logging():
    """The snapshot must run at the start of `main()`, before the call to
    `setup_logging()` (which writes to logs/) — otherwise launchd ticks have
    no recoverable baseline if logging init itself touches data/.

    We use `ast` to extract the EXACT source line of each top-level call
    inside `main()`. This avoids the trap where the docstring I added
    contains the literal text `` `setup_logging()` `` (which a naive
    `str.find` would match).
    """
    import ast

    tree = ast.parse(open(_RUN_PY, encoding="utf-8").read())
    main_fn = next((n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main_fn is not None, "run.py has no `def main():`"
    snap_line = None
    log_line = None
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            fname = func.attr
        elif isinstance(func, ast.Name):
            fname = func.id
        else:
            continue
        if fname == "snapshot_store_db":
            snap_line = node.lineno
        elif fname == "setup_logging" and log_line is None:
            log_line = node.lineno
    assert snap_line is not None, "main() does not call snapshot_store_db(...)"
    assert log_line is not None, "main() does not call setup_logging()"
    assert snap_line < log_line, (
        f"snapshot_store_db (line {snap_line}) must precede "
        f"setup_logging (line {log_line}) in main()"
    )