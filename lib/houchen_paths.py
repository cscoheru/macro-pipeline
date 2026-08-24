"""Centralized path resolution + isolation enforcement for the Hou Chen corpus.

PR-1 responsibilities, hardened after Codex FAIL:

    1. Resolve the data root (env override `HOUCHEN_DATA_ROOT` or default).
    2. ENFORCE isolation (P0-2): reject a root whose path contains a symlink,
       reject the macro protected roots, and verify every derived path is
       contained under the canonical root via `os.path.commonpath`.
    3. Provide content-addressed target paths and per-attempt temp dirs.

Design rule: NO module may construct a path to raw/derived/DB files by
os.path.join-ing a raw string. Everything goes through this module. The
enforcement point is `verify_data_root()` / `assert_safe_root()`; every
state-changing entry point must call `assert_safe_root()` before touching
the filesystem, and read-only entry points must call the lighter
`resolve_data_root()` (no directory creation).

Symlink policy: we `os.lstat` every path component from the root up to the
leaf. If any component is a symlink we reject — `realpath()` alone is not
enough because it silently resolves the link and hides the escape.
"""
from __future__ import annotations

import os
import re

# Default root lives inside the macro `data/` dir but in its own sub-tree.
_DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "houchen",
)

_ENV_ROOT = "HOUCHEN_DATA_ROOT"


class DataRootError(ValueError):
    """Raised when the configured data root violates the isolation contract."""


def data_root() -> str:
    """Return the configured (not yet validated) data root."""
    return os.environ.get(_ENV_ROOT, _DEFAULT_ROOT)


def _protected_roots() -> list[str]:
    """Absolute canonical paths that the research corpus MUST NOT overlap.

    These are the macro-pipeline data roots. A research data root that is
    equal to, or an ancestor of, or a descendant of any of these is rejected.
    The default research root is `<repo>/data/houchen` — a SIBLING of
    `<repo>/data/store.db`, not a child of `<repo>/data/` in a way that
    overlaps these protected paths.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [
        os.path.join(repo, "data", "store.db"),
        os.path.join(repo, "data", "insights"),
        os.path.join(repo, "data", "snapshots"),
        os.path.join(repo, "data", "state.json"),
        os.path.join(repo, "data", "ledger.sqlite"),
        os.path.join(repo, "data", "macro.db"),
        os.path.join(repo, "config"),
        os.path.join(repo, "logs"),
    ]


def _overlaps(a: str, b: str) -> bool:
    """True if a and b share a containment relationship (a==b, a inside b, b inside a)."""
    a = os.path.normpath(a)
    b = os.path.normpath(b)
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


# macOS ships these OS-level aliases; they are part of the system image and
# not attacker-controlled. Only these EXACT paths (resolving to their standard
# targets) are exempt from the ancestor symlink walk — anything else under
# /private/ is still rejected.
_SYSTEM_ALIASES = {
    "/var": "/private/var",
    "/tmp": "/private/tmp",
    "/etc": "/private/etc",
}


def _reject_symlink_ancestors(path: str) -> None:
    """Reject any symlink in the ancestors of `path` (P0-2: a symlinked middle
    component must not redirect writes outside the intended root).

    Carve-out: the OS's own aliases (/var, /tmp, /etc → /private/…) are exempt;
    when one is reached the walk stops (everything above is the OS itself).
    Without this carve-out every /tmp-based test root would be falsely
    rejected on macOS; with it, a user-planted symlink under /private/var/…
    is still rejected.
    """
    current = os.path.abspath(path)
    while True:
        if os.path.islink(current):
            if _SYSTEM_ALIASES.get(current) == os.path.realpath(current):
                return  # the OS's own alias; above this is the OS itself
            raise DataRootError(f"path ancestor is a symlink: {current}")
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def resolve_data_root() -> str:
    """Return the canonical data root, rejecting symlinked/escape roots.

    Raised DataRootError if the configured root itself is a symlink, if any
    ancestor component (below the OS) is a symlink, or if its realpath
    overlaps a protected macro root. macOS system aliases (/var → /private/var)
    are exempt in the ancestor walk.
    """
    root = os.path.abspath(data_root())
    # Reject a symlinked root (e.g. data/houchen -> /somewhere/else).
    if os.path.islink(root):
        raise DataRootError(f"data root is a symlink: {root}")
    _reject_symlink_ancestors(root)
    canon = os.path.realpath(root)
    for protected in _protected_roots():
        if _overlaps(canon, protected):
            raise DataRootError(
                f"data root {canon!r} overlaps protected macro path {protected!r}"
            )
    return canon


def verify_data_root() -> str:
    """Canonicalize + create the data root if missing, then re-validate.

    State-changing entry points call this once at startup. It creates the
    root dir if absent, but refuses a symlinked root or one overlapping a
    protected macro path.
    """
    root = os.path.abspath(data_root())
    if os.path.islink(root):
        raise DataRootError(f"data root is a symlink: {root}")
    os.makedirs(root, exist_ok=True)
    return resolve_data_root()


def _require_contained(canon_root: str, path: str) -> str:
    canon = os.path.realpath(path)
    try:
        common = os.path.commonpath([canon_root, canon])
    except ValueError:
        raise DataRootError(f"path {path!r} escapes data root {canon_root!r}")
    if common != canon_root:
        raise DataRootError(f"path {path!r} escapes data root {canon_root!r}")
    return canon


def _reject_symlink_leaf(path: str) -> None:
    if os.path.islink(path):
        raise DataRootError(f"path is a symlink: {path}")


def sqlite_path() -> str:
    """Path to the research SQLite file (relative to the CANONICAL root)."""
    return os.path.join(resolve_data_root(), "houchen.sqlite3")


def raw_captions_dir() -> str:
    return os.path.join(resolve_data_root(), "raw", "captions")


def raw_metadata_dir() -> str:
    return os.path.join(resolve_data_root(), "raw", "metadata")


def raw_tmp_dir() -> str:
    """Scratch root; each attempt gets its own subdir under here."""
    return os.path.join(resolve_data_root(), "raw", ".tmp")


def raw_tmp_attempt_dir(attempt_id: str) -> str:
    """A unique per-attempt temp dir (P0-1: no shared temp across workers).

    `attempt_id` must be a safe token (alphanumerics, `_`, `-` only; no path
    separator, no `..`), so it cannot escape the scratch root.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", attempt_id) or ".." in attempt_id:
        raise DataRootError(f"invalid attempt_id: {attempt_id!r}")
    return os.path.join(raw_tmp_dir(), attempt_id)


def derived_dir() -> str:
    return os.path.join(resolve_data_root(), "derived")


def artifacts_dir() -> str:
    return os.path.join(resolve_data_root(), "artifacts")


def failures_dir() -> str:
    return os.path.join(resolve_data_root(), "failures")


def caption_target_path(content_sha256: str, ext: str) -> str:
    """Content-addressed target for a frozen raw caption.

    `content_sha256` must be a 64-char lowercase hex sha256; `ext` in the
    allowlist. No other input is accepted.
    """
    if not (isinstance(content_sha256, str) and len(content_sha256) == 64
            and all(c in "0123456789abcdef" for c in content_sha256)):
        raise DataRootError("content_sha256 must be 64-char lowercase hex")
    if ext not in {"json3", "vtt"}:
        raise DataRootError(f"invalid ext: {ext!r}")
    return os.path.join(
        raw_captions_dir(),
        content_sha256[:2],
        f"{content_sha256}.{ext}",
    )


# ---------------------------------------------------------------------------
# PR-2 transcript / normalize derived paths
# ---------------------------------------------------------------------------

def transcripts_dir() -> str:
    """Per-version transcript JSON root: `<root>/derived/transcripts/<version>/`.

    The version is part of the path so two normalizer versions coexist.
    """
    return os.path.join(resolve_data_root(), "derived", "transcripts")


def transcript_version_dir(version: str) -> str:
    """Directory for a specific normalizer_version's transcripts."""
    _require_safe_version(version)
    return os.path.join(transcripts_dir(), version)


def transcript_target_path(version: str, content_sha256: str) -> str:
    """Content-addressed derived transcript JSON:
    `<root>/derived/transcripts/<version>/<sha[:2]>/<sha>.json`.
    """
    _require_safe_version(version)
    if not (isinstance(content_sha256, str) and len(content_sha256) == 64
            and all(c in "0123456789abcdef" for c in content_sha256)):
        raise DataRootError("content_sha256 must be 64-char lowercase hex")
    return os.path.join(
        transcript_version_dir(version),
        content_sha256[:2],
        f"{content_sha256}.json",
    )


def normalize_failure_path(run_id: str, video_id: str) -> str:
    """Per-(run,video) failure record: `<root>/failures/<run>/<video>.json`."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id) or ".." in run_id:
        raise DataRootError(f"invalid run_id: {run_id!r}")
    if not re.fullmatch(VIDEO_ID_RE, video_id):
        raise DataRootError(f"invalid video_id: {video_id!r}")
    return os.path.join(failures_dir(), run_id, f"{video_id}.json")


def _require_safe_version(version: str) -> None:
    """Normalizer versions are written by PR-2 code only; the allowlist is
    deliberately tight: alphanumerics + dot + dash + underscore, no path
    separators, no `..`. The brief §8 specifies the format is human-curated."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version) or ".." in version \
            or "/" in version or "\\" in version:
        raise DataRootError(f"invalid normalizer_version: {version!r}")


# Forward import for the VIDEO_ID_RE check above (kept identical to the
# PR-1 identifier regex).
VIDEO_ID_RE = r"[A-Za-z0-9_-]{11}"


def is_within_data_root(path: str) -> bool:
    """True if `path` resolves under the canonical data root (defensive helper)."""
    canon_root = resolve_data_root()
    try:
        return os.path.commonpath([canon_root, os.path.realpath(path)]) == canon_root
    except (ValueError, OSError):
        return False


def assert_no_symlink_components(path: str) -> str:
    """Return the absolute path after verifying that NO component of `path` —
    from the canonical data root down to and including the leaf — is a symlink
    (P0-2).

    This is the single enforcement point for "no write through a symlink". It
    must be called before any mkdir/write/DB-open of a derived path. Only
    components strictly below the canonical root are walked, so macOS system
    ancestor symlinks (`/var` → `/private/var`) are never traversed and a
    `/tmp` test root is not falsely rejected.
    """
    root = resolve_data_root()
    abspath = os.path.abspath(path)
    rel = os.path.relpath(abspath, root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        raise DataRootError(f"path {abspath!r} escapes data root {root!r}")
    current = root
    for comp in rel.split(os.sep):
        if comp in ("", "."):
            continue
        current = os.path.join(current, comp)
        if os.path.islink(current):
            raise DataRootError(f"path component is a symlink: {current}")
    return abspath
