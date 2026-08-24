"""Pre-run snapshot of `data/store.db`.

Rationale
---------
`data/store.db` is the macro pipeline's hot file. launchd triggers a daily
fetch at 09:07 and 16:07 (see `~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist`),
which rewrites it. When a downstream audit needs a recoverable baseline (the
PR-1 R3 red-line dispute), there is no git history (`data/` is gitignored) and
no rotation elsewhere.

This module takes a gzipped, SHA-verified snapshot of `data/store.db` at the
start of every `run.py` invocation, atomically (`.tmp` + `os.replace`), with
bounded retention. Failures are swallowed — a snapshot is best-effort and
must never break the pipeline.

Public API
----------
- `snapshot_store_db(repo_root, keep=30, now=None)`: take one snapshot.
  Returns `(path, sha256_hex)` for the new file, or `None` on skip / failure.
- `list_snapshots(repo_root)`: list `(path, mtime)` of existing snapshots.
- `_BACKUP_DIRNAME`, `_SNAPSHOT_REGEX`: module-level constants for tests.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import logging
import os
import re
import shutil
import sys

_BACKUP_DIRNAME = "backups"  # under data/
_SNAPSHOT_REGEX = re.compile(r"^store-(\d{8}-\d{6})\.db\.gz$")


def _now_stamp(now):
    if now is None:
        now = datetime.datetime.now()
    return now.strftime("%Y%m%d-%H%M%S")


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup_dir(repo_root):
    return os.path.join(repo_root, "data", _BACKUP_DIRNAME)


def _store_db(repo_root):
    return os.path.join(repo_root, "data", "store.db")


def list_snapshots(repo_root):
    """Return [(path, mtime), ...] of existing snapshots, oldest first."""
    bdir = _backup_dir(repo_root)
    if not os.path.isdir(bdir):
        return []
    out = []
    for name in os.listdir(bdir):
        if _SNAPSHOT_REGEX.match(name):
            full = os.path.join(bdir, name)
            out.append((full, os.path.getmtime(full)))
    out.sort(key=lambda x: x[1])
    return out


def snapshot_store_db(repo_root, keep=30, now=None):
    """Take one gzipped, SHA-verified snapshot of `data/store.db`.

    Atomic via `.tmp` + `os.replace`. Compressed with gzip level 6. Permissions
    on the result are 0600. Oldest snapshots beyond `keep` are unlinked.

    Returns `(target_path, sha256_hex)` on success, or `None` on any skip or
    failure (missing source, hash mismatch, IO error). Never raises.
    """
    log = logging.getLogger("presnapshot")
    src = _store_db(repo_root)
    if not os.path.isfile(src):
        return None
    try:
        pre_sha = _hash_file(src)
        bdir = _backup_dir(repo_root)
        os.makedirs(bdir, mode=0o700, exist_ok=True)
        stamp = _now_stamp(now)
        name = f"store-{stamp}.db.gz"
        target = os.path.join(bdir, name)
        # If a same-second snapshot already exists with identical bytes, skip
        # (true idempotency within one launchd tick).
        if os.path.isfile(target):
            with gzip.open(target, "rb") as f:
                cur = hashlib.sha256()
                for chunk in iter(lambda: f.read(65536), b""):
                    cur.update(chunk)
            if cur.hexdigest() == pre_sha:
                return target, pre_sha
        tmp = os.path.join(bdir, f".{name}.tmp")
        with open(src, "rb") as f_in, gzip.open(tmp, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        # Verify the compressed bytes round-trip back to the same SHA.
        post_sha = _hash_file(tmp)  # hash the gzipped blob for cheap check
        with gzip.open(tmp, "rb") as f_in:
            plain = hashlib.sha256()
            for chunk in iter(lambda: f_in.read(65536), b""):
                plain.update(chunk)
            plain_sha = plain.hexdigest()
        if plain_sha != pre_sha or post_sha == pre_sha:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            log.warning("presnapshot: integrity check failed pre=%s plain=%s gz=%s",
                        pre_sha[:12], plain_sha[:12], post_sha[:12])
            return None
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        # Rotate: keep newest `keep` by mtime.
        snaps = list_snapshots(repo_root)
        while len(snaps) > keep:
            old_path, _ = snaps.pop(0)
            try:
                os.unlink(old_path)
            except OSError as exc:
                log.warning("presnapshot: rotate failed %s: %s", old_path, exc)
        # Single stdout line so launchd.out.log always carries proof of life.
        print(f"[presnapshot] wrote {name} sha={pre_sha[:12]} kept={len(snaps)}",
              file=sys.stdout, flush=True)
        return target, pre_sha
    except Exception as exc:  # last-resort: snapshot is best-effort
        log.warning("presnapshot: failed: %s", exc)
        return None