"""Pytest suite for verify_store_redline.py and restore_store_from_snapshot.py."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

import pytest

SCRIPT_VERIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "verify_store_redline.py")
SCRIPT_RESTORE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "restore_store_from_snapshot.py")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _gunzip_sha(path: str) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_verify(args, repo_root):
    cmd = [sys.executable, SCRIPT_VERIFY, "--repo-root", repo_root] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


def _run_restore(args, repo_root):
    cmd = [sys.executable, SCRIPT_RESTORE, "--repo-root", repo_root] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_root():
    """Temp repo with data/backups/ and a live data/store.db."""
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        backups = os.path.join(data, "backups")
        os.makedirs(backups, mode=0o700)
        yield tmp


# ---------------------------------------------------------------------------
# verify_store_redline.py
# ---------------------------------------------------------------------------

def test_verify_lists_snapshots_with_correct_plain_sha(repo_root):
    """plain_sha256 column equals SHA of gunzipped bytes."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")

    content = b"hello world " * 1000
    with open(live_path, "wb") as f:
        f.write(content)
    live_sha = _hash_file(live_path)

    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    r = _run_verify(["--json"], repo_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["snapshot_count"] == 1
    row = body["snapshots"][0]
    assert row["plain_sha256"] == live_sha
    assert row["source_match"] is True


def test_verify_source_match_true_when_live_matches(repo_root):
    """source_match=True when snapshot plain SHA equals live SHA."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")

    content = b"same content"
    with open(live_path, "wb") as f:
        f.write(content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    r = _run_verify(["--json"], repo_root)
    assert r.returncode == 0
    body = json.loads(r.stdout)
    assert body["snapshots"][0]["source_match"] is True


def test_verify_source_match_false_when_live_differs(repo_root):
    """source_match=False when snapshot plain SHA differs from live SHA."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")

    with open(live_path, "wb") as f:
        f.write(b"live content differs")
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(b"snapshot content differs too")

    r = _run_verify(["--json"], repo_root)
    assert r.returncode == 0
    body = json.loads(r.stdout)
    assert body["snapshots"][0]["source_match"] is False


def test_verify_expect_returns_zero_on_match(repo_root):
    """--expect with a matching SHA exits 0."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    content = b"test content"
    with open(live_path, "wb") as f:
        f.write(content)
    sha = _hash_file(live_path)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    r = _run_verify(["--expect", sha], repo_root)
    assert r.returncode == 0, r.stderr


def test_verify_expect_returns_one_on_mismatch(repo_root):
    """--expect with a non-matching SHA exits 1."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    with open(live_path, "wb") as f:
        f.write(b"live content")
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(b"snapshot content")

    fake_sha = "a" * 64
    r = _run_verify(["--expect", fake_sha], repo_root)
    assert r.returncode == 1, r.stderr
    assert "不匹配" in r.stderr


def test_verify_expect_with_no_snapshots_returns_two(repo_root):
    """--expect when no snapshots exist exits 2."""
    live_path = os.path.join(repo_root, "data", "store.db")
    with open(live_path, "wb") as f:
        f.write(b"lonely live")
    fake_sha = "a" * 64
    r = _run_verify(["--expect", fake_sha], repo_root)
    assert r.returncode == 2, r.stderr


def test_verify_missing_live_returns_three(repo_root):
    """Missing live data/store.db exits 3."""
    r = _run_verify([], repo_root)
    assert r.returncode == 3, r.stderr
    assert "不存在" in r.stderr


def test_verify_json_has_all_five_fields(repo_root):
    """--json output contains timestamp, basename, size_bytes, plain_sha256,
    source_match for each snapshot."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    content = b"json test"
    with open(live_path, "wb") as f:
        f.write(content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    r = _run_verify(["--json"], repo_root)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    row = body["snapshots"][0]
    for field in ("timestamp", "basename", "size_bytes", "plain_sha256", "source_match"):
        assert field in row, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# restore_store_from_snapshot.py
# ---------------------------------------------------------------------------

def test_restore_dry_run_does_not_modify_anything(repo_root):
    """--dry-run must not touch the filesystem (before/after identical)."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    content = b"original"
    with open(live_path, "wb") as f:
        f.write(content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    before = set()
    for root, _, files in os.walk(repo_root):
        for f in files:
            before.add(os.path.join(root, f))

    r = _run_restore(["--snapshot", "store-20260824-115556.db.gz", "--dry-run"], repo_root)
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout or "dry" in r.stdout.lower()

    after = set()
    for root, _, files in os.walk(repo_root):
        for f in files:
            after.add(os.path.join(root, f))
    assert before == after


def test_restore_live_sha_matches_snapshot_plain_sha(repo_root):
    """Restored live store.db SHA equals snapshot's plain SHA."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    content = b"restore target " * 50
    with open(live_path, "wb") as f:
        f.write(content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    r = _run_restore(
        ["--snapshot", "store-20260824-115556.db.gz", "--force"],
        repo_root,
    )
    assert r.returncode == 0, r.stderr
    assert _hash_file(live_path) == _gunzip_sha(snap_path)


def test_restore_creates_bak_file(repo_root):
    """Restore preserves live state as a .bak before swapping."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    live_content = b"live before restore"
    snap_content = b"snap after restore"
    with open(live_path, "wb") as f:
        f.write(live_content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(snap_content)

    r = _run_restore(
        ["--snapshot", "store-20260824-115556.db.gz", "--force"],
        repo_root,
    )
    assert r.returncode == 0, r.stderr

    bak_files = [
        f for f in os.listdir(repo_root + "/data")
        if f.startswith("store.db.") and f.endswith(".bak")
    ]
    assert len(bak_files) == 1, f"Expected 1 .bak file, got {bak_files}"
    bak_path = os.path.join(repo_root, "data", bak_files[0])
    with open(bak_path, "rb") as f:
        assert f.read() == live_content


def test_restore_missing_snapshot_returns_two(repo_root):
    """Missing snapshot basename exits 2."""
    live_path = os.path.join(repo_root, "data", "store.db")
    with open(live_path, "wb") as f:
        f.write(b"lonely")

    r = _run_restore(["--snapshot", "does-not-exist.db.gz"], repo_root)
    assert r.returncode == 2, r.stderr
    assert "不存在" in r.stderr


def test_restore_missing_live_returns_three(repo_root):
    """Missing live store.db exits 3."""
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    with gzip.open(snap_path, "wb") as f:
        f.write(b"orphan snapshot")

    r = _run_restore(["--snapshot", "store-20260824-115556.db.gz", "--force"], repo_root)
    assert r.returncode == 3, r.stderr


def test_restore_non_tty_without_force_returns_four(repo_root):
    """Non-TTY stdin without --force exits 4."""
    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")
    content = b"non-tty test"
    with open(live_path, "wb") as f:
        f.write(content)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(content)

    # Simulate non-TTY by closing stdin before the call
    r = subprocess.run(
        [sys.executable, SCRIPT_RESTORE,
         "--repo-root", repo_root,
         "--snapshot", "store-20260824-115556.db.gz"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 4, r.stderr
    assert "TTY" in r.stderr or "force" in r.stderr.lower()


def test_restore_post_restore_sha_mismatch_preserves_bak(repo_root):
    """Post-restore SHA mismatch exits 5 and leaves .bak in place.

    Strategy: invoke the restore script's main() in-process via a wrapper script
    that monkey-patches the module before the script's own import runs. This
    avoids subprocess isolation — the patch is in the same process that executes
    the actual restore logic.
    """
    import restore_store_from_snapshot as rs

    live_path = os.path.join(repo_root, "data", "store.db")
    snap_path = os.path.join(repo_root, "data", "backups", "store-20260824-115556.db.gz")

    correct_content = b"snap correct bytes 999"
    corrupted_content = b"snap CORRUPTED bytes XXX"

    # Write correct content and record its real SHA
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(correct_content)
    correct_sha = _gunzip_sha(snap_path)

    # Overwrite with corrupted content so post-restore SHA != correct_sha
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(corrupted_content)

    with open(live_path, "wb") as f:
        f.write(b"live before restore")

    # Wrapper: patches the module then calls main() — must stay in-process.
    # Hardcode the scripts dir so it works inside -c (where __file__ is undefined).
    scripts_dir = os.path.dirname(os.path.abspath(SCRIPT_RESTORE))
    wrapper_code = textwrap.dedent(f"""\
        import sys, os, textwrap
        sys.path.insert(0, {scripts_dir!r})

        import restore_store_from_snapshot as rs

        _real_gunzip = rs._gunzip_sha
        _correct_sha  = {correct_sha!r}
        _snap_path    = {snap_path!r}

        def lying_gunzip(path):
            if path == _snap_path:
                return _correct_sha
            return _real_gunzip(path)
        rs._gunzip_sha = lying_gunzip

        sys.exit(rs.main())
    """)

    r = subprocess.run(
        [sys.executable, "-c", wrapper_code,
         "--repo-root", repo_root,
         "--snapshot", "store-20260824-115556.db.gz",
         "--force"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 5, (
        f"Expected exit 5, got {r.returncode}\n"
        f"stdout: {r.stdout}\n"
        f"stderr: {r.stderr}"
    )
    assert "不匹配" in r.stderr or "mismatch" in r.stderr.lower()

    # .bak must be preserved
    bak_files = [
        f for f in os.listdir(repo_root + "/data")
        if f.startswith("store.db.") and f.endswith(".bak")
    ]
    assert len(bak_files) == 1, f".bak should be preserved, got {bak_files}"
    bak_path = os.path.join(repo_root, "data", bak_files[0])
    with open(bak_path, "rb") as f:
        assert f.read() == b"live before restore"
