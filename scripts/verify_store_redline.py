"""Read-only inspector for `data/store.db` snapshots.

Reports the plain SHA-256 of every snapshot (gunzipped bytes) and compares
each against the current live `data/store.db`.

Exit codes
----------
0 : current store.db matches --expect, OR no --expect given and >=1 snapshot
1 : --expect given and live store.db SHA does NOT match
2 : no snapshots found in data/backups/
3 : live data/store.db missing
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys

# Absolute path to this script's directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Default repo_root is the parent of scripts/
_DEFAULT_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)

_BACKUP_DIRNAME = "backups"
_SNAPSHOT_REGEX = re.compile(r"^store-(\d{8}-\d{6})\.db\.gz$")


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _gunzip_sha(path: str) -> str:
    """Decompress a .gz file and return SHA-256 of the plain bytes."""
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _store_db(repo_root: str) -> str:
    return os.path.join(repo_root, "data", "store.db")


def _backup_dir(repo_root: str) -> str:
    return os.path.join(repo_root, "data", _BACKUP_DIRNAME)


def _list_snapshots(repo_root: str):
    """Return [(path, mtime, filename), ...] sorted by mtime."""
    bdir = _backup_dir(repo_root)
    if not os.path.isdir(bdir):
        return []
    out = []
    for name in os.listdir(bdir):
        if _SNAPSHOT_REGEX.match(name):
            full = os.path.join(bdir, name)
            out.append((full, os.path.getmtime(full), name))
    out.sort(key=lambda x: x[1])
    return out


def _format_timestamp(name: str) -> str:
    """Extract YYYYMMDD-HHMMSS from 'store-YYYYMMDD-HHMMSS.db.gz'."""
    m = _SNAPSHOT_REGEX.match(name)
    if m:
        return m.group(1)
    return name


def verify_and_report(repo_root: str, expect_sha: str | None, json_output: bool):
    """Main logic. Returns exit code."""
    live = _store_db(repo_root)
    if not os.path.isfile(live):
        print("错误：live data/store.db 不存在", file=sys.stderr)
        return 3

    live_sha = _hash_file(live)
    snapshots = _list_snapshots(repo_root)

    if not snapshots:
        print("错误：data/backups/ 中没有快照", file=sys.stderr)
        return 2

    rows = []
    for path, mtime, name in snapshots:
        plain_sha = _gunzip_sha(path)
        size = os.path.getsize(path)
        ts = _format_timestamp(name)
        match = plain_sha == live_sha
        rows.append({
            "timestamp": ts,
            "basename": name,
            "size_bytes": size,
            "plain_sha256": plain_sha,
            "source_match": match,
        })

    # --expect check
    if expect_sha is not None:
        if live_sha == expect_sha:
            return 0
        print(f"错误：live store.db SHA 与 --expect 不匹配", file=sys.stderr)
        print(f"  期望: {expect_sha}", file=sys.stderr)
        print(f"  实际: {live_sha}", file=sys.stderr)
        return 1

    # Human-readable table
    if not json_output:
        print(f"{'timestamp':<16} {'basename':<30} {'size':>10}  {'plain_sha256':<16}  match")
        print("-" * 110)
        for r in rows:
            short = r["plain_sha256"][:16]
            mark = "  *" if r["source_match"] else ""
            print(f"{r['timestamp']:<16} {r['basename']:<30} {r['size_bytes']:>10,}  {short:<16}{mark}")

    # JSON output
    out = {
        "live_sha256": live_sha,
        "live_path": live,
        "snapshot_count": len(rows),
        "snapshots": rows,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect store.db snapshots")
    parser.add_argument(
        "--repo-root",
        default=_DEFAULT_REPO_ROOT,
        help=f"Repo root (default: {_DEFAULT_REPO_ROOT})",
    )
    parser.add_argument(
        "--expect",
        help="Expected SHA-256 of live store.db; exit 0 only on match",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output",
    )
    args = parser.parse_args(argv)

    return verify_and_report(args.repo_root, args.expect, args.json)


if __name__ == "__main__":
    sys.exit(main())
