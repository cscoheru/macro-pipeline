"""Atomic restore of `data/store.db` from a gzipped snapshot.

Behavior
--------
1. Resolve --snapshot to data/backups/<name>.  Exit 2 if missing.
2. Verify live data/store.db exists.  Exit 3 if missing.
3. Compute plain SHA of the snapshot.
4. Print action plan.
5. Without --force and stdin is a TTY: prompt for confirmation.
6. Without --force and stdin is NOT a TTY: exit 4.
7. Without --dry-run:
   a. Copy live -> data/store.db.<UTC-timestamp>.bak
   b. Atomic gunzip+install: write data/store.db.tmp, fsync, os.replace
   c. chmod 0600
   d. Verify post-restore SHA == snapshot's plain SHA.
      On mismatch: exit 5, leave .bak in place.
8. With --dry-run: print full plan, exit 0.

Exit codes
----------
0 : success (or dry-run completed)
2 : missing snapshot
3 : missing live store.db
4 : confirmation refused / missing --force in non-TTY
5 : post-restore SHA mismatch (live preserved as .bak)
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import os
import shutil
import sys

# Absolute path to this script's directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)


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


def _store_db(repo_root: str) -> str:
    return os.path.join(repo_root, "data", "store.db")


def _backup_dir(repo_root: str) -> str:
    return os.path.join(repo_root, "data", "backups")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")


def _is_tty() -> bool:
    return sys.stdin.isatty()


def restore_store_from_snapshot(
    repo_root: str,
    snapshot_name: str,
    force: bool,
    dry_run: bool,
) -> int:
    """Returns exit code."""
    bdir = _backup_dir(repo_root)
    snapshot_path = os.path.join(bdir, snapshot_name)
    live = _store_db(repo_root)
    live_sha = None

    # 1. Resolve snapshot
    if not os.path.isfile(snapshot_path):
        print(f"错误：快照不存在: {snapshot_path}", file=sys.stderr)
        return 2

    # 2. Verify live store.db exists
    if not os.path.isfile(live):
        print(f"错误：live data/store.db 不存在，拒绝从无到有创建", file=sys.stderr)
        return 3

    # 3. Compute plain SHA of snapshot (call once; cache for post-restore compare)
    snapshot_sha = _gunzip_sha(snapshot_path)
    snapshot_mtime = os.path.getmtime(snapshot_path)
    snapshot_mtime_str = datetime.datetime.fromtimestamp(
        snapshot_mtime, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    snapshot_size = os.path.getsize(snapshot_path)
    live_sha = _hash_file(live)
    live_size = os.path.getsize(live)

    # 4. Print action plan
    utc_stamp = _utc_now()
    bak_path = f"{live}.{utc_stamp}.bak"
    tmp_path = os.path.join(repo_root, "data", "store.db.tmp")

    print("=== Restore Action Plan ===")
    print(f"  Source (snapshot): {snapshot_path}")
    print(f"  Snapshot mtime   : {snapshot_mtime_str}")
    print(f"  Snapshot SHA-256 : {snapshot_sha}")
    print(f"  Snapshot size    : {snapshot_size:,} bytes (gzipped)")
    print(f"  Target (live)    : {live}")
    print(f"  Live SHA-256     : {live_sha}")
    print(f"  Live size        : {live_size:,} bytes")
    print(f"  Backup path      : {bak_path}")

    if dry_run:
        print("\n[DRY RUN] No files were modified.")
        return 0

    # 5. Confirmation
    if not force:
        if not _is_tty():
            print("\n错误：stdin 不是 TTY 且未提供 --force", file=sys.stderr)
            return 4
        print()
        try:
            answer = input(f"Restore data/store.db from {snapshot_name}? [yes/no]: ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 4
        if answer.strip().lower() != "yes":
            print("已取消。", file=sys.stderr)
            return 4

    # 6a. Copy live -> .bak
    print(f"\nBacking up current store.db -> {bak_path}")
    shutil.copy2(live, bak_path)
    print(f"  done ({os.path.getsize(bak_path):,} bytes)")

    # 6b. Atomic gunzip to tmp, fsync, replace
    print(f"Decompressing snapshot -> {tmp_path}")
    with gzip.open(snapshot_path, "rb") as f_in:
        with open(tmp_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    # fsync to survive power loss
    fd = os.open(tmp_path, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)
    # Atomic rename
    os.replace(tmp_path, live)
    os.chmod(live, 0o600)
    print("  done")

    # 6c. Verify post-restore SHA against the cached snapshot_sha
    post_sha = _hash_file(live)
    if post_sha != snapshot_sha:
        print(
            f"错误：post-restore SHA 不匹配\n"
            f"  预期: {snapshot_sha}\n"
            f"  实际: {post_sha}\n"
            f"  .bak 文件已保留: {bak_path}",
            file=sys.stderr,
        )
        return 5

    print(f"\nRestore complete. SHA verified: {post_sha}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Restore data/store.db from a gzipped snapshot"
    )
    parser.add_argument(
        "--repo-root",
        default=_DEFAULT_REPO_ROOT,
        help=f"Repo root (default: {_DEFAULT_REPO_ROOT})",
    )
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot basename under data/backups/ (e.g. store-20260824-115556.db.gz)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip interactive confirmation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print action plan, do NOT write",
    )
    args = parser.parse_args(argv)

    return restore_store_from_snapshot(
        args.repo_root,
        args.snapshot,
        args.force,
        args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
