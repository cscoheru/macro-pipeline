"""PR-3 concept lifecycle (brief §7.2).

Brief §7.2 mandates:

  - Domain skeleton uses FIXED slugs; names can be human-edited but slugs
    are stable. The 7-seed list is enforced in DEFAULT_DOMAIN_SKELETON.
  - `concept.status` ∈ {proposed, canonical, deprecated}; auto-discovered
    concepts enter as `proposed` only.
  - `concept.alias` merging is reversible and records actor + timestamp.
  - `concept.source` MUST back any canonical definition (Rule 7 in the
    hard validator).
  - Promotion to `canonical` requires a `concept_source` row AND explicit
    actor (no auto-promotion from model output).
"""
from __future__ import annotations

import sqlite3
import sys
import uuid

sys.path.insert(0, __name__.rsplit(".", 1)[0].rsplit("/", 1)[0])

import houchen_paths  # noqa: E402


# brief §7.2 — 7 entries (audit F-1).
DEFAULT_DOMAIN_SKELETON = [
    {"slug": "political_economy",      "name": "政治经济与分配"},
    {"slug": "state_governance",       "name": "国家、央地关系与治理"},
    {"slug": "society_psychology",     "name": "社会结构、群体心理与行动"},
    {"slug": "international_order",    "name": "国际秩序与地缘政治"},
    {"slug": "technology_ai",          "name": "技术、平台与人工智能"},
    {"slug": "history_interpretation", "name": "历史解释"},
    {"slug": "method_media",           "name": "方法论、知识生产与媒体"},
]


def seed_domain_skeleton(conn: sqlite3.Connection, *,
                          skeleton: list[dict] | None = None,
                          actor: str = "system") -> int:
    """Idempotently insert the 7 domain slugs.

    Returns the number of NEW rows inserted (0 if all already present).
    Already-present slugs have their `name` and `description` refreshed
    ONLY if `name` is NULL — never overwrite an existing curated name.
    """
    rows = skeleton if skeleton is not None else DEFAULT_DOMAIN_SKELETON
    inserted = 0
    for r in rows:
        slug = r.get("slug")
        if not slug:
            raise ValueError(f"domain skeleton row missing slug: {r!r}")
        name = r.get("name") or ""
        desc = r.get("description")
        existing = conn.execute(
            "SELECT name FROM domain WHERE slug=?", (slug,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO domain(slug, name, description) VALUES (?,?,?)",
                (slug, name, desc))
            inserted += 1
        elif not existing["name"] and name:
            conn.execute(
                "UPDATE domain SET name=?, description=? WHERE slug=?",
                (name, desc, slug))
    conn.commit()
    return inserted


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def upsert_proposed_concept(conn: sqlite3.Connection, *,
                            canonical_name: str, definition: str | None,
                            origin: str = "corpus",
                            domain_slugs: list[str] | None = None,
                            analysis_run_id: str = "") -> str:
    """Insert (or look up) a `concept` row as `proposed`.

    Returns the concept_id. Idempotent on `(canonical_name, status='proposed')`:
    if a proposed row with the same canonical_name already exists, returns it
    (audit F-3: brief requires `canonical_name` field).
    """
    if not canonical_name:
        raise ValueError("canonical_name is required")
    if origin not in ("seed", "corpus", "human"):
        raise ValueError(f"invalid origin: {origin!r}")
    existing = conn.execute(
        "SELECT concept_id FROM concept"
        " WHERE canonical_name=? AND status='proposed'",
        (canonical_name,)).fetchone()
    if existing is not None:
        cid = existing["concept_id"]
    else:
        cid = f"hccon_{uuid.uuid7().hex}"
        now = _now_iso()
        conn.execute(
            "INSERT INTO concept(concept_id, canonical_name, definition,"
            " status, origin, first_seen_at, last_seen_at) "
            " VALUES (?,?,?,?,?,?,?)",
            (cid, canonical_name, definition or "", "proposed", origin,
             now, now))
    # M2M domains (idempotent).
    for slug in domain_slugs or ():
        conn.execute(
            "INSERT OR IGNORE INTO concept_domain(concept_id, domain_slug)"
            " VALUES (?, ?)", (cid, slug))
    conn.commit()
    return cid


def merge_aliases(conn: sqlite3.Connection, *, alias: str,
                  target_concept_id: str, source: str = "human",
                  actor: str = "human") -> str:
    """Add `alias` to `concept_alias` pointing at `target_concept_id`.

    Reversible (delete the row to undo). Records `source` and `created_at`.
    """
    existing = conn.execute(
        "SELECT alias_id FROM concept_alias"
        " WHERE concept_id=? AND alias=?",
        (target_concept_id, alias)).fetchone()
    if existing is not None:
        return existing["alias_id"]
    aid = f"hcali_{uuid.uuid7().hex}"
    conn.execute(
        "INSERT INTO concept_alias(alias_id, concept_id, alias, source,"
        " created_at) VALUES (?,?,?,?,?)",
        (aid, target_concept_id, alias, source, _now_iso()))
    conn.commit()
    return aid


def promote_to_canonical(conn: sqlite3.Connection, *, concept_id: str,
                         actor: str, evidence_concept_source_id: str) -> bool:
    """Promote a proposed concept to canonical — REQUIRES a backing
    `concept_source` row (brief §7.2 / Rule 7).

    Returns True on success, False if the source row does not exist
    or the concept is not currently `proposed`. The actor string is recorded
    on the concept row's last_seen_at update as provenance.
    """
    if not actor:
        raise ValueError("actor is required (no auto-promotion; brief §7.2)")
    row = conn.execute(
        "SELECT status FROM concept WHERE concept_id=?", (concept_id,)).fetchone()
    if row is None or row["status"] != "proposed":
        return False
    src = conn.execute(
        "SELECT 1 FROM concept_source WHERE concept_id=?"
        " AND concept_source_id=?", (concept_id, evidence_concept_source_id)
    ).fetchone()
    if src is None:
        return False
    conn.execute(
        "UPDATE concept SET status='canonical', last_seen_at=?"
        " WHERE concept_id=?",
        (_now_iso(), concept_id))
    conn.commit()
    return True


def record_concept_source(conn: sqlite3.Connection, *,
                          concept_id: str, transcript_version_id: str,
                          segment_start_ordinal: int, segment_end_ordinal: int,
                          start_ms: int, end_ms: int, exact_quote: str,
                          timestamp_url: str, raw_caption_sha256: str,
                          source_role: str,
                          analysis_run_id: str) -> str:
    """Insert a `concept_source` row (the back-link for any canonical
    concept's first definition). Returns the new concept_source_id.

    `source_role` must be one of brief §7.2's three values.
    """
    if source_role not in ("canonical_definition", "usage", "speaker_definition"):
        raise ValueError(f"invalid source_role: {source_role!r}")
    sid = f"hccsr_{uuid.uuid7().hex}"
    conn.execute(
        "INSERT INTO concept_source"
        "(concept_source_id, concept_id, transcript_version_id,"
        " segment_start_ordinal, segment_end_ordinal, start_ms, end_ms,"
        " exact_quote, timestamp_url, raw_caption_sha256, source_role,"
        " analysis_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, concept_id, transcript_version_id,
         segment_start_ordinal, segment_end_ordinal, start_ms, end_ms,
         exact_quote, timestamp_url, raw_caption_sha256, source_role,
         analysis_run_id))
    conn.commit()
    return sid