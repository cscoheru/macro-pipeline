"""PR-4 Phase 0 — FTS5 search engine (brief §10).

A thin wrapper over the four v4 FTS5 virtual tables:

  - transcript_fts (text, transcript_version_id, start_ms, end_ms, ordinal)
  - claim_fts       (claim_text, claim_id, claim_type, layer, video_id)
  - concept_fts     (canonical_name, definition, concept_id, status)
  - concept_alias_fts (alias, concept_id, source)

The module is read-only. It never writes to any FTS table, never
modifies the corpus, and never imports `lib/insight_publisher.py` or
the macro store. The fixed query set in
`scripts/houchen_fixtures/fixed_query_set.py` is the gate that any future
tokenizer change must pass.

Search syntax is FTS5 MATCH (unicode61 tokenizer). Users can pass
single terms, OR-joined terms (`"a OR b"`), or quoted phrases. `?` / `*`
wildcards are passed through. The module deliberately does NOT translate
natural-language questions into SQL — the brief's research questions
(noun phrases) map cleanly to FTS5 MATCH with the default tokenizer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Iterable


# Match kind → FTS5 virtual table + parent table for the JOIN.
# `transcript_search` joins `transcript_version` to resolve video_id
# because `transcript_segment` has no video_id column (audit F-1).
_KIND_TO_FTS = {
    "transcript": "transcript_fts",
    "claim": "claim_fts",
    "concept": "concept_fts",
    "concept_alias": "concept_alias_fts",
}

_VALID_KINDS = frozenset(_KIND_TO_FTS)


@dataclass(frozen=True)
class TranscriptHit:
    video_id: str
    transcript_version_id: str
    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    rank: float


@dataclass(frozen=True)
class ClaimHit:
    claim_id: str
    claim_type: str
    layer: str
    video_id: str
    claim_text: str
    rank: float


@dataclass(frozen=True)
class ConceptHit:
    concept_id: str
    status: str
    canonical_name: str
    definition: str
    rank: float


@dataclass(frozen=True)
class ConceptAliasHit:
    concept_id: str
    source: str
    alias: str
    rank: float


@dataclass
class SearchResult:
    kind: str
    query: str
    total: int
    transcripts: list[TranscriptHit] = field(default_factory=list)
    claims: list[ClaimHit] = field(default_factory=list)
    concepts: list[ConceptHit] = field(default_factory=list)
    aliases: list[ConceptAliasHit] = field(default_factory=list)

    def all(self) -> list:
        """Return all hits flattened in a stable order: transcripts → claims
        → concepts → aliases. Useful for callers that want a single JSON
        array regardless of `kind`."""
        return (list(self.transcripts) + list(self.claims)
                + list(self.concepts) + list(self.aliases))


def _validate_query(query: str) -> str:
    """Strip and reject empty / dangerous queries. FTS5 MATCH can be
    hostile when given unbalanced quotes; refuse rather than raise."""
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    q = query.strip()
    if not q:
        raise ValueError("query must not be empty")
    if q.count('"') % 2 != 0:
        raise ValueError("query has unbalanced double quotes")
    return q


def _rows_as_dicts(cursor, rows) -> list[dict]:
    """Wrap sqlite3 rows as dicts keyed by column name. This decouples
    the helpers from `connection.row_factory` (some callers pass a
    bare `sqlite3.Row` connection; others pass a tuple connection)."""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


def search_transcript(conn, query: str, *, limit: int = 20) -> list[TranscriptHit]:
    """Run a MATCH against `transcript_fts` and resolve `video_id` via JOIN."""
    _validate_query(query)
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cur = conn.execute(
        "SELECT tv.video_id, t.transcript_version_id, t.ordinal,"
        "       t.start_ms, t.end_ms, t.text,"
        "       bm25(transcript_fts) AS rank"
        " FROM transcript_fts t"
        " JOIN transcript_version tv"
        "   ON tv.transcript_version_id = t.transcript_version_id"
        " WHERE transcript_fts MATCH ?"
        " ORDER BY rank LIMIT ?",
        (query, limit))
    rows = _rows_as_dicts(cur, cur.fetchall())
    return [TranscriptHit(
        video_id=r["video_id"],
        transcript_version_id=r["transcript_version_id"],
        ordinal=int(r["ordinal"]),
        start_ms=int(r["start_ms"]),
        end_ms=int(r["end_ms"]),
        text=r["text"],
        rank=float(r["rank"]),
    ) for r in rows]


def search_claim(conn, query: str, *, limit: int = 20) -> list[ClaimHit]:
    """Run a MATCH against `claim_fts` (only `accepted` rows are indexed)."""
    _validate_query(query)
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cur = conn.execute(
        "SELECT claim_id, claim_type, layer, video_id, claim_text,"
        "       bm25(claim_fts) AS rank"
        " FROM claim_fts"
        " WHERE claim_fts MATCH ?"
        " ORDER BY rank LIMIT ?",
        (query, limit))
    rows = _rows_as_dicts(cur, cur.fetchall())
    return [ClaimHit(
        claim_id=r["claim_id"],
        claim_type=r["claim_type"],
        layer=r["layer"],
        video_id=r["video_id"],
        claim_text=r["claim_text"],
        rank=float(r["rank"]),
    ) for r in rows]


def search_concept(conn, query: str, *, limit: int = 20) -> list[ConceptHit]:
    """Run a MATCH against `concept_fts` (proposed + canonical rows)."""
    _validate_query(query)
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cur = conn.execute(
        "SELECT concept_id, status, canonical_name, definition,"
        "       bm25(concept_fts) AS rank"
        " FROM concept_fts"
        " WHERE concept_fts MATCH ?"
        " ORDER BY rank LIMIT ?",
        (query, limit))
    rows = _rows_as_dicts(cur, cur.fetchall())
    return [ConceptHit(
        concept_id=r["concept_id"],
        status=r["status"],
        canonical_name=r["canonical_name"],
        definition=r["definition"] or "",
        rank=float(r["rank"]),
    ) for r in rows]


def search_concept_alias(conn, query: str, *, limit: int = 20) -> list[ConceptAliasHit]:
    """Run a MATCH against `concept_alias_fts`."""
    _validate_query(query)
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cur = conn.execute(
        "SELECT concept_id, source, alias, bm25(concept_alias_fts) AS rank"
        " FROM concept_alias_fts"
        " WHERE concept_alias_fts MATCH ?"
        " ORDER BY rank LIMIT ?",
        (query, limit))
    rows = _rows_as_dicts(cur, cur.fetchall())
    return [ConceptAliasHit(
        concept_id=r["concept_id"],
        source=r["source"] or "",
        alias=r["alias"],
        rank=float(r["rank"]),
    ) for r in rows]


def search(conn, *, kind: str, query: str, limit: int = 20) -> SearchResult:
    """Single entry point used by the `search` CLI subcommand.

    `kind` is one of {transcript, claim, concept, concept_alias,
    all}. `all` runs all four searches and returns a single
    SearchResult with every bucket populated.
    """
    if kind not in _VALID_KINDS and kind != "all":
        raise ValueError(
            f"kind must be one of {sorted(_VALID_KINDS) + ['all']}, got {kind!r}")
    result = SearchResult(kind=kind, query=query, total=0)
    targets: Iterable[str]
    if kind == "all":
        targets = ("transcript", "claim", "concept", "concept_alias")
    else:
        targets = (kind,)
    for t in targets:
        if t == "transcript":
            result.transcripts = search_transcript(conn, query, limit=limit)
            result.total += len(result.transcripts)
        elif t == "claim":
            result.claims = search_claim(conn, query, limit=limit)
            result.total += len(result.claims)
        elif t == "concept":
            result.concepts = search_concept(conn, query, limit=limit)
            result.total += len(result.concepts)
        elif t == "concept_alias":
            result.aliases = search_concept_alias(conn, query, limit=limit)
            result.total += len(result.aliases)
    return result


# Schema-version helper. Tells callers (CLI / status) whether the v4
# substrate is present. The FTS5 tables are part of `_V4_FTS_TABLES`; a
# probe avoids running MATCH against missing tables.

def fts5_installed(conn) -> bool:
    """True if the v4 FTS5 substrate is present (no-op on older schemas)."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type='table' AND name='transcript_fts' LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None
