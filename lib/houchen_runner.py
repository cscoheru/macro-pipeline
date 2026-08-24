"""Pipeline orchestration for the Hou Chen research corpus (PR-1, hardened).

P1-2 (durability): every state-changing entry point commits its terminal
state BEFORE returning (or re-raising). No write transaction is held across
network or file I/O — attempts and runs each commit in short transactions.

P1-5 (single state semantics): pending scope selection, status and coverage
all derive from `houchen_schema.video_state()` / `is_pending()` so they can
never disagree. Default `fetch-captions --pending` selects only `pending` and
`retryable` videos; `missing`/`auth_required`/`unavailable`/`permanent_error`
are terminal and only re-run on explicit override.

P2-3: `yt-dlp --version` is probed ONCE per run and passed down to each
freeze, so a 637-video fetch does not spawn ~638 version subprocesses.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from typing import Callable, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import houchen_acquisition as acq
import houchen_normalizer  # PR-2: deterministic transcript normalizer
import houchen_paths
import houchen_schema
import houchen_store


DEFAULT_NORMALIZER_NAME = houchen_normalizer.NORMALIZER_NAME
DEFAULT_NORMALIZER_VERSION = houchen_normalizer.NORMALIZER_VERSION


DEFAULT_CHANNEL_HANDLE = "@flipradio_fearnation"
DEFAULT_CHANNEL_URL = "https://www.youtube.com/@flipradio_fearnation"
CATALOG_TABS = ("videos", "streams", "shorts")

_RUN_CONFIG = {
    "channel_url": DEFAULT_CHANNEL_URL,
    "catalog_tabs": list(CATALOG_TABS),
    "language_priority": list(houchen_schema.LANGUAGE_PRIORITY),
    "format_priority": list(houchen_schema.FORMAT_PRIORITY),
    "caption_kind_priority": list(houchen_schema.CAPTION_KIND_PRIORITY),
}


def _config_sha256() -> str:
    return hashlib.sha256(
        json.dumps(_RUN_CONFIG, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _tool_versions_json(yt_version: str) -> str:
    import platform
    return json.dumps(
        {"yt_dlp": yt_version, "python": platform.python_version()},
        sort_keys=True,
    )


def _insert_run(conn, run_id, kind, started_at, status="running"):
    conn.execute(
        "INSERT INTO corpus_run"
        "(run_id, kind, started_at, finished_at, status, config_sha256,"
        " tool_versions_json) VALUES (?,?,?,?,?,?,?)",
        (run_id, kind, started_at, None, status, _config_sha256(),
         _tool_versions_json(_DETECTED_VERSION.get("v", ""))),
    )
    conn.commit()


def _finish_run(conn, run_id, status, summary=None, error_class=None,
                error_detail=None):
    conn.execute(
        "UPDATE corpus_run SET finished_at=?, status=?, summary_json=?,"
        " error_class=?, error_detail=? WHERE run_id=?",
        (_now(), status, json.dumps(summary, sort_keys=True) if summary else None,
         error_class, error_detail, run_id),
    )
    conn.commit()


_DETECTED_VERSION = {"v": ""}


# ---------------------------------------------------------------------------
# preflight (P1-2: commit terminal state before return)
# ---------------------------------------------------------------------------

def preflight(conn, *, binary=acq.DEFAULT_YTDLP_BINARY, runner=None) -> dict:
    started = _now()
    run_id = houchen_schema.new_run_id()
    status = "success"
    error_class = None
    error_detail = None
    yt_version = ""
    try:
        yt_version = acq.preflight_ytdlp(binary=binary, runner=runner)
        _DETECTED_VERSION["v"] = yt_version
        houchen_store.ensure_dirs()
    except acq.AcquisitionError as e:
        status = "failed"
        error_class = e.error_class
        error_detail = acq.redact(e.detail)
    except OSError as e:
        status = "failed"
        error_class = "dir_create"
        error_detail = acq.redact(str(e))

    _insert_run(conn, run_id, "preflight", started, status="running")
    _finish_run(conn, run_id, status,
                summary={"yt_dlp_version": yt_version,
                         "data_root": houchen_paths.resolve_data_root()},
                error_class=error_class, error_detail=error_detail)
    if status == "failed":
        raise acq.AcquisitionError("tool_error", error_class or "preflight",
                                   error_detail or "preflight failed")
    return {"ok": True, "yt_dlp_version": yt_version,
            "data_root": houchen_paths.resolve_data_root()}


# ---------------------------------------------------------------------------
# catalog (P1-2: per-tab commit + partial evidence; P2-2: --limit honored)
# ---------------------------------------------------------------------------

def run_catalog(conn, *, channel_url=DEFAULT_CHANNEL_URL,
                binary=acq.DEFAULT_YTDLP_BINARY, runner=None,
                tabs=CATALOG_TABS, limit=None, dry_run=False) -> dict:
    _validate_limit(limit)
    started = _now()
    yt_version = acq.preflight_ytdlp(binary=binary, runner=runner)
    _DETECTED_VERSION["v"] = yt_version

    summary = {"tabs": {}, "videos_discovered": 0, "videos_upserted": 0,
               "duplicates_skipped": 0, "dry_run": dry_run}
    overall = "success"

    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "catalog", started, "running")

    for tab in tabs:
        tab_summary = {"status": "success", "enumerated": 0, "upserted": 0,
                       "duplicates": 0, "error": None}
        try:
            entries = acq.playlist_entries(
                f"{channel_url}/{tab}", binary=binary, runner=runner)
        except acq.AcquisitionError as e:
            tab_summary["status"] = "failed"
            tab_summary["error"] = {"outcome": e.outcome,
                                    "error_class": e.error_class,
                                    "detail": acq.redact(e.detail)}
            overall = "partial"
            summary["tabs"][tab] = tab_summary
            continue
        if limit is not None:
            entries = list(entries)[:limit]
        tab_summary["enumerated"] = len(entries)
        summary["videos_discovered"] += len(entries)
        if not dry_run:
            collection_id = _ensure_collection(conn, tab, started)
            for entry in entries:
                upserted, dup = _upsert_video(conn, entry, started)
                tab_summary["upserted"] += int(upserted)
                summary["videos_upserted"] += int(upserted)
                tab_summary["duplicates"] += int(dup)
                summary["duplicates_skipped"] += int(dup)
                _ensure_membership(conn, entry.get("id", ""), collection_id)
            # Commit this tab's batch BEFORE moving on (P1-2).
            conn.commit()
        summary["tabs"][tab] = tab_summary

    if not dry_run:
        _finish_run(conn, run_id, overall, summary=summary)
    summary["run_id"] = run_id
    summary["status"] = overall
    return summary


def _ensure_collection(conn, tab, enumerated_at):
    import uuid
    row = conn.execute(
        "SELECT collection_id FROM video_collection WHERE collection_name=?",
        (tab,)).fetchone()
    if row:
        return row["collection_id"]
    cid = f"hccol_{uuid.uuid7().hex}"
    conn.execute(
        "INSERT INTO video_collection(collection_id, collection_name, enumerated_at)"
        " VALUES (?,?,?)", (cid, tab, enumerated_at))
    return cid


def _ensure_membership(conn, video_id, collection_id):
    if not video_id or not _valid_video_id(video_id):
        return
    conn.execute(
        "INSERT OR IGNORE INTO video_collection_membership(video_id, collection_id)"
        " VALUES (?,?)", (video_id, collection_id))


def _valid_video_id(vid):
    import re
    return bool(re.fullmatch(houchen_schema.VIDEO_ID_RE, vid))


def _validate_limit(limit):
    """Reject a negative `--limit` (P2-4) before it is silently interpreted as
    a Python negative slice. None and >=0 pass; <0 raises ValueError."""
    if limit is not None and limit < 0:
        raise ValueError(f"--limit must be >= 0, got {limit}")


def _video_exists(conn, video_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM video WHERE video_id=?", (video_id,)
    ).fetchone() is not None


def _upsert_video(conn, entry, now):
    import re
    vid = entry.get("id")
    if not vid or not _valid_video_id(vid):
        return False, False
    title = entry.get("title") or ""
    description = entry.get("description") or ""
    duration = entry.get("duration")
    live = entry.get("live_status") or entry.get("was_live")
    availability = entry.get("availability", "public")
    if availability not in ("public", "unlisted", "private", "deleted",
                            "region_blocked", "unavailable"):
        availability = "public"
    content_kind = "video"
    if "/shorts/" in (entry.get("url") or ""):
        content_kind = "short"
    elif entry.get("live_status") == "is_live" or entry.get("is_live"):
        content_kind = "stream"
    elif entry.get("was_live"):
        content_kind = "live_replay"

    meta_blob = json.dumps({
        "title": title, "description": description, "duration_sec": duration,
        "live_status": live, "availability": availability,
        "content_kind": content_kind,
    }, sort_keys=True, ensure_ascii=False).encode()
    new_sha = hashlib.sha256(meta_blob).hexdigest()

    published = None
    if isinstance(entry.get("timestamp"), (int, float)):
        published = _iso_from_unix(int(entry["timestamp"]))

    existing = conn.execute(
        "SELECT discovered_at FROM video WHERE video_id=?", (vid,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO video"
            "(video_id, channel_id, channel_handle, canonical_url, title, description,"
            " published_at, duration_sec, live_status, availability, content_kind,"
            " discovered_at, last_seen_at, metadata_sha256)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, entry.get("channel_id"), entry.get("channel"),
             entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
             title, description, published,
             duration if isinstance(duration, int) else None,
             live, availability, content_kind, now, now, new_sha))
        return True, False
    conn.execute(
        "UPDATE video SET title=?, description=?, duration_sec=?, live_status=?,"
        " availability=?, content_kind=?, last_seen_at=?, metadata_sha256=?"
        " WHERE video_id=?",
        (title, description, duration if isinstance(duration, int) else None,
         live, availability, content_kind, now, new_sha, vid))
    return False, False


def _iso_from_unix(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# fetch-captions (P1-5: single pending semantics; P1-6: membership check)
# ---------------------------------------------------------------------------

def run_fetch_captions(conn, *, video_ids=None, pending_only=True,
                       include_terminal=False, limit=None,
                       binary=acq.DEFAULT_YTDLP_BINARY, runner=None,
                       dry_run=False) -> dict:
    _validate_limit(limit)

    summary = {"scope_count": 0, "frozen": 0, "skipped": 0,
               "missing": 0, "auth_required": 0, "unavailable": 0,
               "retryable": 0, "tool_error": 0, "permanent_error": 0,
               "raw_integrity_error": 0, "dry_run": dry_run}

    # P2-1: reject an explicit, uncataloged video ID BEFORE any subtitle
    # network call, and persist a run-level failure with the offending IDs.
    if video_ids is not None:
        uncataloged = [v for v in video_ids
                       if _valid_video_id(v) and not _video_exists(conn, v)]
        if uncataloged:
            started = _now()
            run_id = houchen_schema.new_run_id()
            if not dry_run:
                _insert_run(conn, run_id, "caption_fetch", started, "running")
                _finish_run(conn, run_id, "failed",
                            summary={"uncataloged_ids": uncataloged},
                            error_class="uncataloged_video",
                            error_detail="uncataloged: " + ",".join(uncataloged))
            summary["uncataloged_ids"] = uncataloged
            summary["run_id"] = run_id
            summary["status"] = "failed"
            return summary

    started = _now()
    yt_version = acq.preflight_ytdlp(binary=binary, runner=runner)
    _DETECTED_VERSION["v"] = yt_version

    scope = _select_scope(conn, video_ids=video_ids, pending_only=pending_only,
                          include_terminal=include_terminal)
    if limit is not None:
        scope = list(scope)[:limit]
    summary["scope_count"] = len(scope)

    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "caption_fetch", started, "running")

    if dry_run:
        summary["run_id"] = run_id
        summary["status"] = "dry_run"
        return summary

    overall = "success"
    for vid in scope:
        result = acq.freeze_one(conn, vid, run_id=run_id,
                                binary=binary, runner=runner,
                                yt_version=yt_version)
        bucket = "frozen" if result.outcome == acq.OUT_SUCCESS else result.outcome
        summary[bucket] = summary.get(bucket, 0) + 1
        if bucket in ("retryable", "tool_error", "raw_integrity_error"):
            overall = "partial"

    _finish_run(conn, run_id, overall, summary=summary)
    summary["run_id"] = run_id
    summary["status"] = overall
    return summary


def _select_scope(conn, *, video_ids=None, pending_only=True,
                  include_terminal=False) -> list[str]:
    if video_ids is not None:
        return [v for v in video_ids if _valid_video_id(v)]
    if pending_only:
        # Single SQL pass (P1-3), no per-video N+1.
        return houchen_schema.pending_video_ids(conn)
    rows = conn.execute(
        "SELECT video_id FROM video ORDER BY discovered_at ASC").fetchall()
    return [r["video_id"] for r in rows]


# ---------------------------------------------------------------------------
# normalize (PR-2: deterministic transcript normalizer layer)
# ---------------------------------------------------------------------------

def _select_normalize_scope(conn, *, video_ids=None,
                            pending_only=True) -> list[str]:
    """Pick videos that need a `transcript_version` row.

    Default: videos whose caption is frozen AND no successful transcript_version
    row exists for the current (normalizer_name, normalizer_version). Single SQL
    pass (P1-3: no N+1).

    Explicit `video_ids` mode validates the IDs up-front (P2-1) and returns
    only those whose raw_caption exists; uncataloged IDs are caught by the
    runner caller.
    """
    if video_ids is not None:
        return [v for v in video_ids
                if _valid_video_id(v) and _raw_caption_exists(conn, v)]
    if pending_only:
        sql = (
            "SELECT v.video_id"
            " FROM video v"
            " JOIN raw_caption rc ON rc.video_id = v.video_id"
            " LEFT JOIN transcript_version tv"
            "    ON tv.video_id = v.video_id"
            "   AND tv.normalizer_name = ?"
            "   AND tv.normalizer_version = ?"
            "   AND tv.status = 'ok'"
            " WHERE tv.transcript_version_id IS NULL"
            " ORDER BY v.discovered_at ASC"
        )
        return [r[0] for r in conn.execute(
            sql, (DEFAULT_NORMALIZER_NAME, DEFAULT_NORMALIZER_VERSION)).fetchall()]
    # include_terminal mode = include already-normalized videos (idempotent rerun).
    rows = conn.execute(
        "SELECT v.video_id FROM video v"
        " JOIN raw_caption rc ON rc.video_id = v.video_id"
        " ORDER BY v.discovered_at ASC").fetchall()
    return [r["video_id"] for r in rows]


def _raw_caption_exists(conn, video_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM raw_caption WHERE video_id=?", (video_id,)
    ).fetchone() is not None


def _record_normalize_attempt(conn, *, video_id, run_id, outcome,
                             error_class=None, detail=None, retryable=0):
    att_id = houchen_schema.new_attempt_id()
    conn.execute(
        "INSERT INTO corpus_attempt"
        "(att_id, video_id, run_id, stage, outcome, error_class,"
        " detail, retryable, occurred_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (att_id, video_id, run_id, "normalize", outcome,
         error_class, detail, retryable, _now()))
    return att_id


def run_normalize(conn, *, video_ids=None, pending_only=True,
                 limit=None, dry_run=False,
                 normalizer_name=DEFAULT_NORMALIZER_NAME,
                 normalizer_version=DEFAULT_NORMALIZER_VERSION) -> dict:
    """PR-2: produce `transcript_version` + `transcript_segment` rows for
    videos whose raw captions are already frozen.

    Returns a summary dict; never raises (per-video failures become
    `outcome='normalize_failed'` corpus_attempt rows).
    """
    if normalizer_name != DEFAULT_NORMALIZER_NAME \
            or normalizer_version != DEFAULT_NORMALIZER_VERSION:
        raise ValueError(
            f"only normalizer {DEFAULT_NORMALIZER_NAME}@{DEFAULT_NORMALIZER_VERSION}"
            f" is supported in PR-2 v1; got {normalizer_name}@{normalizer_version}")
    _validate_limit(limit)

    summary = {
        "scope_count": 0, "normalized": 0, "skipped_already": 0,
        "failed": 0, "dry_run": dry_run,
        "normalizer": {"name": normalizer_name, "version": normalizer_version},
    }

    # P2-1: reject an explicit, uncataloged video ID BEFORE any file read,
    # and persist a run-level failure with the offending IDs.
    if video_ids is not None:
        uncataloged = [v for v in video_ids
                       if _valid_video_id(v) and not _video_exists(conn, v)]
        if uncataloged:
            started = _now()
            run_id = houchen_schema.new_run_id()
            if not dry_run:
                _insert_run(conn, run_id, "normalize", started, "running")
                _finish_run(conn, run_id, "failed",
                            summary={"uncataloged_ids": uncataloged},
                            error_class="uncataloged_video",
                            error_detail="uncataloged: " + ",".join(uncataloged))
            summary["uncataloged_ids"] = uncataloged
            summary["run_id"] = run_id
            summary["status"] = "failed"
            return summary

    scope = _select_normalize_scope(conn, video_ids=video_ids,
                                    pending_only=pending_only)
    if limit is not None:
        scope = list(scope)[:limit]
    summary["scope_count"] = len(scope)

    started = _now()
    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "normalize", started, "running")

    if dry_run:
        summary["run_id"] = run_id
        summary["status"] = "dry_run"
        return summary

    overall = "success"
    for vid in scope:
        rc = conn.execute(
            "SELECT video_id, format, content_sha256, local_path"
            " FROM raw_caption WHERE video_id=?", (vid,)).fetchone()
        if rc is None:
            # The scope query filtered by raw_caption existence; defensive only.
            summary["skipped_already"] += 1
            continue
        try:
            houchen_paths.verify_data_root()
            result = houchen_normalizer.transcribe_video(
                video_id=vid,
                raw_caption_path=rc["local_path"],
                raw_caption_sha256=rc["content_sha256"],
                raw_format=rc["format"],
                created_at=started,
            )
        except ValueError as e:
            summary["failed"] += 1
            _record_normalize_attempt(conn, video_id=vid, run_id=run_id,
                                      outcome="normalize_failed",
                                      error_class="parse_error",
                                      detail=acq.redact(str(e)))
            conn.commit()
            _write_normalize_failure_artifact(run_id, vid, error=str(e))
            overall = "partial"
            continue
        except OSError as e:
            summary["failed"] += 1
            _record_normalize_attempt(conn, video_id=vid, run_id=run_id,
                                      outcome="normalize_failed",
                                      error_class="io_error",
                                      detail=acq.redact(str(e)))
            conn.commit()
            overall = "partial"
            continue

        # Persist transcript_version + transcript_segment rows. Idempotent:
        # the UNIQUE(video_id, raw_caption_sha256, normalizer_*) constraint
        # catches re-runs; we treat IntegrityError as a no-op success.
        tv_id = _persist_transcript_version(conn, run_id, result)
        if tv_id is None:
            summary["skipped_already"] += 1
            _record_normalize_attempt(conn, video_id=vid, run_id=run_id,
                                      outcome="skipped")
            conn.commit()
            continue
        _record_normalize_attempt(conn, video_id=vid, run_id=run_id,
                                  outcome="success")
        conn.commit()
        summary["normalized"] += 1

    if not dry_run:
        _finish_run(conn, run_id, overall, summary=summary)
    summary["run_id"] = run_id
    summary["status"] = overall
    return summary


def _persist_transcript_version(conn, run_id, result) -> str | None:
    """Insert transcript_version + segments. Returns the new tv_id, or None
    if the UNIQUE constraint hits (already normalized — idempotent no-op)."""
    import uuid
    tv_id = f"hctv_{uuid.uuid7().hex}"
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO transcript_version"
            "(transcript_version_id, video_id, raw_caption_sha256,"
            " normalizer_name, normalizer_version, created_at,"
            " content_sha256, status) VALUES (?,?,?,?,?,?,?,?)",
            (tv_id, result.video_id, result.raw_caption_sha256,
             result.normalizer_name, result.normalizer_version,
             result.created_at, result.content_sha256, "ok"))
        for s in result.segments:
            conn.execute(
                "INSERT INTO transcript_segment"
                "(transcript_version_id, ordinal, start_ms, end_ms, text,"
                " raw_cue_start, raw_cue_end, speaker) VALUES (?,?,?,?,?,?,?,?)",
                (tv_id, s.ordinal, s.start_ms, s.end_ms, s.text,
                 s.raw_cue_start, s.raw_cue_end, s.speaker))
        conn.execute("COMMIT")
        return tv_id
    except sqlite3.IntegrityError:
        # UNIQUE(video_id, raw_caption_sha256, normalizer_*, normalizer_version)
        # already exists; idempotent re-run.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return None
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _write_normalize_failure_artifact(run_id, video_id, *, error):
    """Best-effort write of a small failure JSON; never raises."""
    try:
        houchen_paths.verify_data_root()
        path = houchen_paths.normalize_failure_path(run_id, video_id)
        parent = os.path.dirname(path)
        houchen_paths.assert_no_symlink_components(parent)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"run_id": run_id, "video_id": video_id,
                       "error": str(error)}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        # Failure-to-log is itself non-fatal.
        pass
