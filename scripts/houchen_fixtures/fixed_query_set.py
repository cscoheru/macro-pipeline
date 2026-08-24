"""PR-4 Phase 0 — fixed FTS5 query benchmark (brief §10).

The brief's §10 research questions map to a small, frozen set of
Chinese + English queries. The set is the gate that any future change
to the tokenizer / schema must pass. It is intentionally tiny and
deterministic; it is NOT a recall benchmark for production FTS
relevance.

Each entry is a tuple `(kind, query, min_hits, label)`:

  - `kind` ∈ {transcript, claim, concept, concept_alias}
  - `query` is the FTS5 MATCH expression
  - `min_hits` is the minimum number of rows the corpus must return for
    a passing test on the canonical fixture. The fixture script
    `test_houchen_search.py` builds a deterministic corpus, seeds
    matching rows, and asserts each query yields ≥ `min_hits` hits.
  - `label` is a human-readable name (printed on assertion failure).
"""
from __future__ import annotations

# A non-empty minimum is required (FTS5 MATCH of an empty string raises).
# `min_hits=0` is allowed for queries that intentionally return zero
# rows in the canonical fixture.
FIXED_QUERY_SET = [
    # transcript_fts queries (trigram tokenizer needs ≥3 chars per token)
    ("transcript", "中央财政", 1, "transcript: 中央财政"),
    ("transcript", "地方政府", 1, "transcript: 地方政府"),
    ("transcript", "基础设施", 1, "transcript: 基础设施"),
    ("transcript", "中央财政 OR 地方政府", 2, "transcript: 中央财政 OR 地方政府"),
    # claim_fts queries (only `accepted` rows are indexed)
    ("claim", "财政扩张", 1, "claim: 财政扩张"),
    ("claim", "基础设施", 1, "claim: 基础设施投资"),
    # concept_fts queries (canonical_name / definition)
    ("concept", "财政转移", 1, "concept: 财政转移"),
    ("concept", "权力下放", 1, "concept: 权力下放"),
    # concept_alias_fts queries
    ("concept_alias", "转移支付", 1, "alias: 转移支付"),
    ("concept_alias", "央地分权", 1, "alias: 央地分权"),
]


def all_queries():
    return list(FIXED_QUERY_SET)
