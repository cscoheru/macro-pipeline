"""Read-only status and coverage aggregation (PR-1, P1-5/P2-2 hardened).

Both functions use `houchen_schema.video_state()` as the SINGLE source of
truth for a video's terminal state, so status/coverage/runner selection and
oldest-pending can never disagree. They are pure reads: no directory
creation, no migration, no writes. They accept either a normal or a
`mode=ro` connection.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import houchen_schema


OUTPUT_VERSION = "1.2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_schema_version(conn) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except Exception:
        return 0
    return row[0] or 0


def _state_counts(conn) -> dict:
    """Count videos by their derived state (frozen / pending / terminal outcome).

    Computed in ONE SQL pass via `houchen_schema.video_states()` (P1-3: no
    per-video N+1)."""
    buckets = {
        "frozen": 0, "pending": 0, "missing": 0, "auth_required": 0,
        "unavailable": 0, "retryable": 0, "tool_error": 0,
        "permanent_error": 0, "raw_integrity_error": 0,
    }
    for state in houchen_schema.video_states(conn).values():
        buckets[state] = buckets.get(state, 0) + 1
    return buckets


def _transcript_state_counts(conn) -> dict:
    """PR-2 transcript state buckets (orthogonal to the PR-1 caption state).

    - `normalized`: video has a frozen raw_caption AND at least one successful
      (`status='ok'`) `transcript_version` row.
    - `pending_normalize`: video has a frozen raw_caption but NO successful
      `transcript_version` row yet (eligible for the default `normalize` run).
    - `no_caption`: video has no frozen raw_caption (counted for parity only).

    Single SQL pass via a CTE (P1-3: no per-video N+1). If the v2 schema is
    not yet applied, every video falls into `no_caption` / `pending_normalize`
    buckets and the function still returns.
    """
    applied = _schema_version(conn)
    if applied < 2:
        return {"normalized": 0, "pending_normalize": 0, "no_caption": 0}
    rows = conn.execute(
        "WITH latest_tv AS ("
        "    SELECT video_id, status,"
        "           ROW_NUMBER() OVER ("
        "               PARTITION BY video_id"
        "               ORDER BY created_at DESC, transcript_version_id DESC"
        "           ) AS rn"
        "    FROM transcript_version"
        " )"
        " SELECT"
        "   SUM(CASE WHEN rc.video_id IS NOT NULL AND lt.status='ok'"
        "            THEN 1 ELSE 0 END) AS normalized,"
        "   SUM(CASE WHEN rc.video_id IS NOT NULL AND (lt.status IS NULL OR lt.status<>'ok')"
        "            THEN 1 ELSE 0 END) AS pending_normalize,"
        "   SUM(CASE WHEN rc.video_id IS NULL THEN 1 ELSE 0 END) AS no_caption"
        " FROM video v"
        " LEFT JOIN raw_caption rc ON rc.video_id = v.video_id"
        " LEFT JOIN latest_tv lt ON lt.video_id = v.video_id AND lt.rn = 1"
    ).fetchone()
    return {
        "normalized": rows[0] or 0,
        "pending_normalize": rows[1] or 0,
        "no_caption": rows[2] or 0,
    }


def _claim_state_counts(conn) -> dict:
    """PR-3 claim-state buckets (orthogonal to caption + transcript state).

    Counts `claim` rows grouped by `status`. Pre-PR-3 schemas return the
    empty bucket (no claim rows yet).
    """
    applied = _schema_version(conn)
    if applied < 3:
        return {"accepted": 0, "needs_review": 0, "rejected": 0,
                "proposed": 0}
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM claim GROUP BY status"
    ).fetchall()
    out = {"accepted": 0, "needs_review": 0, "rejected": 0, "proposed": 0}
    for r in rows:
        out[r[0] or "unknown"] = r[1]
    return out


def _concept_state_counts(conn) -> dict:
    """PR-3 concept-state buckets: seed (domain rows) + proposed / canonical /
    deprecated concept rows. Pre-PR-3 returns 0 for every bucket."""
    applied = _schema_version(conn)
    if applied < 3:
        return {"seed": 0, "proposed": 0, "canonical": 0, "deprecated": 0}
    seed = conn.execute("SELECT COUNT(*) FROM domain").fetchone()[0] or 0
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM concept GROUP BY status"
    ).fetchall()
    out = {"seed": seed, "proposed": 0, "canonical": 0, "deprecated": 0}
    for r in rows:
        out[r[0] or "unknown"] = r[1]
    return out


def _analyze_scope_counts(conn) -> dict:
    """PR-3 analyze-scope buckets, derived without historical-run inflation.

    `latest_tv` provides one current transcript per video and `analyzed`
    deduplicates successful analyze attempts whose parent run completed, so
    the two aggregate buckets remain mutually exclusive.
    """
    applied = _schema_version(conn)
    if applied < 3:
        return {"pending_analyze": 0, "analyzed": 0}
    row = conn.execute(
        "WITH latest_tv AS ("
        "  SELECT video_id, status,"
        "         ROW_NUMBER() OVER (PARTITION BY video_id"
        "           ORDER BY created_at DESC, transcript_version_id DESC) AS rn"
        "  FROM transcript_version"
        "), analyzed AS ("
        "  SELECT DISTINCT ca.video_id FROM corpus_attempt ca"
        "  JOIN corpus_run cr ON cr.run_id=ca.run_id"
        "  WHERE ca.stage='analyze' AND ca.outcome='success'"
        "    AND cr.kind='analyze' AND cr.status='success'"
        ")"
        " SELECT"
        "  SUM(CASE WHEN tv.status='ok' AND a.video_id IS NULL THEN 1 ELSE 0 END),"
        "  SUM(CASE WHEN tv.status='ok' AND a.video_id IS NOT NULL THEN 1 ELSE 0 END)"
        " FROM video v"
        " LEFT JOIN latest_tv tv ON tv.video_id=v.video_id AND tv.rn=1"
        " LEFT JOIN analyzed a ON a.video_id=v.video_id"
    ).fetchone()
    return {"pending_analyze": row[0] or 0, "analyzed": row[1] or 0}


def _schema_version(conn) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version").fetchone()
    except Exception:
        return 0
    return row[0] or 0


def status(conn, *, yt_dlp_version: str = "") -> dict:
    buckets = _state_counts(conn)
    transcripts = _transcript_state_counts(conn)
    claims = _claim_state_counts(conn)
    concepts = _concept_state_counts(conn)
    return {
        "schema_version": _current_schema_version(conn),
        "output_version": OUTPUT_VERSION,
        "generated_at": _now(),
        "tools": {"yt_dlp_version": yt_dlp_version},
        "totals": {
            "videos": sum(buckets.values()),
            "by_availability": _count_by(conn, "video", "availability"),
            "by_content_kind": _count_by(conn, "video", "content_kind"),
        },
        "captions": {
            "frozen": buckets["frozen"],
            "pending": buckets["pending"],
            "missing": buckets["missing"],
            "auth_required": buckets["auth_required"],
            "unavailable": buckets["unavailable"],
            "retryable": buckets["retryable"],
            "tool_error": buckets["tool_error"],
            "permanent_error": buckets["permanent_error"],
            "raw_integrity_error": buckets["raw_integrity_error"],
        },
        "transcripts": {
            "normalized": transcripts["normalized"],
            "pending_normalize": transcripts["pending_normalize"],
        },
        "claims": claims,
        "concepts": concepts,
        "analyze_scope": _analyze_scope_counts(conn),
        "oldest_pending": _oldest_pending(conn),
        "recent_errors_by_class": _recent_error_classes(conn),
    }


def coverage(conn) -> dict:
    buckets = _state_counts(conn)
    transcripts = _transcript_state_counts(conn)
    claims = _claim_state_counts(conn)
    concepts = _concept_state_counts(conn)
    return {
        "schema_version": _current_schema_version(conn),
        "output_version": OUTPUT_VERSION,
        "generated_at": _now(),
        "by_collection": _count_by_collection(conn),
        "by_availability": _count_by(conn, "video", "availability"),
        "by_content_kind": _count_by(conn, "video", "content_kind"),
        "caption_outcomes": buckets,
        "transcript_state": transcripts,
        "claim_outcomes": claims,
        "concept_state": concepts,
        "analyze_scope": _analyze_scope_counts(conn),
        "catalog_partial": _catalog_partial(conn),
    }


def coverage_markdown(conn) -> str:
    cov = coverage(conn)
    lines = ["# Hou Chen corpus coverage (PR-1 + PR-3)", "",
             f"schema_version={cov['schema_version']} output_version={cov['output_version']}",
             f"generated_at={cov['generated_at']}", ""]
    lines.append("## By collection")
    for name, n in sorted(cov["by_collection"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## By availability")
    for name, n in sorted(cov["by_availability"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Caption outcomes")
    for name, n in sorted(cov["caption_outcomes"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Transcript state")
    for name, n in sorted(cov["transcript_state"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Claim outcomes")
    for name, n in sorted(cov["claim_outcomes"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Concept state")
    for name, n in sorted(cov["concept_state"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Analyze scope")
    for name, n in sorted(cov["analyze_scope"].items()):
        lines.append(f"- {name}: {n}")
    lines.append("")
    lines.append("## Catalog partial gaps")
    for g in cov["catalog_partial"]:
        lines.append(
            f"- {g['started_at']} {g['run_id']} tab={g['tab']}"
            f" error={g['error_class']}"
        )
    return "\n".join(lines)


def to_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------

def _count_by(conn, table, group_col):
    rows = conn.execute(
        f"SELECT {group_col}, COUNT(*) FROM {table} GROUP BY {group_col}"
    ).fetchall()
    return {r[0] or "None": r[1] for r in rows}


def _count_by_collection(conn):
    rows = conn.execute(
        "SELECT vc.collection_name, COUNT(m.video_id)"
        " FROM video_collection vc"
        " LEFT JOIN video_collection_membership m ON m.collection_id=vc.collection_id"
        " GROUP BY vc.collection_name"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _catalog_partial(conn, limit=10):
    """Recent, bounded catalog partial gaps (P1-5): run_id, started_at, failed
    tab and error_class/outcome, all redacted. Empty list when none."""
    rows = conn.execute(
        "SELECT run_id, started_at, summary_json FROM corpus_run"
        " WHERE kind='catalog' AND status='partial'"
        " ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    gaps = []
    for r in rows:
        try:
            summary = json.loads(r["summary_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        tabs = summary.get("tabs") or {}
        for tab, tsum in tabs.items():
            if not isinstance(tsum, dict) or tsum.get("status") != "failed":
                continue
            err = tsum.get("error") or {}
            gaps.append({
                "run_id": r["run_id"],
                "started_at": r["started_at"],
                "tab": tab,
                "error_class": err.get("error_class") or err.get("outcome"),
            })
    return gaps


def _oldest_pending(conn):
    """Earliest discovered_at among videos that are still pending/reselectable.

    A single SQL query (P1-3), not a per-video scan."""
    reselect = ", ".join(repr(o) for o in sorted(houchen_schema.RESELECTABLE_OUTCOMES))
    row = conn.execute(
        "SELECT MIN(v.discovered_at)"
        " FROM video v"
        " LEFT JOIN raw_caption rc ON rc.video_id = v.video_id"
        " LEFT JOIN ("
        "   SELECT video_id, outcome, ROW_NUMBER() OVER ("
        "       PARTITION BY video_id ORDER BY occurred_at DESC, att_id DESC"
        "   ) AS rn FROM corpus_attempt WHERE stage='freeze'"
        " ) lf ON lf.video_id = v.video_id AND lf.rn = 1"
        " WHERE rc.video_id IS NULL"
        f"   AND (lf.outcome IS NULL OR lf.outcome IN ({reselect}))"
    ).fetchone()
    return row[0] if row else None


def _recent_error_classes(conn, limit=10):
    rows = conn.execute(
        "SELECT error_class, COUNT(*) FROM corpus_attempt"
        " WHERE stage='freeze' AND outcome NOT IN ('success','skipped')"
        " GROUP BY error_class ORDER BY COUNT(*) DESC LIMIT ?", (limit,)
    ).fetchall()
    return {r[0] or "unknown": r[1] for r in rows}
