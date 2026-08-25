"""
macro_bridge.py — Read-only bridge between macro store.db and HouChen claims.

Reads macro observations from store.db (readonly), matches against accepted
HouChen claims via keyword mapping, produces macro_link_candidate records
in houchen.db, and exports JSONL.

Core principle: ZERO writes to store.db.
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MACRO_STORE_PATH = _PROJECT_ROOT / "data" / "store.db"
_HOUCHEN_DB_PATH = _PROJECT_ROOT / "data" / "houchen" / "houchen.sqlite3"
_KEYWORDS_PATH = _PROJECT_ROOT / "config" / "macro_bridge_keywords.yaml"

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

MACRO_LINK_CANDIDATE_DDL = """\
CREATE TABLE IF NOT EXISTS macro_link_candidate (
    candidate_id    TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL REFERENCES claim(claim_id),
    macro_source    TEXT NOT NULL,
    macro_series    TEXT NOT NULL,
    macro_period    TEXT NOT NULL,
    macro_value     REAL,
    relation        TEXT NOT NULL CHECK(relation IN (
                        'supports','challenges','contextualizes','unresolved')),
    confidence      TEXT CHECK(confidence IN ('high','medium','low')),
    reasoning       TEXT,
    created_at      TEXT NOT NULL,
    method          TEXT NOT NULL DEFAULT 'keyword_match',
    reviewed        INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0,1))
);
"""

MACRO_LINK_CANDIDATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_mlc_claim ON macro_link_candidate(claim_id);",
    "CREATE INDEX IF NOT EXISTS idx_mlc_macro ON macro_link_candidate(macro_source, macro_series);",
    "CREATE INDEX IF NOT EXISTS idx_mlc_relation ON macro_link_candidate(relation);",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class MacroLinkCandidate:
    """A candidate link between a HouChen claim and a macro observation."""

    def __init__(
        self,
        candidate_id: str,
        claim_id: str,
        macro_source: str,
        macro_series: str,
        macro_period: str,
        macro_value: float | None,
        relation: str,
        confidence: str | None,
        reasoning: str | None,
        method: str = "keyword_match",
    ):
        self.candidate_id = candidate_id
        self.claim_id = claim_id
        self.macro_source = macro_source
        self.macro_series = macro_series
        self.macro_period = macro_period
        self.macro_value = macro_value
        self.relation = relation
        self.confidence = confidence
        self.reasoning = reasoning
        self.method = method

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "claim_id": self.claim_id,
            "macro_source": self.macro_source,
            "macro_series": self.macro_series,
            "macro_period": self.macro_period,
            "macro_value": self.macro_value,
            "relation": self.relation,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "method": self.method,
        }

    def to_row(self) -> tuple:
        from datetime import datetime, timezone
        return (
            self.candidate_id,
            self.claim_id,
            self.macro_source,
            self.macro_series,
            self.macro_period,
            self.macro_value,
            self.relation,
            self.confidence,
            self.reasoning,
            datetime.now(timezone.utc).isoformat(),
            self.method,
            0,  # reviewed
        )


# ---------------------------------------------------------------------------
# Macro store access (READ ONLY)
# ---------------------------------------------------------------------------

def open_macro_store_readonly(store_path: Path | None = None) -> sqlite3.Connection:
    """Open macro store.db in read-only mode.

    Uses file URI with mode=ro and PRAGMA query_only as double insurance.
    """
    path = store_path or _MACRO_STORE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Macro store not found: {path}")
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_latest_observations(
    macro_conn: sqlite3.Connection,
) -> dict[str, dict]:
    """Fetch the latest observation for each (source, series) pair.

    Returns: {(source, series): {source, series, date, value}}
    """
    rows = macro_conn.execute("""
        SELECT o.source, o.series, o.date, o.value
        FROM observations o
        INNER JOIN (
            SELECT source, series, MAX(date) as max_date
            FROM observations
            GROUP BY source, series
        ) latest ON o.source = latest.source
                AND o.series = latest.series
                AND o.date = latest.max_date
    """).fetchall()
    result = {}
    for r in rows:
        key = f"{r['source']}:{r['series']}"
        result[key] = {
            "source": r["source"],
            "series": r["series"],
            "date": r["date"],
            "value": r["value"],
        }
    return result


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def load_keywords(path: Path | None = None) -> dict[str, list[str]]:
    """Load keyword → macro series mapping from YAML config."""
    p = path or _KEYWORDS_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        data = yaml.safe_load(f)
    return data.get("keywords", {})


def _match_keywords(
    claim_text: str,
    keywords: dict[str, list[str]],
) -> list[str]:
    """Return macro series keys that match any keyword in claim_text."""
    matched = []
    text_lower = claim_text.lower()
    for keyword, series_list in keywords.items():
        if keyword.lower() in text_lower:
            matched.extend(series_list)
    # deduplicate preserving order
    seen = set()
    result = []
    for s in matched:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# Relation assessment
# ---------------------------------------------------------------------------

def _assess_relation(
    claim_text: str,
    claim_type: str,
    macro_key: str,
    observation: dict | None,
) -> tuple[str, str | None, str | None]:
    """Assess the relation between a claim and a macro observation.

    Returns: (relation, confidence, reasoning)

    For keyword_match v1:
    - If no observation data → unresolved
    - If keyword matched but claim is descriptive/contextual → contextualizes
    - If claim is predictive/causal → supports/challenges based on trend (deferred)
    - Default → contextualizes
    """
    if observation is None:
        return ("unresolved", "low", "No macro observation available for this series")

    # Empty series list (e.g., 贸易战 with no macro series) → contextualizes
    if not macro_key:
        return ("contextualizes", "low", "No direct macro series; contextual reference")

    # For v1: all matches are contextualizes (safe default)
    # Future: parse claim sentiment + macro trend direction for supports/challenges
    value = observation.get("value")
    date = observation.get("date", "?")
    reasoning = f"Keyword match to {macro_key}; latest value={value} at {date}"

    # Heuristic: if claim_type is descriptive, it's contextualizes
    if claim_type in ("descriptive", "definition"):
        return ("contextualizes", "medium", reasoning)

    # For predictive/causal claims, we'd need trend analysis (v2)
    # For now, mark as unresolved to signal human review needed
    if claim_type in ("predictive", "causal"):
        return ("unresolved", "low",
                f"{reasoning}; predictive/causal claim needs trend analysis (v2)")

    return ("contextualizes", "medium", reasoning)


# ---------------------------------------------------------------------------
# Core: find candidates for a claim
# ---------------------------------------------------------------------------

def find_candidates(
    claim_id: str,
    claim_text: str,
    claim_type: str,
    keywords: dict[str, list[str]],
    observations: dict[str, dict],
) -> list[MacroLinkCandidate]:
    """Find macro link candidates for a single claim.

    Args:
        claim_id: HouChen claim ID
        claim_text: The claim text
        claim_type: claim type (descriptive, causal, predictive, etc.)
        keywords: keyword → series mapping
        observations: latest macro observations keyed by source:series

    Returns:
        List of MacroLinkCandidate objects
    """
    matched_keys = _match_keywords(claim_text, keywords)

    if not matched_keys:
        return []

    candidates = []
    seen_series = set()

    for macro_key in matched_keys:
        if macro_key in seen_series:
            continue
        seen_series.add(macro_key)

        obs = observations.get(macro_key)
        relation, confidence, reasoning = _assess_relation(
            claim_text, claim_type, macro_key, obs
        )

        source, series = macro_key.split(":", 1) if ":" in macro_key else (macro_key, "")

        candidate = MacroLinkCandidate(
            candidate_id=f"mlc_{uuid.uuid7()}",
            claim_id=claim_id,
            macro_source=source,
            macro_series=series,
            macro_period=obs["date"] if obs else "",
            macro_value=obs["value"] if obs else None,
            relation=relation,
            confidence=confidence,
            reasoning=reasoning,
            method="keyword_match",
        )
        candidates.append(candidate)

    return candidates


# ---------------------------------------------------------------------------
# Scan all accepted claims
# ---------------------------------------------------------------------------

def scan_all(
    houchen_conn: sqlite3.Connection,
    macro_conn: sqlite3.Connection,
    keywords_path: Path | None = None,
) -> list[MacroLinkCandidate]:
    """Scan all accepted HouChen claims and produce macro link candidates.

    Writes candidates to houchen.db macro_link_candidate table.
    """
    keywords = load_keywords(keywords_path)
    observations = fetch_latest_observations(macro_conn)

    # Fetch accepted claims
    rows = houchen_conn.execute("""
        SELECT claim_id, claim_text, claim_type
        FROM claim
        WHERE status = 'accepted'
    """).fetchall()

    all_candidates = []
    for row in rows:
        candidates = find_candidates(
            claim_id=row["claim_id"],
            claim_text=row["claim_text"],
            claim_type=row["claim_type"],
            keywords=keywords,
            observations=observations,
        )
        all_candidates.extend(candidates)

    # Write to houchen.db
    if all_candidates:
        _ensure_table(houchen_conn)
        houchen_conn.executemany(
            """INSERT INTO macro_link_candidate
               (candidate_id, claim_id, macro_source, macro_series,
                macro_period, macro_value, relation, confidence, reasoning,
                created_at, method, reviewed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [c.to_row() for c in all_candidates],
        )
        houchen_conn.commit()

    return all_candidates


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create macro_link_candidate table if not exists."""
    conn.execute(MACRO_LINK_CANDIDATE_DDL)
    for idx in MACRO_LINK_CANDIDATE_INDEXES:
        conn.execute(idx)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_jsonl(
    houchen_conn: sqlite3.Connection,
    output_path: Path,
) -> int:
    """Export all macro_link_candidate records to JSONL.

    Returns: number of records exported.
    """
    rows = houchen_conn.execute("""
        SELECT candidate_id, claim_id, macro_source, macro_series,
               macro_period, macro_value, relation, confidence, reasoning,
               created_at, method, reviewed
        FROM macro_link_candidate
        ORDER BY created_at
    """).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w") as f:
        for row in rows:
            record = {
                "candidate_id": row["candidate_id"],
                "claim_id": row["claim_id"],
                "macro_source": row["macro_source"],
                "macro_series": row["macro_series"],
                "macro_period": row["macro_period"],
                "macro_value": row["macro_value"],
                "relation": row["relation"],
                "confidence": row["confidence"],
                "reasoning": row["reasoning"],
                "created_at": row["created_at"],
                "method": row["method"],
                "reviewed": bool(row["reviewed"]),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    return count


# ---------------------------------------------------------------------------
# Verify SHA
# ---------------------------------------------------------------------------

def verify_store_sha(
    expected_sha: str,
    store_path: Path | None = None,
) -> bool:
    """Verify that store.db SHA matches expected value."""
    import hashlib
    path = store_path or _MACRO_STORE_PATH
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    actual = h.hexdigest()
    return actual == expected_sha


# ---------------------------------------------------------------------------
# Import to evaluation (for reviewed candidates only)
# ---------------------------------------------------------------------------

def import_to_evaluation(
    candidate: MacroLinkCandidate,
    houchen_conn: sqlite3.Connection,
    evaluator: str = "macro_bridge",
) -> str:
    """Import a reviewed candidate into the evaluation table.

    Only call for candidates with reviewed=1.
    Returns the evaluation_id.
    """
    if not candidate.relation:
        raise ValueError("Cannot import candidate without relation")

    evaluation_id = f"evl_{uuid.uuid7()}"
    verdict_map = {
        "supports": "confirmed",
        "challenges": "contested",
        "contextualizes": "partial",
        "unresolved": "pending",
    }

    from datetime import datetime, timezone
    houchen_conn.execute(
        """INSERT INTO evaluation
           (evaluation_id, target_kind, target_id, evaluator, as_of,
            verdict, reasoning, status, external_evidence_id, created_at)
           VALUES (?, 'claim', ?, ?, ?, ?, ?, 'draft', NULL, ?)""",
        (
            evaluation_id,
            candidate.claim_id,
            evaluator,
            candidate.macro_period,
            verdict_map.get(candidate.relation, "pending"),
            candidate.reasoning,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    houchen_conn.commit()
    return evaluation_id
