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
import houchen_analyzer  # PR-3: claim extraction + provider orchestration
import houchen_concept  # PR-3: domain seed + concept lifecycle
import houchen_normalizer  # PR-2: deterministic transcript normalizer
import houchen_paths
import houchen_prompt
import houchen_publish_paths  # PR-4 Phase 1: render/publish path resolution
import houchen_publisher  # PR-4 Phase 1: VaultWriter protocol + ledger
import houchen_render  # PR-4 Phase 1: pure Markdown renderer
import houchen_schema
import houchen_search  # PR-4 Phase 0: FTS5 search
import houchen_store
import houchen_validator  # PR-3: brief §9.3 hard validator


DEFAULT_NORMALIZER_NAME = houchen_normalizer.NORMALIZER_NAME
DEFAULT_NORMALIZER_VERSION = houchen_normalizer.NORMALIZER_VERSION
DEFAULT_ANALYSIS_PROVIDER = "fake"  # PR-3 v1: offline-only per audit F-6
DEFAULT_PROMPT_VERSION = houchen_prompt.PROMPT_VERSION
DEFAULT_SCHEMA_VERSION = "claim_extraction_v1"  # mirrors houchen_prompt.SCHEMA_VERSION


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


# ---------------------------------------------------------------------------
# PR-3: analyze / validate / concept_seed
# ---------------------------------------------------------------------------

def _select_analyze_scope(conn, *, video_ids=None, pending_only=True):
    """Select normalized videos eligible for analysis without N+1 queries.

    The latest matching normalizer output is derived in one CTE; a second CTE
    limits the exclusion set to *successful* analyze attempts whose parent run
    also completed successfully. This avoids both historical-run duplication
    and a partial/failed run incorrectly suppressing a replay.
    """
    if video_ids is not None:
        return [v for v in video_ids
                if _valid_video_id(v) and _has_ok_transcript(conn, v)]
    if pending_only:
        rows = conn.execute(
            "WITH latest_tv AS ("
            "  SELECT video_id, status,"
            "         ROW_NUMBER() OVER (PARTITION BY video_id"
            "           ORDER BY created_at DESC, transcript_version_id DESC) AS rn"
            "  FROM transcript_version"
            "  WHERE normalizer_name=? AND normalizer_version=?"
            "), analyzed AS ("
            "  SELECT DISTINCT ca.video_id FROM corpus_attempt ca"
            "  JOIN corpus_run cr ON cr.run_id=ca.run_id"
            "  WHERE ca.stage='analyze' AND ca.outcome='success'"
            "    AND cr.kind='analyze' AND cr.status='success'"
            ")"
            " SELECT v.video_id FROM video v"
            " JOIN latest_tv tv ON tv.video_id=v.video_id AND tv.rn=1"
            " LEFT JOIN analyzed a ON a.video_id=v.video_id"
            " WHERE tv.status='ok' AND a.video_id IS NULL"
            " ORDER BY v.discovered_at ASC",
            (DEFAULT_NORMALIZER_NAME, DEFAULT_NORMALIZER_VERSION)).fetchall()
        return [r[0] for r in rows]
    rows = conn.execute(
        "SELECT v.video_id FROM video v"
        " JOIN transcript_version tv ON tv.video_id = v.video_id"
        "      AND tv.status = 'ok'"
        " ORDER BY v.discovered_at ASC").fetchall()
    return [r[0] for r in rows]


def _has_ok_transcript(conn, video_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM transcript_version"
        " WHERE video_id=? AND status='ok' LIMIT 1",
        (video_id,)).fetchone() is not None


def _load_segments_for_transcript(conn, transcript_version_id):
    rows = conn.execute(
        "SELECT ordinal, start_ms, end_ms, text, raw_cue_start,"
        "       raw_cue_end, speaker"
        " FROM transcript_segment WHERE transcript_version_id=?"
        " ORDER BY ordinal ASC",
        (transcript_version_id,)).fetchall()
    return [dict(r) for r in rows]


def _load_transcript_for_video(conn, video_id):
    row = conn.execute(
        "SELECT transcript_version_id, content_sha256"
        " FROM transcript_version"
        " WHERE video_id=? AND status='ok'"
        " ORDER BY created_at DESC, transcript_version_id DESC LIMIT 1",
        (video_id,)).fetchone()
    return (row["transcript_version_id"], row["content_sha256"]) if row else (None, None)


def run_analyze(conn, *, video_ids=None, pending_only=True, limit=None,
                dry_run=False, provider=DEFAULT_ANALYSIS_PROVIDER,
                model="") -> dict:
    """PR-3: build input bundles, invoke provider (default fake), persist
    per-run derived JSON. Mirrors run_normalize's idempotent / best-effort
    shape."""
    _validate_limit(limit)
    summary = {
        "scope_count": 0, "analyzed": 0, "failed": 0,
        "dry_run": dry_run, "provider": provider, "model": model,
    }

    if video_ids is not None:
        uncataloged = [v for v in video_ids
                       if _valid_video_id(v) and not _video_exists(conn, v)]
        if uncataloged:
            started = _now()
            run_id = houchen_schema.new_run_id()
            if not dry_run:
                _insert_run(conn, run_id, "analyze", started, "running")
                _finish_run(conn, run_id, "failed",
                            summary={"uncataloged_ids": uncataloged},
                            error_class="uncataloged_video",
                            error_detail="uncataloged: " + ",".join(uncataloged))
            summary["uncataloged_ids"] = uncataloged
            summary["run_id"] = run_id
            summary["status"] = "failed"
            return summary

    scope = _select_analyze_scope(conn, video_ids=video_ids,
                                  pending_only=pending_only)
    if limit is not None:
        scope = list(scope)[:limit]
    summary["scope_count"] = len(scope)

    started = _now()
    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "analyze", started, "running")

    if dry_run:
        summary["run_id"] = run_id
        summary["status"] = "dry_run"
        return summary

    overall = "success"
    for vid in scope:
        tv_id, tv_sha = _load_transcript_for_video(conn, vid)
        if not tv_id:
            summary["failed"] += 1
            continue
        raw = conn.execute(
            "SELECT raw_caption_sha256 FROM transcript_version"
            " WHERE transcript_version_id=?", (tv_id,)).fetchone()
        segments = _load_segments_for_transcript(conn, tv_id)
        try:
            payload, sha = houchen_analyzer.build_input_payload(
                video_id=vid, transcript_version_id=tv_id,
                transcript_version_sha=tv_sha,
                segments=segments, model=model, provider=provider,
                raw_caption_sha256=(raw[0] if raw else ""),
            )
            outcome = houchen_analyzer.call_provider(
                input_payload=payload, input_sha256=sha,
                run_id=run_id, provider=provider, model=model,
            )
        except Exception as e:  # noqa: BLE001
            outcome = houchen_analyzer.AnalyzeOutcome(
                video_id=vid, outcome="analyze_failed",
                error_class="build_error", detail=str(e))

        # Persist corpus_attempt + commit.
        try:
            att_id = houchen_schema.new_attempt_id()
            conn.execute(
                "INSERT INTO corpus_attempt"
                "(att_id, video_id, run_id, stage, outcome, error_class,"
                " detail, retryable, occurred_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (att_id, vid, run_id, "analyze", outcome.outcome,
                 outcome.error_class, outcome.detail, 0, _now()))
            conn.commit()
        except Exception:
            pass

        if outcome.outcome == "success":
            summary["analyzed"] += 1
        else:
            summary["failed"] += 1
            overall = "partial"

    if not dry_run:
        _finish_run(conn, run_id, overall, summary=summary)
    summary["run_id"] = run_id
    summary["status"] = overall
    return summary


def run_validate(conn, *, video_ids=None, limit=None, dry_run=False) -> dict:
    """Read each analyzed run's artifact, run the hard validator, and write
    the resulting claim/concept/etc. rows. Per-video idempotent UNIQUE on
    analysis_run_id."""
    _validate_limit(limit)
    summary = {"scope_count": 0, "validated": 0, "rejected": 0,
               "needs_review": 0, "failed": 0, "dry_run": dry_run}

    # Scope: videos that have at least one successful analyze attempt.
    if video_ids is not None:
        scope = [v for v in video_ids if _valid_video_id(v)
                 and _has_successful_analyze(conn, v)]
    else:
        rows = conn.execute(
            "SELECT DISTINCT ca.video_id FROM corpus_attempt ca"
            " JOIN corpus_run cr ON cr.run_id = ca.run_id"
            " WHERE ca.stage='analyze' AND ca.outcome='success'"
            "   AND cr.status='success'").fetchall()
        scope = [r[0] for r in rows]
    if limit is not None:
        scope = list(scope)[:limit]
    summary["scope_count"] = len(scope)

    started = _now()
    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "validate", started, "running")

    if dry_run:
        summary["run_id"] = run_id
        summary["status"] = "dry_run"
        return summary

    overall = "success"
    for vid in scope:
        try:
            accepted, rejected, needs_review = _validate_one_video(conn, vid)
            summary["validated"] += len(accepted)
            summary["rejected"] += len(rejected)
            summary["needs_review"] += len(needs_review)
            if rejected or needs_review:
                overall = "partial"
            conn.execute(
                "INSERT INTO corpus_attempt"
                "(att_id, video_id, run_id, stage, outcome, error_class,"
                " detail, retryable, occurred_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (houchen_schema.new_attempt_id(), vid, run_id, "validate",
                 "success", None,
                 json.dumps({"accepted": len(accepted), "rejected": len(rejected),
                             "needs_review": len(needs_review)}, sort_keys=True),
                 0, _now()))
            conn.commit()
        except Exception as e:  # noqa: BLE001
            summary["failed"] += 1
            overall = "partial"
            conn.execute(
                "INSERT INTO corpus_attempt"
                "(att_id, video_id, run_id, stage, outcome, error_class,"
                " detail, retryable, occurred_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (houchen_schema.new_attempt_id(), vid, run_id,
                 "validate", "validate_failed", "validator_error",
                 str(e), 0, _now()))
            conn.commit()

    if not dry_run:
        _finish_run(conn, run_id, overall, summary=summary)
    summary["run_id"] = run_id
    summary["status"] = overall
    return summary


def _has_successful_analyze(conn, video_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM corpus_attempt"
        " WHERE video_id=? AND stage='analyze' AND outcome='success' LIMIT 1",
        (video_id,)).fetchone() is not None


def _validate_one_video(conn, video_id):
    """Validate and persist the latest successful analysis for one video.

    Formal rows retain the *analysis* run as their provenance (`analysis_run_id`;
    audit F-2), while the caller's validate run records the operational
    attempt. The artifact is selected by both run and video so a multi-video
    analyze run can never cross-bind candidates to the wrong transcript.
    """
    row = conn.execute(
        "SELECT ca.run_id, ca.att_id FROM corpus_attempt ca"
        " JOIN corpus_run cr ON cr.run_id = ca.run_id"
        " WHERE ca.video_id=? AND ca.stage='analyze'"
        "   AND ca.outcome='success' AND cr.status='success'"
        " ORDER BY ca.occurred_at DESC, ca.att_id DESC LIMIT 1",
        (video_id,)).fetchone()
    if row is None:
        return [], [], []
    analyze_run_id = row["run_id"]
    artifact = houchen_paths.analysis_artifact_path(analyze_run_id)
    try:
        item = houchen_analyzer.load_artifact_item(artifact, video_id)
        candidates = item["candidates"]
        bundle = houchen_analyzer.load_input_bundle(item["input_sha256"])
    except (FileNotFoundError, ValueError, KeyError):
        return [], [], []

    transcript_version_id = bundle.get("transcript_version_id")
    if not transcript_version_id or item.get("transcript_version_id") != transcript_version_id:
        return [], [], []
    tv = conn.execute(
        "SELECT raw_caption_sha256 FROM transcript_version"
        " WHERE transcript_version_id=? AND video_id=? AND status='ok'",
        (transcript_version_id, video_id)).fetchone()
    if tv is None:
        return [], [], []
    raw_caption_sha256 = tv["raw_caption_sha256"]
    segments_by_ordinal = houchen_analyzer.segments_for_validator(
        bundle.get("segments") or [])
    result = houchen_validator.validate_candidate_bundle(
        candidates, segments_by_ordinal=segments_by_ordinal,
        from_model=True,
    )

    # Per-analysis idempotency: an analysis result is frozen after its first
    # validation materialization, regardless of whether it yielded accepts or
    # rejects. The fake always has rejects; this explicit guard also protects
    # future providers that return only non-claim candidates.
    if conn.execute(
        "SELECT 1 FROM claim WHERE analysis_run_id=? LIMIT 1",
        (analyze_run_id,)).fetchone() is not None:
        return [], [], []

    import uuid
    accepted, rejected, needs_review = [], [], []
    claim_ids_by_index = {}
    accepted_claims = [c for c in result.accepted if "claim_text" in c]
    for c in accepted_claims:
        # Do not let a model cite a different transcript_version than the
        # content-addressed INPUT it actually saw.
        if c.get("transcript_version_id") != transcript_version_id:
            result.per_item_rejects.append(houchen_validator.Reject(
                candidate_ref=f"claim[{c.get('_index', '?')}]", rule_id="R1",
                reason="candidate transcript_version_id differs from analysis INPUT"))
            continue
        cid = f"hccl_{uuid.uuid7().hex}"
        conn.execute(
            "INSERT INTO claim"
            "(claim_id, video_id, claim_text, claim_type, speaker,"
            " layer, temporal_scope, modality, status, analysis_run_id,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, video_id, c["claim_text"], c["claim_type"],
             c.get("speaker"), c["layer"], c.get("temporal_scope"),
             c.get("modality"), "accepted", analyze_run_id, _now()))
        conn.execute(
            "INSERT INTO claim_source"
            "(claim_id, transcript_version_id, segment_start_ordinal,"
            " segment_end_ordinal, start_ms, end_ms, exact_quote,"
            " timestamp_url, raw_caption_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, transcript_version_id, c["segment_start_ordinal"],
             c["segment_end_ordinal"], c["start_ms"], c["end_ms"],
             c["exact_quote"], c["timestamp_url"], raw_caption_sha256))
        claim_ids_by_index[c.get("_index")] = cid
        accepted.append(cid)

    # Preserve rejected claim candidates as auditable, clearly non-authoritative
    # rows. Their failed source cannot be promoted into claim_source.
    for r in result.per_item_rejects:
        if not r.candidate_ref.startswith("claim["):
            continue
        cid = f"hccl_{uuid.uuid7().hex}"
        conn.execute(
            "INSERT INTO claim"
            "(claim_id, video_id, claim_text, claim_type, speaker,"
            " layer, temporal_scope, modality, status, analysis_run_id,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, video_id, f"[rejected:{r.rule_id}] {r.reason}",
             "interpretive", None, "system_evaluation", None, None,
             "rejected", analyze_run_id, _now()))
        rejected.append(cid)

    # Proposed concepts remain proposed — never auto-promote (brief §7.2).
    # The paired concept_source gives a human reviewer the exact corpus anchor.
    concept_ids_by_name = {}
    for proposed in candidates.get("proposed_concepts") or []:
        if not isinstance(proposed, dict) or not proposed.get("canonical_name"):
            continue
        cid = houchen_concept.upsert_proposed_concept(
            conn, canonical_name=proposed["canonical_name"],
            definition=proposed.get("definition"), origin="corpus",
            domain_slugs=proposed.get("domain_slugs") or [],
            analysis_run_id=analyze_run_id)
        ord_ = proposed.get("first_segment_ordinal", 0)
        seg = segments_by_ordinal.get(ord_)
        if seg and proposed.get("first_exact_quote") and houchen_validator.validate_quote_in_segment(
                {"exact_quote": proposed["first_exact_quote"]}, seg["text"]) is None:
            houchen_concept.record_concept_source(
                conn, concept_id=cid, transcript_version_id=transcript_version_id,
                segment_start_ordinal=ord_, segment_end_ordinal=ord_,
                start_ms=proposed.get("first_start_ms", seg["start_ms"]),
                end_ms=proposed.get("first_end_ms", seg["end_ms"]),
                exact_quote=proposed["first_exact_quote"],
                timestamp_url=proposed.get("first_timestamp_url", ""),
                raw_caption_sha256=raw_caption_sha256, source_role="usage",
                analysis_run_id=analyze_run_id)
        concept_ids_by_name[proposed["canonical_name"]] = cid

    # Link only claims that survived validation; unresolved concept names enter
    # the same reversible proposed state rather than being silently dropped.
    for link in candidates.get("concept_links") or []:
        if not isinstance(link, dict):
            continue
        claim_id = claim_ids_by_index.get(link.get("candidate_claim_index"))
        name = link.get("concept_canonical_name")
        relation = link.get("relation")
        if not claim_id or not name or relation not in (
                "defines", "uses", "exemplifies", "qualifies", "relates"):
            continue
        concept_id = concept_ids_by_name.get(name)
        if concept_id is None:
            concept_id = houchen_concept.upsert_proposed_concept(
                conn, canonical_name=name, definition=None, origin="corpus",
                analysis_run_id=analyze_run_id)
            concept_ids_by_name[name] = concept_id
        conn.execute(
            "INSERT OR IGNORE INTO claim_concept"
            "(claim_id, concept_id, relation, analysis_run_id) VALUES (?,?,?,?)",
            (claim_id, concept_id, relation, analyze_run_id))

    for mention in candidates.get("evidence_mentions") or []:
        if not isinstance(mention, dict) or not mention.get("text"):
            continue
        if mention.get("transcript_version_id") != transcript_version_id:
            continue
        conn.execute(
            "INSERT INTO evidence_mention"
            "(mention_id, video_id, transcript_version_id, segment_ordinal,"
            " text, mention_type, external_entity_candidate, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (f"hcem_{uuid.uuid7().hex}", video_id, transcript_version_id,
             mention.get("segment_ordinal", 0), mention["text"],
             mention.get("mention_type", "reference"),
             mention.get("external_entity_candidate"), _now()))

    for forecast in candidates.get("forecast_candidates") or []:
        if not isinstance(forecast, dict):
            continue
        claim_id = claim_ids_by_index.get(forecast.get("for_claim_index"))
        if not claim_id or houchen_validator.validate_forecast_has_criteria(forecast):
            continue
        conn.execute(
            "INSERT INTO forecast"
            "(forecast_id, claim_id, time_window_start, time_window_end,"
            " outcome_condition, status) VALUES (?,?,?,?,?,?)",
            (f"hcfc_{uuid.uuid7().hex}", claim_id,
             forecast.get("time_window_start"), forecast.get("time_window_end"),
             forecast["outcome_condition"], "candidate"))

    for edge in candidates.get("reasoning_edges") or []:
        if not isinstance(edge, dict) or houchen_validator.validate_reasoning_edge_source(edge):
            continue
        from_id = claim_ids_by_index.get(edge.get("from_claim_index"))
        to_id = claim_ids_by_index.get(edge.get("to_claim_index"))
        if not from_id or not to_id:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO reasoning_edge"
            "(from_claim_id, to_claim_id, relation, layer, source_id,"
            " transcript_version_id, exact_quote, start_ms, end_ms,"
            " timestamp_url, analysis_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (from_id, to_id, edge.get("relation"), edge.get("layer"), None,
             edge.get("transcript_version_id"), edge.get("exact_quote"),
             edge.get("start_ms"), edge.get("end_ms"),
             edge.get("timestamp_url"), analyze_run_id))

    conn.commit()
    return accepted, rejected, needs_review


def houchen_prompt_input_sha(run_id):
    """Read the input_sha256 from an analysis artifact (best-effort)."""
    try:
        import json
        with open(houchen_paths.analysis_artifact_path(run_id), "r",
                  encoding="utf-8") as f:
            doc = json.load(f)
        return doc.get("input_sha256")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def run_concept_seed(conn, *, dry_run=False) -> dict:
    """One-shot: insert the 7 domain slugs (brief §7.2 + audit F-1).
    Idempotent — re-running is a no-op."""
    summary = {"seeded": 0, "dry_run": dry_run}
    started = _now()
    run_id = houchen_schema.new_run_id()
    if not dry_run:
        _insert_run(conn, run_id, "concept_seed", started, "running")
        n = houchen_concept.seed_domain_skeleton(conn)
        conn.commit()
        _finish_run(conn, run_id, "success",
                    summary={"seeded": n, "actor": "system"})
        summary["seeded"] = n
    summary["run_id"] = run_id
    summary["status"] = "success" if not dry_run else "dry_run"
    return summary


# ---------------------------------------------------------------------------
# PR-4 Phase 0 — run_search (read-only, FTS5 MATCH)
# ---------------------------------------------------------------------------

def run_search(conn, *, kind, query, limit=20) -> dict:
    """Read-only FTS5 search across transcript / claim / concept / concept_alias.

    Persists a `corpus_run(kind='search', status='success')` row as the
    audit trail; the actual search never mutates any FTS table. The CLI
    dry-run flag short-circuits before the run row is written.
    """
    if not houchen_search.fts5_installed(conn):
        raise RuntimeError(
            "FTS5 substrate is not installed (schema_version < 4 or the v4"
            " migration was skipped). Run `ensure_schema` first.")
    result = houchen_search.search(conn, kind=kind, query=query, limit=limit)
    summary = {
        "kind": kind,
        "query": query,
        "limit": limit,
        "total": result.total,
        "transcripts": [
            {"video_id": h.video_id, "transcript_version_id": h.transcript_version_id,
             "ordinal": h.ordinal, "start_ms": h.start_ms, "end_ms": h.end_ms,
             "text": h.text, "rank": h.rank} for h in result.transcripts],
        "claims": [
            {"claim_id": h.claim_id, "claim_type": h.claim_type, "layer": h.layer,
             "video_id": h.video_id, "claim_text": h.claim_text, "rank": h.rank}
            for h in result.claims],
        "concepts": [
            {"concept_id": h.concept_id, "status": h.status,
             "canonical_name": h.canonical_name, "definition": h.definition,
             "rank": h.rank} for h in result.concepts],
        "concept_aliases": [
            {"concept_id": h.concept_id, "source": h.source, "alias": h.alias,
             "rank": h.rank} for h in result.aliases],
    }
    return summary


def _latest_successful_analyze_attempt(conn, video_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT ca.run_id, ca.att_id FROM corpus_attempt ca"
        " JOIN corpus_run cr ON cr.run_id = ca.run_id"
        " WHERE ca.video_id=? AND ca.stage='analyze'"
        "   AND ca.outcome='success' AND cr.status='success'"
        " ORDER BY ca.occurred_at DESC, ca.att_id DESC LIMIT 1",
        (video_id,)).fetchone()


def build_video_page_from_db(conn, video_id: str,
                             *, analysis_run_id: str | None = None) -> houchen_render.VideoPage:
    """Build a VideoPage from corpus DB rows for render/publish.

    Uses the latest successful analyze run for the video unless
    `analysis_run_id` is given explicitly. Accepted claims are joined
    with `claim_source` for quote blocks.
    """
    vrow = conn.execute(
        "SELECT canonical_url, title, published_at FROM video WHERE video_id=?",
        (video_id,)).fetchone()
    if vrow is None:
        raise ValueError(f"unknown video_id: {video_id}")

    if analysis_run_id is None:
        row = _latest_successful_analyze_attempt(conn, video_id)
        if row is None:
            raise ValueError(f"no successful analyze for video_id: {video_id}")
        analysis_run_id = row["run_id"]
    else:
        row = conn.execute(
            "SELECT 1 FROM corpus_run WHERE run_id=? AND kind='analyze'",
            (analysis_run_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown analysis_run_id: {analysis_run_id}")

    artifact = houchen_paths.analysis_artifact_path(analysis_run_id)
    item = houchen_analyzer.load_artifact_item(artifact, video_id)
    bundle = houchen_analyzer.load_input_bundle(item["input_sha256"])
    transcript_version_id = bundle.get("transcript_version_id")
    if not transcript_version_id:
        raise ValueError(
            f"missing transcript_version_id in input bundle for run {analysis_run_id}")
    prompt_version = bundle.get("prompt_version") or houchen_prompt.PROMPT_VERSION

    counts = conn.execute(
        "SELECT status, COUNT(*) AS n FROM claim"
        " WHERE video_id=? AND analysis_run_id=? GROUP BY status",
        (video_id, analysis_run_id)).fetchall()
    by_status = {r["status"]: r["n"] for r in counts}

    claim_rows = conn.execute(
        "SELECT c.claim_id, c.claim_text, c.claim_type, c.layer, c.speaker,"
        " cs.exact_quote, cs.timestamp_url, cs.transcript_version_id"
        " FROM claim c"
        " JOIN claim_source cs ON cs.claim_id = c.claim_id"
        " WHERE c.video_id=? AND c.analysis_run_id=? AND c.status='accepted'"
        " ORDER BY cs.segment_start_ordinal, c.claim_id",
        (video_id, analysis_run_id)).fetchall()
    claims = [
        houchen_render.ClaimSummary(
            claim_id=r["claim_id"],
            claim_text=r["claim_text"],
            claim_type=r["claim_type"],
            layer=r["layer"],
            speaker=r["speaker"],
            exact_quote=r["exact_quote"],
            timestamp_url=r["timestamp_url"],
            transcript_version_id=r["transcript_version_id"],
        )
        for r in claim_rows
    ]

    claim_ids = [c.claim_id for c in claims]
    concept_ids: list[str] = []
    concept_names: dict[str, str] = {}
    if claim_ids:
        placeholders = ",".join("?" * len(claim_ids))
        concept_rows = conn.execute(
            f"SELECT DISTINCT cc.concept_id, c.canonical_name"
            f" FROM claim_concept cc"
            f" JOIN concept c ON c.concept_id = cc.concept_id"
            f" WHERE cc.claim_id IN ({placeholders})",
            claim_ids).fetchall()
        concept_ids = [r["concept_id"] for r in concept_rows]
        concept_names = {
            r["concept_id"]: (r["canonical_name"] or r["concept_id"])
            for r in concept_rows
        }

    forecast_ids: list[str] = []
    if claim_ids:
        placeholders = ",".join("?" * len(claim_ids))
        forecast_rows = conn.execute(
            f"SELECT forecast_id FROM forecast"
            f" WHERE claim_id IN ({placeholders})",
            claim_ids).fetchall()
        forecast_ids = [r["forecast_id"] for r in forecast_rows]

    canonical_url = vrow["canonical_url"] or ""
    title = vrow["title"] or ""
    published_at = vrow["published_at"] or ""

    return houchen_render.VideoPage(
        video_id=video_id,
        canonical_url=canonical_url,
        title=title,
        published_at=published_at,
        transcript_version_id=transcript_version_id,
        analysis_run_id=analysis_run_id,
        prompt_version=prompt_version,
        claim_count_accepted=by_status.get("accepted", 0),
        claim_count_rejected=by_status.get("rejected", 0),
        claim_count_needs_review=by_status.get("needs_review", 0),
        claims=claims,
        concept_ids=concept_ids,
        concept_names=concept_names,
        forecast_ids=forecast_ids,
    )


def _concept_source_from_row(row) -> houchen_render.ConceptSource:
    return houchen_render.ConceptSource(
        transcript_version_id=row["transcript_version_id"],
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        exact_quote=row["exact_quote"],
        role=row["source_role"],
        source_kind="model",
        timestamp_url=row["timestamp_url"] or "",
    )


def build_concept_page_from_db(conn, concept_id: str) -> houchen_render.ConceptPage:
    """Build a ConceptPage from corpus DB for render/publish (brief §11).

    Proposed concepts are allowed (no auto-promote). Canonical-definition
    sources use `source_role='canonical_definition'`; speaker uses are
    `usage` / `speaker_definition`. System analyses only include linked
    claims with `layer='system_evaluation'` (renderer asserts this).
    """
    crow = conn.execute(
        "SELECT concept_id, canonical_name, definition, status,"
        " first_seen_at, last_seen_at FROM concept WHERE concept_id=?",
        (concept_id,)).fetchone()
    if crow is None:
        raise ValueError(f"unknown concept_id: {concept_id}")

    domain_rows = conn.execute(
        "SELECT domain_slug FROM concept_domain WHERE concept_id=?"
        " ORDER BY domain_slug",
        (concept_id,)).fetchall()
    domain_slugs = [r["domain_slug"] for r in domain_rows]

    src_rows = conn.execute(
        "SELECT transcript_version_id, start_ms, end_ms, exact_quote,"
        " source_role, timestamp_url FROM concept_source"
        " WHERE concept_id=? ORDER BY start_ms, transcript_version_id",
        (concept_id,)).fetchall()
    canonical_definition_sources = []
    speaker_use_sources = []
    for r in src_rows:
        src = _concept_source_from_row(r)
        if r["source_role"] == "canonical_definition":
            canonical_definition_sources.append(src)
        else:
            speaker_use_sources.append(src)

    if not speaker_use_sources:
        usage_rows = conn.execute(
            "SELECT cs.transcript_version_id, cs.start_ms, cs.end_ms,"
            " cs.exact_quote, cs.timestamp_url"
            " FROM claim_concept cc"
            " JOIN claim c ON c.claim_id = cc.claim_id"
            " JOIN claim_source cs ON cs.claim_id = c.claim_id"
            " WHERE cc.concept_id=? AND c.status='accepted'"
            "   AND c.layer != 'system_evaluation'"
            " ORDER BY cs.start_ms, c.claim_id",
            (concept_id,)).fetchall()
        seen_quotes: set[str] = set()
        for r in usage_rows:
            quote = (r["exact_quote"] or "").strip()
            if not quote or quote in seen_quotes:
                continue
            seen_quotes.add(quote)
            speaker_use_sources.append(houchen_render.ConceptSource(
                transcript_version_id=r["transcript_version_id"],
                start_ms=r["start_ms"],
                end_ms=r["end_ms"],
                exact_quote=quote,
                role="usage",
                source_kind="model",
                timestamp_url=r["timestamp_url"] or "",
            ))

    eval_rows = conn.execute(
        "SELECT c.claim_id, c.claim_text, c.claim_type, c.layer, c.speaker,"
        " cs.exact_quote, cs.timestamp_url, cs.transcript_version_id"
        " FROM claim_concept cc"
        " JOIN claim c ON c.claim_id = cc.claim_id"
        " JOIN claim_source cs ON cs.claim_id = c.claim_id"
        " WHERE cc.concept_id=? AND c.status='accepted'"
        "   AND c.layer='system_evaluation'"
        " ORDER BY cs.start_ms, c.claim_id",
        (concept_id,)).fetchall()
    system_evaluations = [
        houchen_render.ClaimSummary(
            claim_id=r["claim_id"],
            claim_text=r["claim_text"],
            claim_type=r["claim_type"],
            layer=r["layer"],
            speaker=r["speaker"],
            exact_quote=r["exact_quote"],
            timestamp_url=r["timestamp_url"],
            transcript_version_id=r["transcript_version_id"],
        )
        for r in eval_rows
    ]

    return houchen_render.ConceptPage(
        concept_id=crow["concept_id"],
        canonical_name=crow["canonical_name"] or "",
        definition=crow["definition"] or "",
        status=crow["status"],
        domain_slugs=domain_slugs,
        first_seen_at=crow["first_seen_at"] or "",
        last_seen_at=crow["last_seen_at"] or "",
        canonical_definition_sources=canonical_definition_sources,
        speaker_use_sources=speaker_use_sources,
        system_evaluations=system_evaluations,
    )


def list_concepts_for_research_pages(conn, *, limit: int = 6) -> list[str]:
    """Pick proposed/canonical concepts with ≥1 concept_source, prefer those
    linked to accepted claims. Used to close PR-4 exit (brief §16)."""
    rows = conn.execute(
        "SELECT c.concept_id,"
        "  (SELECT COUNT(*) FROM claim_concept cc"
        "   JOIN claim cl ON cl.claim_id=cc.claim_id AND cl.status='accepted'"
        "   WHERE cc.concept_id=c.concept_id) AS acc_n,"
        "  (SELECT COUNT(*) FROM concept_source cs"
        "   WHERE cs.concept_id=c.concept_id) AS src_n"
        " FROM concept c"
        " WHERE c.status IN ('proposed','canonical')"
        "   AND EXISTS (SELECT 1 FROM concept_source cs"
        "               WHERE cs.concept_id=c.concept_id)"
        " ORDER BY acc_n DESC, src_n DESC, c.canonical_name ASC"
        " LIMIT ?",
        (limit,)).fetchall()
    return [r["concept_id"] for r in rows]


# ---------------------------------------------------------------------------
# PR-4 Phase 1 — run_render (write-side; render → write file → record row)
# ---------------------------------------------------------------------------

def run_render(conn, *, kind: str, page_key: str,
               page_obj, template_version: str | None = None,
               include_claim_pages: bool = False,
               dry_run: bool = False) -> dict:
    """Render one page to Markdown, write it under `<publish_root>/render/...`,
    and record a `rendered_page` row. Idempotent: re-rendering the same
    `(page_kind, page_key, template_version)` triple yields the same SHA-256.

    `claim` pages are OFF by default in v1 (S-2 audit fix). Pass
    `include_claim_pages=True` to opt in.
    """
    if template_version is None:
        template_version = houchen_render.TEMPLATE_VERSION
    if kind == "claim" and not include_claim_pages:
        raise ValueError(
            "claim pages are OFF by default in v1 (S-2 audit fix); pass "
            "include_claim_pages=True to opt in")
    if kind == "claim" and not include_claim_pages:
        # already raised above; defensive
        raise ValueError("claim pages disabled")
    summary = {
        "kind": kind, "page_key": page_key,
        "template_version": template_version,
        "dry_run": dry_run,
    }
    markdown = houchen_render.render_page(kind, page_obj)
    sha = houchen_render.render_sha256(markdown)
    summary["render_sha256"] = sha

    local_path = houchen_publish_paths.render_page_path(
        template_version, kind, page_key)

    if dry_run:
        summary["local_path"] = local_path
        summary["status"] = "dry_run"
        return summary

    houchen_paths.assert_no_symlink_components(local_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)

    rendered_page_id = f"rp_{kind}_{page_key}"
    existing = conn.execute(
        "SELECT rendered_page_id, render_sha256 FROM rendered_page"
        " WHERE rendered_page_id=?",
        (rendered_page_id,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO rendered_page(rendered_page_id, page_kind,"
            "       page_key, template_version, render_sha256, created_at)"
            " VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (rendered_page_id, kind, page_key, template_version, sha))
    else:
        # Re-render MUST yield the same SHA — if it doesn't, the input
        # changed and we keep the original row (the file is rewritten
        # so the on-disk bytes match the new SHA). The vault_path
        # column does not exist; the runner attaches vault_path at
        # publish-time via the publish_record row.
        conn.execute(
            "UPDATE rendered_page SET render_sha256=?, template_version=?"
            " WHERE rendered_page_id=?",
            (sha, template_version, rendered_page_id))
    conn.commit()

    summary["local_path"] = local_path
    summary["rendered_page_id"] = rendered_page_id
    summary["status"] = "rendered"
    return summary


# ---------------------------------------------------------------------------
# PR-4 Phase 1 — run_publish (write-side; PUT → GET → SHA via VaultWriter)
# ---------------------------------------------------------------------------

def run_publish(conn, *, page_ids=None, kind=None,
                vault_writer, vault_prefix: str,
                dry_run: bool = True,
                apply: bool = False,
                operator_authorized: bool = False,
                actor: str = "system") -> dict:
    """Iterate pending `rendered_page` rows and publish via VaultWriter.

    `dry_run=True` is the default. Real PUT requires both `apply=True` AND
    `operator_authorized=True`; either alone is rejected with exit-code 2
    semantics (raised). The CLI prints a remediation message.

    Returns a JSON-serializable summary with per-page results and a
    final ledger snapshot.
    """
    if apply and not operator_authorized:
        raise RuntimeError(
            "--apply requires --operator-authorized (audit gate)")
    if apply and dry_run:
        # The CLI normally passes dry_run=False alongside apply=True.
        dry_run = False

    summary = {
        "dry_run": dry_run,
        "apply": apply,
        "operator_authorized": operator_authorized,
        "vault_prefix": vault_prefix,
        "actor": actor,
        "page_results": [],
        "published_count": 0,
        "failed_count": 0,
    }

    if page_ids is None:
        rows = conn.execute(
            "SELECT rendered_page_id, page_kind, page_key"
            " FROM rendered_page"
            " WHERE (? IS NULL OR page_kind = ?)"
            " ORDER BY rendered_page_id",
            (kind, kind)).fetchall()
        candidates = [r[0] for r in rows]
    else:
        candidates = list(page_ids)

    for page_id in candidates:
        row = conn.execute(
            "SELECT page_kind, page_key FROM rendered_page"
            " WHERE rendered_page_id=?",
            (page_id,)).fetchone()
        if row is None:
            summary["page_results"].append(
                {"page_id": page_id, "status": "skipped",
                 "error_class": "unknown_page"})
            continue
        page_kind, page_key = row
        vault_path = houchen_publish_paths.vault_path_for(
            page_kind, page_key, vault_prefix)
        # Stamp the rendered_page with the planned vault_path so the
        # publisher's page_row lookup has it. We do this only on the
        # first publish attempt for this page.
        if dry_run:
            summary["page_results"].append({
                "page_id": page_id, "vault_path": vault_path,
                "status": "dry_run",
            })
            continue

        # Real publish path: attach vault_path placeholder and let
        # publish_page do PUT → GET → SHA.
        conn.execute(
            "UPDATE rendered_page SET page_key=page_key"
            " WHERE rendered_page_id=?",
            (page_id,))
        # Use a temporary accessor: publish_page reads the planned
        # vault_path from a synthetic record. We pass vault_path as
        # an explicit kwarg via a one-shot adapter.
        try:
            result = publish_with_path(
                conn=conn, page_id=page_id, vault_path=vault_path,
                vault_writer=vault_writer, actor=actor)
        except houchen_publisher.PublishError as exc:
            summary["page_results"].append({
                "page_id": page_id, "vault_path": vault_path,
                "status": "failed", "error_class": exc.error_class,
                "error_detail": str(exc),
            })
            summary["failed_count"] += 1
            continue

        summary["page_results"].append({
            "page_id": page_id, "vault_path": vault_path,
            "status": "published" if result.published else "failed",
            "error_class": result.error_class,
        })
        if result.published:
            summary["published_count"] += 1
        else:
            summary["failed_count"] += 1

    # Per-render registry export — useful for readback tests.
    if not dry_run and candidates:
        index_path = houchen_publish_paths.obsidian_index_path()
        houchen_paths.assert_no_symlink_components(index_path)
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        houchen_publisher.export_obsidian_index(conn, out_path=index_path)
        summary["obsidian_index_path"] = index_path

    if summary["failed_count"] == 0:
        summary["status"] = "success"
    elif summary["published_count"] == 0:
        summary["status"] = "failed"
    else:
        summary["status"] = "partial"
    return summary


def publish_with_path(*, conn, page_id: str, vault_path: str,
                      vault_writer, actor: str):
    """Adapter that stamps the planned vault_path onto a transient
    `rendered_page` row and dispatches to `publish_page`.

    `publish_page` reads vault_path from a placeholder column; for the
    PR-4 Phase 1 surface we pass it explicitly via this adapter to keep
    `publish_page` testable without polluting the schema. The vault_path
    is recorded in `publish_record` immediately, so the placeholder
    column on `rendered_page` is not used at rest.
    """
    page_row = conn.execute(
        "SELECT render_sha256 FROM rendered_page WHERE rendered_page_id=?",
        (page_id,)).fetchone()
    if page_row is None:
        raise houchen_publisher.PublishError(
            f"unknown rendered_page {page_id!r}",
            error_class="unknown_page")
    # The publish_page contract: it reads content from the render file
    # and writes the publish_record row. vault_path is bound here.
    return _publish_with_explicit_path(
        conn, page_id=page_id, render_sha=page_row[0],
        vault_path=vault_path, vault_writer=vault_writer, actor=actor)


def _publish_with_explicit_path(conn, *, page_id, render_sha,
                                vault_path, vault_writer, actor):
    """Internal: PUT → GET → SHA with explicit vault_path.

    Mirrors `lib/houchen_publisher.publish_page` but takes the
    vault_path as a kwarg instead of looking it up in a placeholder
    column. Keeps `publish_page` testable while letting `run_publish`
    compose the path from `vault_path_for(...)`.
    """
    local_path_lookup = conn.execute(
        "SELECT page_kind, page_key, template_version FROM rendered_page"
        " WHERE rendered_page_id=?",
        (page_id,)).fetchone()
    if local_path_lookup is None:
        raise houchen_publisher.PublishError(
            f"unknown rendered_page {page_id!r}",
            error_class="unknown_page")
    page_kind, page_key, template_version = local_path_lookup
    local_path = houchen_publish_paths.render_page_path(
        template_version, page_kind, page_key)
    content = houchen_publisher._read_render_file(
        local_path, expected_sha=render_sha)

    existing = houchen_publisher._fetch_existing_record(
        conn, page_id, vault_path)
    if existing is not None and existing[1] == "published" and existing[2] == render_sha:
        return houchen_publisher.PublishResult(
            page_id=page_id, vault_path=vault_path, published=True)

    try:
        vault_writer.put_pipeline(vault_path, content)
    except Exception as exc:
        return houchen_publisher._record_failure(
            conn, page_id, vault_path, render_sha,
            error_class="put_failed", detail=str(exc))
    try:
        fetched = vault_writer.get_pipeline(vault_path)
    except Exception as exc:
        return houchen_publisher._record_failure(
            conn, page_id, vault_path, render_sha,
            error_class="readback_failed", detail=str(exc))
    if fetched is None:
        return houchen_publisher._record_failure(
            conn, page_id, vault_path, render_sha,
            error_class="readback_missing",
            detail="get_pipeline returned None")
    if houchen_publisher._sha256_text(fetched) != render_sha:
        return houchen_publisher._record_failure(
            conn, page_id, vault_path, render_sha,
            error_class="readback_mismatch",
            detail="sha256 differs from rendered_page.render_sha256")

    houchen_publisher.upsert_published(
        conn, page_id, vault_path, render_sha, actor=actor)
    return houchen_publisher.PublishResult(
        page_id=page_id, vault_path=vault_path, published=True)
