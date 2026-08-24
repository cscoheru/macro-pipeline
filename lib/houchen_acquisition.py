"""yt-dlp subprocess adapter + frozen-caption pipeline (PR-1, hardened).

Hardening vs. the first Codex FAIL:
    - Real yt-dlp contract (P1-1): playlist via `{"entries":[...]}`, subtitle
      inventory via `--dump-json` `subtitles`/`automatic_captions`, output
      naming `<stem>.<lang>.<ext>`, JSON3 via `events[].segs[].utf8`.
    - Frozen-raw immutability (P0-1): unique per-attempt temp dir; no-replace
      content-addressed install via hard link; `verify_frozen_raw()` checks
      lstat-regular + containment + size + SHA before `already_frozen`.
    - Durability (P0-1): fsync file, then no-replace install, then fsync dir,
      then DB INSERT/COMMIT; any I/O failure leaves no raw row.
    - Error redaction (P0-3): single `redact()` entry point applied to every
      stderr / exception detail before it reaches SQLite / logs / CLI.
    - Bounded subprocess capture (P2-3): incremental `os.read` with a hard
      byte cap that kills the whole process group on overflow or timeout.

No module here touches lib/store.py or any macro path. All paths come from
`houchen_paths`, all DB writes are short transactions that commit immediately
(no write lock held across network I/O — P1-2).
"""
from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import houchen_paths
import houchen_schema


DEFAULT_YTDLP_BINARY = "yt-dlp"
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_STDERR_LIMIT = 4096          # redaction/truncation target for stderr
DEFAULT_STDOUT_LIMIT = 32 * 1024 * 1024   # 32 MiB cap on info/playlist JSON
DEFAULT_DOWNLOAD_BYTE_LIMIT = 5 * 1024 * 1024  # 5 MiB cap per caption file

OUT_SUCCESS = "success"
OUT_SKIPPED = "skipped"
OUT_MISSING = "missing"
OUT_AUTH_REQUIRED = "auth_required"
OUT_UNAVAILABLE = "unavailable"
OUT_RETRYABLE = "retryable"
OUT_TOOL_ERROR = "tool_error"
OUT_PERMANENT_ERROR = "permanent_error"
OUT_RAW_INTEGRITY_ERROR = "raw_integrity_error"

# Error classes that abort the whole candidate loop (P1-4): a global failure
# (tool missing, auth, video unavailable, timeout) must NOT be retried against
# a lower-priority candidate. A per-candidate download/parse failure (e.g. a
# high-priority manual json3 that fails to download) is NOT in this set, so the
# loop records it and falls through to the next candidate.
_GLOBAL_ERROR_CLASSES = frozenset({
    "tool_missing", "auth_required", "unavailable", "timeout",
})


# ---------------------------------------------------------------------------
# Error hierarchy (P0-3: every detail is redacted before persistence)
# ---------------------------------------------------------------------------

class AcquisitionError(Exception):
    def __init__(self, outcome: str, error_class: str, detail: str):
        super().__init__(f"{outcome}:{error_class}: {detail}")
        self.outcome = outcome
        self.error_class = error_class
        self.detail = detail


class ToolMissingError(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_TOOL_ERROR, "tool_missing", detail)


class TimeoutError_(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_RETRYABLE, "timeout", detail)


class AuthRequiredError(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_AUTH_REQUIRED, "auth_required", detail)


class UnavailableError(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_UNAVAILABLE, "unavailable", detail)


class PermanentError(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_PERMANENT_ERROR, "permanent_error", detail)


class RawIntegrityError(AcquisitionError):
    def __init__(self, detail: str):
        super().__init__(OUT_RAW_INTEGRITY_ERROR, "raw_integrity_error", detail)


class ResourceLimitError(AcquisitionError):
    """Raised when a subprocess's stdout/stderr/output file exceeds its bound
    (P2-3). The process group is killed BEFORE this is raised."""
    def __init__(self, detail: str):
        super().__init__(OUT_TOOL_ERROR, "output_limit", detail)


# ---------------------------------------------------------------------------
# Redaction (P0-3) — the single entry point for scrubbing secrets from any
# text that will be persisted or displayed.
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_SECRET_VALUE = r"[A-Za-z0-9._~+/=%-]{8,}"
_BEARER_RE = re.compile(r"(?i)\bbearer\s+" + _SECRET_VALUE)
_ASSIGN_RE = re.compile(
    r"(?i)\b(authorization|token|cookie|signature|sig|api[_-]?key|secret"
    r"|access[_-]?key)\s*[:=]\s*" + _SECRET_VALUE)
_ABS_PATH_RE = re.compile(r"(?:/Users|/home|/root|/private|/var|/tmp)/[^\s\"'<>]+")


def redact(text: str) -> str:
    """Scrub secrets/URLs/absolute paths from an error string.

    Replaces signed URLs, `Bearer <token>`, secret assignments and local
    absolute paths so no signed URL / cookie / token / local path survives
    into SQLite / logs / CLI. Returns a plain string safe to persist.
    """
    if not text:
        return ""
    s = _URL_RE.sub("<redacted-url>", text)
    s = _BEARER_RE.sub("<redacted>", s)
    s = _ASSIGN_RE.sub(r"\1=<redacted>", s)
    s = _ABS_PATH_RE.sub("<redacted-path>", s)
    return s


def _truncate_stderr(raw: bytes, limit: int = DEFAULT_STDERR_LIMIT) -> str:
    text = redact(raw.decode("utf-8", errors="replace"))
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[...stderr truncated; total {len(text)} bytes]"


# ---------------------------------------------------------------------------
# Bounded subprocess runner (P2-3)
# ---------------------------------------------------------------------------

def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _run_bounded(argv, *, timeout_sec, stdout_limit=DEFAULT_STDOUT_LIMIT,
                 stderr_limit=DEFAULT_STDERR_LIMIT, watch_path=None,
                 byte_limit=None):
    """Run argv (shell=False) with bounded incremental capture.

    Kills the WHOLE process group on timeout, on stdout/stderr overflow, or
    when a watched output file exceeds `byte_limit` (P2-3), raising a stable
    `ResourceLimitError` for the overflow cases instead of deadlocking or
    silently dropping bytes. Returns (returncode, stdout_bytes, stderr_text)
    where stderr_text is already redacted.
    """
    proc = subprocess.Popen(
        list(argv),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,   # enables whole-group kill
    )
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "out")
    sel.register(proc.stderr, selectors.EVENT_READ, "err")
    out = bytearray()
    err = bytearray()
    start = time.monotonic()
    try:
        while True:
            remaining = timeout_sec - (time.monotonic() - start)
            if remaining <= 0:
                _kill_group(proc)
                raise subprocess.TimeoutExpired(argv, timeout_sec)
            # Enforce a watched output-file size limit DURING the run (P2-3).
            if watch_path and byte_limit is not None:
                try:
                    if os.path.exists(watch_path) \
                            and os.path.getsize(watch_path) > byte_limit:
                        _kill_group(proc)
                        raise ResourceLimitError(
                            f"output exceeded byte_limit={byte_limit}")
                except OSError:
                    pass
            for key, _ in sel.select(timeout=min(0.2, remaining)):
                data = os.read(key.fd, 65536)
                if not data:
                    sel.unregister(key.fileobj)
                    continue
                if key.data == "out":
                    if len(out) + len(data) > stdout_limit:
                        _kill_group(proc)
                        raise ResourceLimitError(
                            f"stdout exceeded limit={stdout_limit}")
                    out.extend(data)
                else:
                    if len(err) + len(data) > stderr_limit:
                        _kill_group(proc)
                        raise ResourceLimitError(
                            f"stderr exceeded limit={stderr_limit}")
                    err.extend(data)
            if proc.poll() is not None:
                # drain whatever remains (bounded) and break
                for key, _ in list(sel.get_map().items()):
                    if key.fileobj is None:
                        continue
                    try:
                        data = os.read(key.fd, 65536)
                        if key.data == "out":
                            if len(out) + len(data) > stdout_limit:
                                _kill_group(proc)
                                raise ResourceLimitError(
                                    f"stdout exceeded limit={stdout_limit}")
                            out.extend(data)
                        elif key.data == "err":
                            if len(err) + len(data) > stderr_limit:
                                _kill_group(proc)
                                raise ResourceLimitError(
                                    f"stderr exceeded limit={stderr_limit}")
                            err.extend(data)
                    except OSError:
                        pass
                break
    finally:
        sel.close()
        proc.wait()

    err_text = redact(err.decode("utf-8", errors="replace"))
    return proc.returncode, bytes(out), err_text


def _run(argv, *, timeout_sec=DEFAULT_TIMEOUT_SEC,
         runner: Optional[Callable] = None,
         stdout_limit=DEFAULT_STDOUT_LIMIT, stderr_limit=DEFAULT_STDERR_LIMIT,
         watch_path=None, byte_limit=None):
    """Test seam: use an injected `runner(argv, timeout_sec=…)` when provided,
    else the bounded real runner.

    The injected runner may return a `CompletedProcess` OR a 3-tuple; both are
    normalized to the `(returncode, stdout_bytes, stderr_text_redacted)`
    contract used by every caller. Injected results are subject to the SAME
    stdout/stderr limits (P2-3).
    """
    if runner is not None:
        result = runner(argv, timeout_sec=timeout_sec)
        if hasattr(result, "returncode"):
            rc = result.returncode
            out = result.stdout or b""
            err_raw = result.stderr or b""
            err = redact(err_raw.decode("utf-8", errors="replace")
                         if isinstance(err_raw, bytes) else str(err_raw))
            if len(out) > stdout_limit:
                raise ResourceLimitError(f"stdout exceeded limit={stdout_limit}")
            if len(err) > stderr_limit:
                raise ResourceLimitError(f"stderr exceeded limit={stderr_limit}")
            return rc, out, err
        # 3-tuple: (rc, out_bytes, err_text).
        rc, out, err = result
        if len(out) > stdout_limit:
            raise ResourceLimitError(f"stdout exceeded limit={stdout_limit}")
        if len(err) > stderr_limit:
            raise ResourceLimitError(f"stderr exceeded limit={stderr_limit}")
        return rc, out, err
    return _run_bounded(argv, timeout_sec=timeout_sec,
                        stdout_limit=stdout_limit, stderr_limit=stderr_limit,
                        watch_path=watch_path, byte_limit=byte_limit)


# ---------------------------------------------------------------------------
# yt-dlp metadata-only calls (real contract)
# ---------------------------------------------------------------------------

def preflight_ytdlp(binary=DEFAULT_YTDLP_BINARY, runner=None) -> str:
    argv = [binary, "--version"]
    try:
        rc, out, err = _run(argv, timeout_sec=10, runner=runner)
    except FileNotFoundError as e:
        raise ToolMissingError(redact(str(e)))
    except subprocess.TimeoutExpired as e:
        raise ToolMissingError(redact(f"ytdlp --version timed out: {e}"))
    if rc != 0:
        raise ToolMissingError(f"ytdlp --version exited {rc}: {err}")
    version = out.decode("utf-8", errors="replace").strip()
    if not version:
        raise ToolMissingError("ytdlp --version returned empty output")
    return version


def playlist_entries(tab_url, *, binary=DEFAULT_YTDLP_BINARY, runner=None,
                     timeout_sec=DEFAULT_TIMEOUT_SEC):
    """Return the `entries` list from `yt-dlp --flat-playlist -J`.

    Real yt-dlp emits a single playlist info object with `entries`. We never
    expect a top-level JSON array (that was the original bug).
    """
    argv = [binary, "--flat-playlist", "-J", tab_url]
    try:
        rc, out, err = _run(argv, timeout_sec=timeout_sec, runner=runner)
    except FileNotFoundError as e:
        raise ToolMissingError(redact(str(e)))
    except subprocess.TimeoutExpired as e:
        raise TimeoutError_(redact(str(e)))
    if rc != 0:
        outcome = classify_exit(rc, err)
        if outcome == OUT_AUTH_REQUIRED:
            raise AuthRequiredError(err)
        if outcome == OUT_UNAVAILABLE:
            raise UnavailableError(err)
        if outcome == OUT_RETRYABLE:
            raise TimeoutError_(err)
        raise AcquisitionError(outcome, "catalog_failed", err)
    try:
        obj = json.loads(out.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise PermanentError(redact(f"flat-playlist JSON parse error: {e}"))
    entries = obj.get("entries") if isinstance(obj, dict) else None
    if not isinstance(entries, list):
        raise PermanentError("flat-playlist output has no 'entries' list")
    return entries


def info_json(video_id, *, binary=DEFAULT_YTDLP_BINARY, runner=None,
              timeout_sec=DEFAULT_TIMEOUT_SEC):
    """Return the full info dict from `yt-dlp --skip-download --dump-json`."""
    if not re.fullmatch(houchen_schema.VIDEO_ID_RE, video_id):
        raise PermanentError(f"invalid video_id: {video_id!r}")
    argv = [
        binary, "--skip-download", "--dump-json",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        rc, out, err = _run(argv, timeout_sec=timeout_sec, runner=runner)
    except FileNotFoundError as e:
        raise ToolMissingError(redact(str(e)))
    except subprocess.TimeoutExpired as e:
        raise TimeoutError_(redact(str(e)))
    if rc != 0:
        outcome = classify_exit(rc, err)
        if outcome == OUT_AUTH_REQUIRED:
            raise AuthRequiredError(err)
        if outcome == OUT_UNAVAILABLE:
            raise UnavailableError(err)
        if outcome == OUT_RETRYABLE:
            raise TimeoutError_(err)
        raise AcquisitionError(outcome, "info_failed", err)
    try:
        return json.loads(out.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise PermanentError(redact(f"info JSON parse error: {e}"))


def subtitle_tracks_from_info(info: dict) -> list["SubtitleTrack"]:
    """Read `subtitles` (manual) + `automatic_captions` (auto) from info JSON.

    Real shape: {"subtitles": {lang: [{ext, url, name}, ...]}, ...}.
    """
    tracks = []
    for kind, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
        lang_map = info.get(key) or {}
        if not isinstance(lang_map, dict):
            continue
        for lang, formats in lang_map.items():
            if not isinstance(formats, list):
                continue
            for fmt in formats:
                if isinstance(fmt, dict) and fmt.get("ext"):
                    tracks.append(SubtitleTrack(
                        language=lang, caption_kind=kind, format=fmt["ext"],
                    ))
    return tracks


# ---------------------------------------------------------------------------
# Caption selection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubtitleTrack:
    language: str
    caption_kind: str   # 'manual' | 'auto'
    format: str         # 'json3', 'vtt', ...

    def selection_key(self):
        kind = houchen_schema.CAPTION_KIND_PRIORITY.index(self.caption_kind) \
            if self.caption_kind in houchen_schema.CAPTION_KIND_PRIORITY else 99
        lang = houchen_schema.LANGUAGE_PRIORITY.index(self.language) \
            if self.language in houchen_schema.LANGUAGE_PRIORITY else 99
        fmt = houchen_schema.FORMAT_PRIORITY.index(self.format) \
            if self.format in houchen_schema.FORMAT_PRIORITY else 99
        return (kind, lang, fmt)


def select_subtitle(tracks) -> Optional["SubtitleTrack"]:
    chinese = [t for t in tracks if t.language in houchen_schema.LANGUAGE_PRIORITY]
    return min(chinese, key=lambda t: t.selection_key()) if chinese else None


def select_candidates(tracks) -> list["SubtitleTrack"]:
    chinese = [t for t in tracks if t.language in houchen_schema.LANGUAGE_PRIORITY]
    return sorted(chinese, key=lambda t: t.selection_key())


# ---------------------------------------------------------------------------
# Parsers (real JSON3 events/segs + VTT)
# ---------------------------------------------------------------------------

def _count_json3_obj(obj) -> int:
    if not isinstance(obj, dict):
        return 0
    cues = 0
    for ev in obj.get("events", []) or []:
        for seg in (ev.get("segs", []) or []) if isinstance(ev, dict) else []:
            t = seg.get("utf8") if isinstance(seg, dict) else None
            if isinstance(t, str) and t.strip():
                cues += 1
    return cues


def _parse_json3(text: str) -> int:
    text = text.strip()
    if not text:
        raise PermanentError("json3 empty")
    # Standard: single JSON object with events[].segs[].utf8.
    try:
        obj = json.loads(text)
        cues = _count_json3_obj(obj)
        if cues:
            return cues
        # Could be JSON Lines (one object per line).
    except json.JSONDecodeError:
        pass
    cues = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cues += _count_json3_obj(json.loads(line))
        except json.JSONDecodeError:
            continue
    if cues == 0:
        raise PermanentError("json3 has zero non-empty cues")
    return cues


def _parse_vtt(text: str) -> int:
    cues = 0
    in_cue = False
    has_text = False
    for line in text.splitlines():
        s = line.strip()
        if "-->" in s:
            in_cue = True
            has_text = False
            continue
        if in_cue:
            if s == "":
                if has_text:
                    cues += 1
                in_cue = False
                continue
            if s:
                has_text = True
    if in_cue and has_text:
        cues += 1
    if cues == 0:
        raise PermanentError("vtt has zero non-empty cues")
    return cues


def parse_caption(fmt: str, text: str) -> int:
    f = fmt.lower()
    if f == "json3":
        return _parse_json3(text)
    if f == "vtt":
        return _parse_vtt(text)
    raise PermanentError(f"unsupported caption format: {fmt}")


# ---------------------------------------------------------------------------
# Exit-code classification
# ---------------------------------------------------------------------------

def classify_exit(returncode: int, stderr_text: str) -> str:
    msg = stderr_text.lower()
    if "sign in" in msg or "cookie" in msg or "authentication" in msg:
        return OUT_AUTH_REQUIRED
    if "video unavailable" in msg or "private video" in msg or "removed" in msg:
        return OUT_UNAVAILABLE
    if returncode == 0:
        return OUT_SUCCESS
    if returncode == 101:
        return OUT_RETRYABLE
    return OUT_TOOL_ERROR


# ---------------------------------------------------------------------------
# SHA / fsync / no-replace install
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync_dir(path: str) -> None:
    """fsync the directory that holds a newly-installed file (durability).

    A directory-fsync failure is NOT silently swallowed (P0-4): it propagates
    so the caller aborts before writing a raw_caption row. Only the platform's
    explicit "directory fsync unsupported" errnos (ENOTSUP / EINVAL) are
    treated as documented best-effort, since the file fsync above already
    provides the hard durability guarantee on such platforms.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        if e.errno in (errno.ENOTSUP, errno.EINVAL):
            return
        raise


def _target_lstat(target: str):
    """lstat the content-addressed target; reject a symlink or any non-regular
    file (directory/FIFO/device/…). Returns the stat result, or None if the
    target does not exist (→ safe to create)."""
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise RawIntegrityError(
            f"content-addressed target is not a regular file: {target}"
        )
    return st


def install_content_addressed(src_path: str, content_sha: str, ext: str,
                              ) -> tuple[str, bool]:
    """Atomically install a temp file at its content-addressed target WITHOUT
    ever overwriting an existing target (P0-1 / P0-3).

    Returns (target_path, created). If the target already exists:
        - same SHA → reuse, bytes/mtime/inode untouched, created=False.
        - different SHA, or a symlink/FIFO/directory → RawIntegrityError.
    There is NO plain-rename fallback: a hard-link failure fails closed.
    """
    target = houchen_paths.caption_target_path(content_sha, ext)

    # Containment: the target must resolve under the canonical data root (a
    # symlinked captions dir would escape it).
    if not houchen_paths.is_within_data_root(target):
        raise RawIntegrityError(f"target escapes data root: {target}")

    # Reject a symlink / non-regular target BEFORE any install (P0-3).
    if _target_lstat(target) is not None:
        if sha256_file(target) != content_sha:
            raise RawIntegrityError(
                f"content-addressed target exists with mismatched SHA: {target}"
            )
        return target, False

    os.makedirs(os.path.dirname(target), exist_ok=True)

    # fsync the source file before it becomes the durable raw.
    with open(src_path, "rb") as f:
        os.fsync(f.fileno())

    try:
        # hard link = atomic no-replace install on the same filesystem.
        os.link(src_path, target)
    except FileExistsError:
        # A competitor installed between our check and link(); verify + reuse.
        st = _target_lstat(target)
        if st is None:
            raise RawIntegrityError("target appeared then vanished during install")
        if sha256_file(target) != content_sha:
            raise RawIntegrityError(
                f"content-addressed target exists with mismatched SHA: {target}"
            )
        return target, False
    except OSError as e:
        # Hard-link unsupported (EXDEV) or other → fail closed (P0-3). We do
        # NOT fall back to a plain rename(), which could overwrite a target
        # that appeared concurrently.
        raise RawIntegrityError(redact(f"no-replace install failed: {e}"))
    # Only after a successful link do we drop our own temp source.
    os.unlink(src_path)

    _fsync_dir(os.path.dirname(target))
    return target, True


# ---------------------------------------------------------------------------
# verify_frozen_raw (P0-1) — the single gate before `already_frozen`
# ---------------------------------------------------------------------------

def verify_frozen_raw(conn, video_id: str):
    """Validate an already-registered raw caption's file. Raises
    RawIntegrityError on any violation (not regular file, symlink, escaped
    path, size or SHA mismatch). Returns the row on success, None if not frozen.
    """
    row = conn.execute(
        "SELECT content_sha256, local_path, byte_count, format FROM raw_caption"
        " WHERE video_id=?", (video_id,)
    ).fetchone()
    if row is None:
        return None
    path = row["local_path"]
    try:
        st = os.lstat(path)
    except OSError as e:
        raise RawIntegrityError(redact(f"lstat failed: {e}"))
    if not stat.S_ISREG(st.st_mode):
        raise RawIntegrityError("raw caption is not a regular file (symlink/other)")
    if not houchen_paths.is_within_data_root(path):
        raise RawIntegrityError("raw caption path escapes the data root")
    if st.st_size != row["byte_count"]:
        raise RawIntegrityError(
            f"size mismatch: stored {row['byte_count']} vs disk {st.st_size}"
        )
    if sha256_file(path) != row["content_sha256"]:
        raise RawIntegrityError("SHA mismatch: stored vs disk")
    return row


# ---------------------------------------------------------------------------
# Download caption (unique per-attempt dir, deterministic discovery)
# ---------------------------------------------------------------------------

def download_caption(video_id: str, track: SubtitleTrack, *, dest_dir: str,
                     binary=DEFAULT_YTDLP_BINARY, runner=None,
                     timeout_sec=DEFAULT_TIMEOUT_SEC,
                     byte_limit=DEFAULT_DOWNLOAD_BYTE_LIMIT) -> str:
    """Download a subtitle into a unique per-attempt `dest_dir`.

    The output file is deterministically `<dest_dir>/<video_id>.<lang>.<ext>`.
    We verify that EXACT file exists after the call — no globbing (P1-1).
    Returns the resolved path.
    """
    if not re.fullmatch(houchen_schema.VIDEO_ID_RE, video_id):
        raise PermanentError(f"invalid video_id: {video_id!r}")
    if track.format not in {"json3", "vtt"}:
        raise PermanentError(f"PR-1 only freezes json3/vtt; got {track.format}")
    os.makedirs(dest_dir, exist_ok=True)
    expected = os.path.join(dest_dir, f"{video_id}.{track.language}.{track.format}")
    argv = [
        binary,
        "--skip-download",
        "--write-subs" if track.caption_kind == "manual" else "--write-auto-subs",
        "--sub-langs", track.language,
        "--sub-format", track.format,
        "--output", os.path.join(dest_dir, video_id),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        rc, out, err = _run(argv, timeout_sec=timeout_sec, runner=runner,
                            watch_path=expected, byte_limit=byte_limit)
    except FileNotFoundError as e:
        raise ToolMissingError(redact(str(e)))
    except subprocess.TimeoutExpired as e:
        raise TimeoutError_(redact(str(e)))
    except ResourceLimitError:
        # The watched output file exceeded byte_limit during the run; the
        # process group was already killed. Clean the partial file and surface
        # a permanent (non-retryable) candidate failure.
        _rmtree_if_exists(os.path.dirname(expected))
        raise PermanentError(
            f"download exceeded byte_limit={byte_limit} (killed during run)")
    if rc != 0:
        outcome = classify_exit(rc, err)
        if outcome == OUT_AUTH_REQUIRED:
            raise AuthRequiredError(err)
        if outcome == OUT_UNAVAILABLE:
            raise UnavailableError(err)
        if outcome == OUT_RETRYABLE:
            raise TimeoutError_(err)
        raise AcquisitionError(outcome, "download_failed", err)
    if not os.path.exists(expected):
        raise PermanentError(
            redact(f"download produced no output at expected path {expected}")
        )
    size = os.path.getsize(expected)
    if size == 0:
        os.remove(expected)
        raise PermanentError("download produced an empty file")
    if size > byte_limit:
        os.remove(expected)
        raise PermanentError(f"download exceeded byte_limit={byte_limit} (size={size})")
    return expected


# ---------------------------------------------------------------------------
# Freeze one video (short transactions, unique temp dir)
# ---------------------------------------------------------------------------

@dataclass
class FreezeResult:
    outcome: str
    error_class: Optional[str]
    detail: str
    video_id: str
    content_sha256: Optional[str] = None
    local_path: Optional[str] = None
    language: Optional[str] = None
    caption_kind: Optional[str] = None
    format: Optional[str] = None
    byte_count: Optional[int] = None
    cue_count: Optional[int] = None


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _record_attempt_committed(conn, *, video_id, run_id, stage, outcome,
                              error_class, detail, retryable, occurred_at) -> None:
    """Insert + COMMIT one corpus_attempt (short transaction; no lock held)."""
    att_id = houchen_schema.new_attempt_id()
    conn.execute(
        "INSERT INTO corpus_attempt"
        "(att_id, video_id, run_id, stage, outcome, error_class, detail,"
        " retryable, occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (att_id, video_id, run_id, stage, outcome, error_class, detail,
         retryable, occurred_at),
    )
    conn.commit()


def _is_retryable(outcome: str) -> int:
    return 1 if outcome in (OUT_RETRYABLE, OUT_TOOL_ERROR) else 0


def freeze_one(conn, video_id: str, *, run_id: str,
               binary=DEFAULT_YTDLP_BINARY, runner=None,
               timeout_sec=DEFAULT_TIMEOUT_SEC,
               byte_limit=DEFAULT_DOWNLOAD_BYTE_LIMIT,
               yt_version: Optional[str] = None,
               now: Optional[str] = None) -> FreezeResult:
    """Freeze the first valid Chinese subtitle for one video.

    Transactions are kept SHORT: every corpus_attempt row commits immediately;
    the raw_caption INSERT uses its own short BEGIN IMMEDIATE. No write lock
    is held across network or file I/O (P1-2).

    `yt_version` is computed ONCE by the runner and passed in (P2-3: avoids a
    per-video `--version` subprocess).
    """
    timestamp = now or _now()
    houchen_paths.verify_data_root()
    if yt_version is None:
        yt_version = preflight_ytdlp(binary=binary, runner=runner)

    # 1. already frozen? verify integrity first (P0-1).
    try:
        existing = verify_frozen_raw(conn, video_id)
    except RawIntegrityError as e:
        return _frozen_error(conn, video_id, run_id, e, timestamp)
    if existing is not None:
        _record_attempt_committed(
            conn, video_id=video_id, run_id=run_id, stage="freeze",
            outcome=OUT_SKIPPED, error_class="already_frozen",
            detail="row present; no network call", retryable=0,
            occurred_at=timestamp)
        return FreezeResult(OUT_SKIPPED, "already_frozen",
                            "already frozen (verified)", video_id)

    # 2. video must be cataloged (P1-6): do NOT insert an attempt row (which
    # would violate the FK); the runner surfaces a structured failure.
    video_row = conn.execute(
        "SELECT metadata_sha256, availability FROM video WHERE video_id=?",
        (video_id,)).fetchone()
    if video_row is None:
        return FreezeResult(OUT_MISSING, "video_not_cataloged",
                            "video row absent; run catalog first", video_id)
    if video_row["availability"] != "public":
        return _frozen_result(conn, video_id, run_id, timestamp,
                              outcome=OUT_UNAVAILABLE,
                              error_class="availability",
                              detail=f"availability={video_row['availability']}")
    source_meta_sha = video_row["metadata_sha256"]

    # 3. info JSON (network) — no DB txn held.
    try:
        info = info_json(video_id, binary=binary, runner=runner,
                         timeout_sec=timeout_sec)
    except AcquisitionError as e:
        return _frozen_result(conn, video_id, run_id, timestamp,
                              outcome=e.outcome, error_class=e.error_class,
                              detail=redact(e.detail))
    tracks = subtitle_tracks_from_info(info)
    _record_attempt_committed(
        conn, video_id=video_id, run_id=run_id, stage="subtitle_inventory",
        outcome=OUT_SUCCESS, error_class=None, detail=None, retryable=0,
        occurred_at=timestamp)

    candidates = select_candidates(tracks)
    if not candidates:
        return _frozen_result(conn, video_id, run_id, timestamp,
                              outcome=OUT_MISSING, error_class="no_chinese_track",
                              detail=f"tracks={[t.language for t in tracks]}")

    # 4. try candidates in priority order.
    houchen_store_ensure_dirs()
    last_error: Optional[AcquisitionError] = None
    for track in candidates:
        attempt_id = houchen_schema.new_attempt_id()
        dest_dir = houchen_paths.raw_tmp_attempt_dir(attempt_id)
        try:
            path = download_caption(video_id, track, dest_dir=dest_dir,
                                    binary=binary, runner=runner,
                                    timeout_sec=timeout_sec,
                                    byte_limit=byte_limit)

            with open(path, "rb") as f:
                text = f.read().decode("utf-8", errors="replace")
            cue_count = parse_caption(track.format, text)
            content_sha = sha256_file(path)
            # Record download SUCCESS only after the caption parses (P1-4), so a
            # malformed download shows as a single candidate failure, not a
            # success-then-failure pair.
            _record_attempt_committed(
                conn, video_id=video_id, run_id=run_id,
                stage="subtitle_download", outcome=OUT_SUCCESS,
                error_class=None, detail=None, retryable=0,
                occurred_at=timestamp)

            # install (no-replace) + fsync, then short INSERT/COMMIT.
            target, created = install_content_addressed(
                path, content_sha, track.format)
            byte_count = os.path.getsize(target)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO raw_caption"
                    "(video_id, language, caption_kind, format, content_sha256,"
                    " local_path, byte_count, cue_count, fetched_at,"
                    " yt_dlp_version, source_metadata_sha256)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (video_id, track.language, track.caption_kind, track.format,
                     content_sha, target, byte_count, cue_count, timestamp,
                     yt_version, source_meta_sha),
                )
                conn.execute("COMMIT")
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                # A competitor froze this video first. Verify the winner.
                try:
                    verify_frozen_raw(conn, video_id)
                    return _frozen_result(conn, video_id, run_id, timestamp,
                                          outcome=OUT_SKIPPED,
                                          error_class="race_lost",
                                          detail="another writer won")
                except RawIntegrityError as e:
                    return _frozen_error(conn, video_id, run_id, e, timestamp)

            _record_attempt_committed(
                conn, video_id=video_id, run_id=run_id, stage="freeze",
                outcome=OUT_SUCCESS, error_class=None, detail=None,
                retryable=0, occurred_at=timestamp)
            return FreezeResult(
                OUT_SUCCESS, None, "frozen", video_id,
                content_sha256=content_sha, local_path=target,
                language=track.language, caption_kind=track.caption_kind,
                format=track.format, byte_count=byte_count, cue_count=cue_count,
            )
        except AcquisitionError as e:
            last_error = e
            # clean our own temp dir only (never touch content-addressed files)
            _rmtree_if_exists(dest_dir)
            # Record the per-candidate failure as observable evidence (P1-4).
            _record_attempt_committed(
                conn, video_id=video_id, run_id=run_id,
                stage="subtitle_download", outcome=e.outcome,
                error_class=e.error_class, detail=redact(e.detail),
                retryable=_is_retryable(e.outcome), occurred_at=timestamp)
            if e.error_class in _GLOBAL_ERROR_CLASSES:
                break
            # candidate-level failure (download/parse) → try the next candidate.
        finally:
            # never leave our attempt temp dir behind.
            _rmtree_if_exists(dest_dir)

    if last_error is None:
        last_error = PermanentError("no candidates tried")
    return _frozen_result(conn, video_id, run_id, timestamp,
                          outcome=last_error.outcome,
                          error_class=last_error.error_class,
                          detail=redact(last_error.detail))


def _frozen_result(conn, video_id, run_id, timestamp, *, outcome, error_class,
                   detail) -> FreezeResult:
    _record_attempt_committed(
        conn, video_id=video_id, run_id=run_id, stage="freeze",
        outcome=outcome, error_class=error_class, detail=redact(detail),
        retryable=_is_retryable(outcome), occurred_at=timestamp)
    return FreezeResult(outcome, error_class, redact(detail), video_id)


def _frozen_error(conn, video_id, run_id, e: RawIntegrityError,
                  timestamp) -> FreezeResult:
    _record_attempt_committed(
        conn, video_id=video_id, run_id=run_id, stage="freeze",
        outcome=OUT_RAW_INTEGRITY_ERROR, error_class=e.error_class,
        detail=redact(e.detail), retryable=0, occurred_at=timestamp)
    return FreezeResult(OUT_RAW_INTEGRITY_ERROR, e.error_class,
                        redact(e.detail), video_id)


def _rmtree_if_exists(path: str) -> None:
    import shutil
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def houchen_store_ensure_dirs() -> None:
    # Imported lazily to avoid a hard import cycle (store imports paths only).
    import houchen_store
    houchen_store.ensure_dirs()
