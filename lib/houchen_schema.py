"""Schema + state machine for the Hou Chen research corpus (PR-1, hardened).

Two responsibilities beyond the original draft:

    - DDL + freeze triggers (unchanged from v1 lock-in).
    - `validate_schema(conn)` — verify that every v1 table/column/index/trigger
      is EXACTLY present, so `houchen_migrations` can refuse to record version 1
      against a wrong pre-existing schema (P1-3).

    - Per-video state semantics (P1-5): a single source of truth for "what is
      the latest terminal outcome of this video". This is used by runner scope
      selection, status, coverage and oldest-pending, so they can never disagree.

State model (derived, not stored as a mutable column):
    - `raw_caption` present            → terminal state `frozen`.
    - else, latest `corpus_attempt` (stage='freeze') outcome maps to a state:
        'missing' | 'auth_required' | 'unavailable' | 'retryable' |
        'tool_error' | 'permanent_error' | 'raw_integrity_error' → terminal.
    - no attempt yet → `pending`.

PENDING by default = only `pending` or `retryable`. Everything else is
terminal and must NOT be re-selected unless the operator explicitly overrides.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Identifiers / constants
# ---------------------------------------------------------------------------

VIDEO_ID_RE = r"[A-Za-z0-9_-]{11}"

_PREFIX_RUN = "hcrun"
_PREFIX_ATT = "hcatt"


def new_run_id() -> str:
    import uuid
    return f"{_PREFIX_RUN}_{uuid.uuid7().hex}"


def new_attempt_id() -> str:
    import uuid
    return f"{_PREFIX_ATT}_{uuid.uuid7().hex}"


# Subtitle selection rules (single source of truth).
LANGUAGE_PRIORITY = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW")
FORMAT_PRIORITY = ("json3", "vtt", "srv3", "srv2", "srv1", "ttml")
CAPTION_KIND_PRIORITY = ("manual", "auto")

# Outcomes that are "terminal" (do NOT re-select by default). 'retryable' and
# 'tool_error' ARE re-selectable (transient); 'pending' means no attempt yet.
TERMINAL_OUTCOMES = frozenset({
    "missing", "auth_required", "unavailable", "permanent_error",
    "raw_integrity_error",
})
RESELECTABLE_OUTCOMES = frozenset({"retryable", "tool_error"})


# ---------------------------------------------------------------------------
# DDL — v1
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS noguard_upd_schema_version
BEFORE UPDATE ON schema_version
BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: UPDATE forbidden'); END;
CREATE TRIGGER IF NOT EXISTS noguard_del_schema_version
BEFORE DELETE ON schema_version
BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: DELETE forbidden'); END;

CREATE TABLE IF NOT EXISTS corpus_run (
  run_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('catalog','caption_fetch','preflight')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed')),
  config_sha256 TEXT NOT NULL,
  tool_versions_json TEXT NOT NULL,
  summary_json TEXT,
  error_class TEXT,
  error_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_corpus_run_started ON corpus_run(started_at);

CREATE TABLE IF NOT EXISTS video (
  video_id TEXT PRIMARY KEY,
  channel_id TEXT,
  channel_handle TEXT,
  canonical_url TEXT,
  title TEXT,
  description TEXT,
  published_at TEXT,
  duration_sec INTEGER,
  live_status TEXT,
  availability TEXT NOT NULL DEFAULT 'public'
      CHECK(availability IN ('public','unlisted','private','deleted',
                             'region_blocked','unavailable')),
  content_kind TEXT NOT NULL DEFAULT 'video'
      CHECK(content_kind IN ('video','short','stream','live_replay')),
  discovered_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  metadata_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_availability ON video(availability);
CREATE INDEX IF NOT EXISTS idx_video_content_kind ON video(content_kind);
CREATE INDEX IF NOT EXISTS idx_video_last_seen ON video(last_seen_at);

CREATE TABLE IF NOT EXISTS video_collection (
  collection_id TEXT PRIMARY KEY,
  collection_name TEXT NOT NULL CHECK(collection_name IN ('videos','streams','shorts')),
  enumerated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_collection_membership (
  video_id TEXT NOT NULL REFERENCES video(video_id),
  collection_id TEXT NOT NULL REFERENCES video_collection(collection_id),
  PRIMARY KEY (video_id, collection_id)
);

CREATE TABLE IF NOT EXISTS raw_caption (
  video_id TEXT PRIMARY KEY REFERENCES video(video_id),
  language TEXT NOT NULL,
  caption_kind TEXT NOT NULL CHECK(caption_kind IN ('manual','auto')),
  format TEXT NOT NULL CHECK(format IN ('json3','vtt','srv1','srv2','srv3','ttml')),
  content_sha256 TEXT NOT NULL,
  local_path TEXT NOT NULL,
  byte_count INTEGER NOT NULL,
  cue_count INTEGER NOT NULL,
  fetched_at TEXT NOT NULL,
  yt_dlp_version TEXT NOT NULL,
  source_metadata_sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS noguard_upd_raw_caption
BEFORE UPDATE ON raw_caption
BEGIN SELECT RAISE(ABORT, 'raw_caption is frozen: UPDATE forbidden'); END;
CREATE TRIGGER IF NOT EXISTS noguard_del_raw_caption
BEFORE DELETE ON raw_caption
BEGIN SELECT RAISE(ABORT, 'raw_caption is frozen: DELETE forbidden'); END;

CREATE TABLE IF NOT EXISTS corpus_attempt (
  att_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES video(video_id),
  run_id TEXT NOT NULL REFERENCES corpus_run(run_id),
  stage TEXT NOT NULL CHECK(stage IN ('catalog','subtitle_inventory',
                                       'subtitle_download','subtitle_parse','freeze')),
  outcome TEXT NOT NULL CHECK(outcome IN ('success','skipped','missing',
                                          'auth_required','unavailable',
                                          'retryable','tool_error',
                                          'permanent_error','raw_integrity_error')),
  error_class TEXT,
  detail TEXT,
  retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0,1)),
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempt_video ON corpus_attempt(video_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_attempt_outcome ON corpus_attempt(outcome);
CREATE INDEX IF NOT EXISTS idx_attempt_run ON corpus_attempt(run_id, occurred_at);
"""

# Canonical v1 table -> expected columns (ordered). Used for exact-schema validation.
_V1_TABLES = {
    "schema_version": ["version", "applied_at", "description"],
    "corpus_run": [
        "run_id", "kind", "started_at", "finished_at", "status",
        "config_sha256", "tool_versions_json", "summary_json",
        "error_class", "error_detail",
    ],
    "video": [
        "video_id", "channel_id", "channel_handle", "canonical_url",
        "title", "description", "published_at", "duration_sec",
        "live_status", "availability", "content_kind", "discovered_at",
        "last_seen_at", "metadata_sha256",
    ],
    "video_collection": ["collection_id", "collection_name", "enumerated_at"],
    "video_collection_membership": ["video_id", "collection_id"],
    "raw_caption": [
        "video_id", "language", "caption_kind", "format", "content_sha256",
        "local_path", "byte_count", "cue_count", "fetched_at",
        "yt_dlp_version", "source_metadata_sha256",
    ],
    "corpus_attempt": [
        "att_id", "video_id", "run_id", "stage", "outcome", "error_class",
        "detail", "retryable", "occurred_at",
    ],
}

# v1 indexes (name, table, column-list). Verified by sqlite_master + pragma.
_V1_INDEXES = {
    ("idx_corpus_run_started", "corpus_run"),
    ("idx_video_availability", "video"),
    ("idx_video_content_kind", "video"),
    ("idx_video_last_seen", "video"),
    ("idx_attempt_video", "corpus_attempt"),
    ("idx_attempt_outcome", "corpus_attempt"),
    ("idx_attempt_run", "corpus_attempt"),
}

# v1 triggers (name). Their bodies are checked too via a known prefix.
_V1_TRIGGERS = {
    "noguard_upd_schema_version",
    "noguard_del_schema_version",
    "noguard_upd_raw_caption",
    "noguard_del_raw_caption",
}


def install_v1(conn) -> None:
    conn.executescript(_SCHEMA_V1)


# Explicit list of complete SQL statements (trigger bodies contain internal
# `;`, so a naive split(";") would corrupt them). Used by the migration to run
# DDL atomically via conn.execute() inside one transaction.
_V1_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS schema_version (
         version INTEGER PRIMARY KEY,
         applied_at TEXT NOT NULL,
         description TEXT NOT NULL
       )""",
    """CREATE TRIGGER IF NOT EXISTS noguard_upd_schema_version
       BEFORE UPDATE ON schema_version
       BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: UPDATE forbidden'); END""",
    """CREATE TRIGGER IF NOT EXISTS noguard_del_schema_version
       BEFORE DELETE ON schema_version
       BEGIN SELECT RAISE(ABORT, 'schema_version is append-only: DELETE forbidden'); END""",
    """CREATE TABLE IF NOT EXISTS corpus_run (
         run_id TEXT PRIMARY KEY,
         kind TEXT NOT NULL CHECK(kind IN ('catalog','caption_fetch','preflight','normalize')),
         started_at TEXT NOT NULL,
         finished_at TEXT,
         status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed')),
         config_sha256 TEXT NOT NULL,
         tool_versions_json TEXT NOT NULL,
         summary_json TEXT,
         error_class TEXT,
         error_detail TEXT
       )""",
    """CREATE INDEX IF NOT EXISTS idx_corpus_run_started ON corpus_run(started_at)""",
    """CREATE TABLE IF NOT EXISTS video (
         video_id TEXT PRIMARY KEY,
         channel_id TEXT,
         channel_handle TEXT,
         canonical_url TEXT,
         title TEXT,
         description TEXT,
         published_at TEXT,
         duration_sec INTEGER,
         live_status TEXT,
         availability TEXT NOT NULL DEFAULT 'public'
             CHECK(availability IN ('public','unlisted','private','deleted',
                                    'region_blocked','unavailable')),
         content_kind TEXT NOT NULL DEFAULT 'video'
             CHECK(content_kind IN ('video','short','stream','live_replay')),
         discovered_at TEXT NOT NULL,
         last_seen_at TEXT NOT NULL,
         metadata_sha256 TEXT NOT NULL
       )""",
    """CREATE INDEX IF NOT EXISTS idx_video_availability ON video(availability)""",
    """CREATE INDEX IF NOT EXISTS idx_video_content_kind ON video(content_kind)""",
    """CREATE INDEX IF NOT EXISTS idx_video_last_seen ON video(last_seen_at)""",
    """CREATE TABLE IF NOT EXISTS video_collection (
         collection_id TEXT PRIMARY KEY,
         collection_name TEXT NOT NULL CHECK(collection_name IN ('videos','streams','shorts')),
         enumerated_at TEXT NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS video_collection_membership (
         video_id TEXT NOT NULL REFERENCES video(video_id),
         collection_id TEXT NOT NULL REFERENCES video_collection(collection_id),
         PRIMARY KEY (video_id, collection_id)
       )""",
    """CREATE TABLE IF NOT EXISTS raw_caption (
         video_id TEXT PRIMARY KEY REFERENCES video(video_id),
         language TEXT NOT NULL,
         caption_kind TEXT NOT NULL CHECK(caption_kind IN ('manual','auto')),
         format TEXT NOT NULL CHECK(format IN ('json3','vtt','srv1','srv2','srv3','ttml')),
         content_sha256 TEXT NOT NULL,
         local_path TEXT NOT NULL,
         byte_count INTEGER NOT NULL,
         cue_count INTEGER NOT NULL,
         fetched_at TEXT NOT NULL,
         yt_dlp_version TEXT NOT NULL,
         source_metadata_sha256 TEXT NOT NULL
       )""",
    """CREATE TRIGGER IF NOT EXISTS noguard_upd_raw_caption
       BEFORE UPDATE ON raw_caption
       BEGIN SELECT RAISE(ABORT, 'raw_caption is frozen: UPDATE forbidden'); END""",
    """CREATE TRIGGER IF NOT EXISTS noguard_del_raw_caption
       BEFORE DELETE ON raw_caption
       BEGIN SELECT RAISE(ABORT, 'raw_caption is frozen: DELETE forbidden'); END""",
    """CREATE TABLE IF NOT EXISTS corpus_attempt (
         att_id TEXT PRIMARY KEY,
         video_id TEXT NOT NULL REFERENCES video(video_id),
         run_id TEXT NOT NULL REFERENCES corpus_run(run_id),
         stage TEXT NOT NULL CHECK(stage IN ('catalog','subtitle_inventory',
                                              'subtitle_download','subtitle_parse',
                                              'freeze','normalize')),
         outcome TEXT NOT NULL CHECK(outcome IN ('success','skipped','missing',
                                                 'auth_required','unavailable',
                                                 'retryable','tool_error',
                                                 'permanent_error','raw_integrity_error',
                                                 'normalize_failed')),
         error_class TEXT,
         detail TEXT,
         retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0,1)),
         occurred_at TEXT NOT NULL
       )""",
    """CREATE INDEX IF NOT EXISTS idx_attempt_video ON corpus_attempt(video_id, occurred_at)""",
    """CREATE INDEX IF NOT EXISTS idx_attempt_outcome ON corpus_attempt(outcome)""",
    """CREATE INDEX IF NOT EXISTS idx_attempt_run ON corpus_attempt(run_id, occurred_at)""",
]


# ---------------------------------------------------------------------------
# DDL — v2 (PR-2: transcript normalizer layer)
# ---------------------------------------------------------------------------

# Append-only v2 adds two tables and one index. The v1 CHECK on corpus_run.kind
# is widened to include 'normalize', and corpus_attempt.stage / outcome CHECKs
# are widened to include 'normalize' and 'normalize_failed'. Because SQLite has
# no ALTER CONSTRAINT, the migration recreates corpus_run / corpus_attempt with
# the new CHECKs. The old data + triggers must be preserved; the canonical
# approach below copies data out, drops, recreates, and copies back.
#
# IMPORTANT: This script runs inside a single BEGIN IMMEDIATE so the temporary
# recreate is atomic. PR-1 v1 lock-in (BEFORE UPDATE / DELETE triggers on
# raw_caption and schema_version) is unchanged.

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS transcript_version (
  transcript_version_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES video(video_id),
  raw_caption_sha256 TEXT NOT NULL,
  normalizer_name TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','failed')),
  UNIQUE (video_id, raw_caption_sha256, normalizer_name, normalizer_version)
);
CREATE INDEX IF NOT EXISTS idx_tv_video ON transcript_version(video_id);

CREATE TABLE IF NOT EXISTS transcript_segment (
  transcript_version_id TEXT NOT NULL
      REFERENCES transcript_version(transcript_version_id),
  ordinal INTEGER NOT NULL,
  start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
  end_ms INTEGER NOT NULL CHECK(end_ms >= start_ms),
  text TEXT NOT NULL CHECK(text != ''),
  raw_cue_start INTEGER NOT NULL,
  raw_cue_end INTEGER NOT NULL CHECK(raw_cue_end >= raw_cue_start),
  speaker TEXT,
  PRIMARY KEY (transcript_version_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_ts_text ON transcript_segment(text);
"""


# Explicit list of v2 SQL statements (mirrors v1's pattern). The corpus_run /
# corpus_attempt CHECK widening is done by the migration runtime, not by raw
# DDL — see `lib/houchen_migrations.py:_apply_v2()`.
_V2_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS transcript_version (
         transcript_version_id TEXT PRIMARY KEY,
         video_id TEXT NOT NULL REFERENCES video(video_id),
         raw_caption_sha256 TEXT NOT NULL,
         normalizer_name TEXT NOT NULL,
         normalizer_version TEXT NOT NULL,
         created_at TEXT NOT NULL,
         content_sha256 TEXT NOT NULL,
         status TEXT NOT NULL CHECK(status IN ('ok','failed')),
         UNIQUE (video_id, raw_caption_sha256, normalizer_name, normalizer_version)
       )""",
    """CREATE INDEX IF NOT EXISTS idx_tv_video ON transcript_version(video_id)""",
    """CREATE TABLE IF NOT EXISTS transcript_segment (
         transcript_version_id TEXT NOT NULL
             REFERENCES transcript_version(transcript_version_id),
         ordinal INTEGER NOT NULL,
         start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
         end_ms INTEGER NOT NULL CHECK(end_ms >= start_ms),
         text TEXT NOT NULL CHECK(text != ''),
         raw_cue_start INTEGER NOT NULL,
         raw_cue_end INTEGER NOT NULL CHECK(raw_cue_end >= raw_cue_start),
         speaker TEXT,
         PRIMARY KEY (transcript_version_id, ordinal)
       )""",
    """CREATE INDEX IF NOT EXISTS idx_ts_text ON transcript_segment(text)""",
]


# Exact v2 column shape — used by `validate_schema()` to refuse wrong
# pre-existing tables (mirrors `_V1_COLUMNS`).
_V2_COLUMNS = {
    "transcript_version": [
        ("transcript_version_id", "TEXT", 0, 1),
        ("video_id", "TEXT", 1, 0),
        ("raw_caption_sha256", "TEXT", 1, 0),
        ("normalizer_name", "TEXT", 1, 0),
        ("normalizer_version", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("content_sha256", "TEXT", 1, 0),
        ("status", "TEXT", 1, 0),
    ],
    "transcript_segment": [
        ("transcript_version_id", "TEXT", 1, 1),
        ("ordinal", "INTEGER", 1, 2),
        ("start_ms", "INTEGER", 1, 0),
        ("end_ms", "INTEGER", 1, 0),
        ("text", "TEXT", 1, 0),
        ("raw_cue_start", "INTEGER", 1, 0),
        ("raw_cue_end", "INTEGER", 1, 0),
        ("speaker", "TEXT", 0, 0),
    ],
}

# table -> list of (from_column, referenced_table, referenced_column)
_V2_FKS = {
    "transcript_version": [("video_id", "video", "video_id")],
    "transcript_segment": [
        ("transcript_version_id", "transcript_version", "transcript_version_id"),
    ],
}

# (index_name, table) -> (unique_flag, [columns])
_V2_INDEX_SPEC = {
    ("idx_tv_video", "transcript_version"): (0, ["video_id"]),
    # The PRIMARY KEY on transcript_segment already provides a unique
    # (transcript_version_id, ordinal) index, but we additionally index `text`
    # so future PR-4 FTS5 / claim search has a non-FTS hook to verify against.
    ("idx_ts_text", "transcript_segment"): (0, ["text"]),
}

# table -> expected CHECK expressions (whitespace-normalized).
_V2_CHECKS = {
    "transcript_version": [
        "status IN ('ok','failed')",
    ],
    "transcript_segment": [
        "start_ms >= 0",
        "end_ms >= start_ms",
        "text != ''",
        "raw_cue_end >= raw_cue_start",
    ],
}


def install_v2(conn) -> None:
    """Run only the v2 table DDL. Used by tests / fast-forward; the canonical
    migration path runs through `lib/houchen_migrations.py` which additionally
    recreates `corpus_run` / `corpus_attempt` to widen their CHECK constraints."""
    conn.executescript(_SCHEMA_V2)


# ---------------------------------------------------------------------------
# Schema validation (P1-1: EXACT v1 validation — columns/types/pk/notnull,
# FKs, index columns+uniqueness, CHECK clauses, and trigger bodies)
# ---------------------------------------------------------------------------

# table -> list of (name, declared_type, notnull, pk_ordinal). pk_ordinal is 0
# for non-PK columns, else the 1-based PK position.
_V1_COLUMNS = {
    "schema_version": [
        ("version", "INTEGER", 0, 1),
        ("applied_at", "TEXT", 1, 0),
        ("description", "TEXT", 1, 0),
    ],
    "corpus_run": [
        ("run_id", "TEXT", 0, 1),
        ("kind", "TEXT", 1, 0),
        ("started_at", "TEXT", 1, 0),
        ("finished_at", "TEXT", 0, 0),
        ("status", "TEXT", 1, 0),
        ("config_sha256", "TEXT", 1, 0),
        ("tool_versions_json", "TEXT", 1, 0),
        ("summary_json", "TEXT", 0, 0),
        ("error_class", "TEXT", 0, 0),
        ("error_detail", "TEXT", 0, 0),
    ],
    "video": [
        ("video_id", "TEXT", 0, 1),
        ("channel_id", "TEXT", 0, 0),
        ("channel_handle", "TEXT", 0, 0),
        ("canonical_url", "TEXT", 0, 0),
        ("title", "TEXT", 0, 0),
        ("description", "TEXT", 0, 0),
        ("published_at", "TEXT", 0, 0),
        ("duration_sec", "INTEGER", 0, 0),
        ("live_status", "TEXT", 0, 0),
        ("availability", "TEXT", 1, 0),
        ("content_kind", "TEXT", 1, 0),
        ("discovered_at", "TEXT", 1, 0),
        ("last_seen_at", "TEXT", 1, 0),
        ("metadata_sha256", "TEXT", 1, 0),
    ],
    "video_collection": [
        ("collection_id", "TEXT", 0, 1),
        ("collection_name", "TEXT", 1, 0),
        ("enumerated_at", "TEXT", 1, 0),
    ],
    "video_collection_membership": [
        ("video_id", "TEXT", 1, 1),
        ("collection_id", "TEXT", 1, 2),
    ],
    "raw_caption": [
        ("video_id", "TEXT", 0, 1),
        ("language", "TEXT", 1, 0),
        ("caption_kind", "TEXT", 1, 0),
        ("format", "TEXT", 1, 0),
        ("content_sha256", "TEXT", 1, 0),
        ("local_path", "TEXT", 1, 0),
        ("byte_count", "INTEGER", 1, 0),
        ("cue_count", "INTEGER", 1, 0),
        ("fetched_at", "TEXT", 1, 0),
        ("yt_dlp_version", "TEXT", 1, 0),
        ("source_metadata_sha256", "TEXT", 1, 0),
    ],
    "corpus_attempt": [
        ("att_id", "TEXT", 0, 1),
        ("video_id", "TEXT", 1, 0),
        ("run_id", "TEXT", 1, 0),
        ("stage", "TEXT", 1, 0),
        ("outcome", "TEXT", 1, 0),
        ("error_class", "TEXT", 0, 0),
        ("detail", "TEXT", 0, 0),
        ("retryable", "INTEGER", 1, 0),
        ("occurred_at", "TEXT", 1, 0),
    ],
}

# table -> list of (from_column, referenced_table, referenced_column)
_V1_FKS = {
    "video_collection_membership": [
        ("collection_id", "video_collection", "collection_id"),
        ("video_id", "video", "video_id"),
    ],
    "raw_caption": [("video_id", "video", "video_id")],
    "corpus_attempt": [
        ("run_id", "corpus_run", "run_id"),
        ("video_id", "video", "video_id"),
    ],
}

# (index_name, table) -> (unique_flag, [columns]) — explicit indexes only.
_V1_INDEX_SPEC = {
    ("idx_corpus_run_started", "corpus_run"): (0, ["started_at"]),
    ("idx_video_availability", "video"): (0, ["availability"]),
    ("idx_video_content_kind", "video"): (0, ["content_kind"]),
    ("idx_video_last_seen", "video"): (0, ["last_seen_at"]),
    ("idx_attempt_video", "corpus_attempt"): (0, ["video_id", "occurred_at"]),
    ("idx_attempt_outcome", "corpus_attempt"): (0, ["outcome"]),
    ("idx_attempt_run", "corpus_attempt"): (0, ["run_id", "occurred_at"]),
}

# table -> expected CHECK expressions (normalized, the inner IN(...) clause).
# After v2 is applied, corpus_run.kind gains 'normalize' and corpus_attempt
# gains 'normalize' / 'normalize_failed'. `_V1_CHECKS` is therefore the
# post-v2 canonical form; `validate_schema()` checks this against the live
# schema once v1 (or v2) has been applied.
_V1_CHECKS = {
    "corpus_run": [
        "kind IN ('catalog','caption_fetch','preflight','normalize')",
        "status IN ('running','success','partial','failed')",
    ],
    "video": [
        "availability IN ('public','unlisted','private','deleted',"
        "'region_blocked','unavailable')",
        "content_kind IN ('video','short','stream','live_replay')",
    ],
    "video_collection": ["collection_name IN ('videos','streams','shorts')"],
    "raw_caption": [
        "caption_kind IN ('manual','auto')",
        "format IN ('json3','vtt','srv1','srv2','srv3','ttml')",
    ],
    "corpus_attempt": [
        "stage IN ('catalog','subtitle_inventory','subtitle_download',"
        "'subtitle_parse','freeze','normalize')",
        "outcome IN ('success','skipped','missing','auth_required','unavailable',"
        "'retryable','tool_error','permanent_error','raw_integrity_error',"
        "'normalize_failed')",
        "retryable IN (0,1)",
    ],
}

# trigger_name -> (table, event, required_abort_message_substring)
_V1_TRIGGER_SPEC = {
    "noguard_upd_schema_version": ("schema_version", "UPDATE",
                                   "schema_version is append-only"),
    "noguard_del_schema_version": ("schema_version", "DELETE",
                                   "schema_version is append-only"),
    "noguard_upd_raw_caption": ("raw_caption", "UPDATE", "raw_caption is frozen"),
    "noguard_del_raw_caption": ("raw_caption", "DELETE", "raw_caption is frozen"),
}


def _normalize_sql(sql: str) -> str:
    import re
    return re.sub(r"\s+", " ", sql or "").strip()


def _strip_ws(sql: str) -> str:
    """Remove ALL whitespace — used to compare CHECK clauses, because SQLite
    reformats them (e.g. inserts a space after a line-wrapped comma) and the
    canonical form is otherwise identical."""
    import re
    return re.sub(r"\s+", "", sql or "")


def _table_xinfo(conn, table):
    return conn.execute(f"PRAGMA table_xinfo({table})").fetchall()


def validate_schema(conn) -> bool:
    """Return True iff the current schema EXACTLY matches v1 + (if applied) v2.

    Checks (P1-1): every table's column names + declared types + NOT NULL +
    PRIMARY KEY; every foreign key; every explicit index's columns +
    uniqueness; every CHECK clause present in the table DDL; every frozen/append
    trigger's table, event, and `RAISE(ABORT, …)` body. A same-named empty
    trigger, a wrong index column, a missing FK, or a wrong CHECK/PK/NOT NULL
    must all fail this check.
    """
    # 1. Tables + full column shape (v1 always; v2 only if applied).
    for table, expected in _V1_COLUMNS.items():
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            return False
        actual = [(r[1], (r[2] or "").upper(), r[3], r[5])
                  for r in _table_xinfo(conn, table)]
        if actual != expected:
            return False

    if _applied_version(conn) >= 2:
        for table, expected in _V2_COLUMNS.items():
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone():
                return False
            actual = [(r[1], (r[2] or "").upper(), r[3], r[5])
                      for r in _table_xinfo(conn, table)]
            if actual != expected:
                return False

    # 2. Foreign keys (v1 always; v2 only if applied).
    for table, expected_fks in _V1_FKS.items():
        actual_fks = conn.execute(
            f"PRAGMA foreign_key_list({table})").fetchall()
        got = {(r[3], r[2], r[4]) for r in actual_fks}   # (from, table, to)
        want = {(f, t, c) for (f, t, c) in expected_fks}
        if got != want:
            return False

    if _applied_version(conn) >= 2:
        for table, expected_fks in _V2_FKS.items():
            actual_fks = conn.execute(
                f"PRAGMA foreign_key_list({table})").fetchall()
            got = {(r[3], r[2], r[4]) for r in actual_fks}
            want = {(f, t, c) for (f, t, c) in expected_fks}
            if got != want:
                return False

    # 3. Explicit indexes (name, table, unique, column list).
    for (name, table), (unique, cols) in _V1_INDEX_SPEC.items():
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? AND tbl_name=?",
            (name, table)).fetchone()
        if not row:
            return False
        got_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({name})").fetchall()]
        got_unique = None
        for ir in conn.execute(f"PRAGMA index_list({table})").fetchall():
            if ir[1] == name:
                got_unique = ir[2]
                break
        if got_cols != cols or (got_unique != 0) != bool(unique):
            return False

    if _applied_version(conn) >= 2:
        for (name, table), (unique, cols) in _V2_INDEX_SPEC.items():
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? AND tbl_name=?",
                (name, table)).fetchone()
            if not row:
                return False
            got_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({name})").fetchall()]
            got_unique = None
            for ir in conn.execute(f"PRAGMA index_list({table})").fetchall():
                if ir[1] == name:
                    got_unique = ir[2]
                    break
            if got_cols != cols or (got_unique != 0) != bool(unique):
                return False

    # 4. CHECK clauses present in each table's DDL (whitespace-insensitive,
    # since SQLite reformats line-wrapped CHECK lists).
    for table, checks in _V1_CHECKS.items():
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        norm = _strip_ws(sql[0]) if sql else ""
        for check in checks:
            if _strip_ws(check) not in norm:
                return False

    if _applied_version(conn) >= 2:
        for table, checks in _V2_CHECKS.items():
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone()
            norm = _strip_ws(sql[0]) if sql else ""
            for check in checks:
                if _strip_ws(check) not in norm:
                    return False

    # 5. Triggers: table, event, and RAISE(ABORT, …) body (v1 only — v2 adds no
    # new triggers because the v2 normalizer has no immutable rows to guard).
    for name, (table, event, msg) in _V1_TRIGGER_SPEC.items():
        row = conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master WHERE type='trigger' AND name=?",
            (name,)).fetchone()
        if not row:
            return False
        norm = _normalize_sql(row[1])
        if row[0] != table:
            return False
        if f"BEFORE {event}" not in norm.upper():
            return False
        if "RAISE(ABORT" not in norm.upper():
            return False
        if msg not in norm:
            return False

    return True


def _applied_version(conn) -> int:
    """Best-effort current schema_version without crashing on a fresh DB."""
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    return row[0] or 0


# ---------------------------------------------------------------------------
# Per-video state derivation (P1-5 / P1-3) — the ONE place status/coverage/
# runner resolve "what is this video's current state". Bulk consumers MUST use
# the single-SQL `video_states()` / `pending_video_ids()` below (no per-video
# N+1); single-video helpers (`video_state`, `is_pending`) remain for tests and
# one-off checks.
# ---------------------------------------------------------------------------

_LATEST_FREEZE_CTE = """
latest_freeze AS (
    SELECT video_id, outcome,
           ROW_NUMBER() OVER (
               PARTITION BY video_id
               ORDER BY occurred_at DESC, att_id DESC
           ) AS rn
    FROM corpus_attempt
    WHERE stage = 'freeze'
)
"""


def latest_freeze_outcome(conn, video_id: str) -> str | None:
    """Most recent freeze-stage attempt outcome for a video, or None."""
    row = conn.execute(
        "SELECT outcome FROM corpus_attempt"
        " WHERE video_id=? AND stage='freeze'"
        " ORDER BY occurred_at DESC, att_id DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    return row[0] if row else None


def video_state(conn, video_id: str) -> str:
    """Terminal state name for a video: frozen | pending | <outcome>."""
    frozen = conn.execute(
        "SELECT 1 FROM raw_caption WHERE video_id=?", (video_id,)
    ).fetchone()
    if frozen:
        return "frozen"
    outcome = latest_freeze_outcome(conn, video_id)
    if outcome is None:
        return "pending"
    return outcome


def is_pending(conn, video_id: str) -> bool:
    """True if the video should be selected by default (not yet frozen and not
    terminal-missing/permanent)."""
    state = video_state(conn, video_id)
    return state in ("pending",) or state in RESELECTABLE_OUTCOMES


_VIDEO_STATES_SQL = (
    f"WITH {_LATEST_FREEZE_CTE}"
    " SELECT v.video_id,"
    "   CASE WHEN rc.video_id IS NOT NULL THEN 'frozen'"
    "        WHEN lf.outcome IS NULL THEN 'pending'"
    "        ELSE lf.outcome END AS state"
    " FROM video v"
    " LEFT JOIN raw_caption rc ON rc.video_id = v.video_id"
    " LEFT JOIN latest_freeze lf ON lf.video_id = v.video_id AND lf.rn = 1"
)


def video_states(conn) -> dict:
    """Return {video_id: state} for ALL videos in ONE SQL pass (P1-3: no N+1).

    state ∈ {'frozen', 'pending'} ∪ corpus_attempt.outcome values."""
    return {r[0]: r[1] for r in conn.execute(_VIDEO_STATES_SQL).fetchall()}


def pending_video_ids(conn) -> list:
    """Video IDs that should be selected by default, ordered by discovered_at.

    A single SQL query (P1-3): no raw_caption AND (no freeze outcome OR the
    latest freeze outcome is reselectable)."""
    reselect = ", ".join(repr(o) for o in sorted(RESELECTABLE_OUTCOMES))
    sql = (
        f"WITH {_LATEST_FREEZE_CTE}"
        " SELECT v.video_id"
        " FROM video v"
        " LEFT JOIN raw_caption rc ON rc.video_id = v.video_id"
        " LEFT JOIN latest_freeze lf ON lf.video_id = v.video_id AND lf.rn = 1"
        " WHERE rc.video_id IS NULL"
        f"   AND (lf.outcome IS NULL OR lf.outcome IN ({reselect}))"
        " ORDER BY v.discovered_at ASC"
    )
    return [r[0] for r in conn.execute(sql).fetchall()]


# Latest applied schema version. Bumped from 1 → 2 by PR-2 (transcript
# normalizer layer).
VERSION = 2
