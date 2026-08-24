"""Fake model provider for the PR-3 analyzer.

Returns deterministic candidate bundles keyed by the analysis INPUT
SHA-256 (so two runs on the same input bundle produce byte-identical
candidates, which the validator can replay idempotently).

In real life, model output is variable; the fake mimics that by including
both well-formed candidates (accepted by the hard validator) AND
candidates that violate specific brief §9.3 rules (rejected, with
reasons), so the validator test suite can prove every rule fires.

The fake provider is invoked ONLY from `lib/houchen_analyzer.call_provider`
when `provider='fake'`. It does NOT touch the network, disk, or any
config/insight.env file (audit F-6 — research and macro-insight namespaces
are independent).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


# Deterministic seed phrases; tuned to pass brief §9.3 Rules 1–5 + 9.
_WELL_FORMED_CLAIM = {
    "claim_text": "中央财政需扩大对地方转移支付的力度。",
    "claim_type": "normative",
    "speaker": "李厚辰",
    "layer": "speaker_reasoning",  # model output may not be speaker_statement (Rule 10)
    "temporal_scope": "2024-2026",
    "modality": "should",
    "transcript_version_id": "__TV_ID__",
    "segment_start_ordinal": 0,
    "segment_end_ordinal": 0,
    "start_ms": 0,
    "end_ms": 1000,
    "exact_quote": "__SEGMENT_TEXT__",
    "timestamp_url": "https://www.youtube.com/watch?v=__VIDEO_ID__&t=0s",
    "raw_caption_sha256": "__RAW_SHA__",
}

# This candidate has a multi-clause claim (because + 所以) — Rule 5 reject.
_MULTI_CLAUSE_CLAIM = dict(_WELL_FORMED_CLAIM)
_MULTI_CLAUSE_CLAIM["claim_text"] = "因为中央财政紧缩，所以地方政府必须自行举债，但是现行法律不允许。"

# This candidate has an exact_quote that's a 1-character mismatch with the
# segment text — Rule 2 reject.
_QUOTE_MISMATCH_CLAIM = dict(_WELL_FORMED_CLAIM)
_QUOTE_MISMATCH_CLAIM["exact_quote"] = "__SEGMENT_TEXT_MANGLED__"


def fake_analyze(input_payload: dict) -> dict[str, Any]:
    """Build a deterministic candidate bundle for the given input.

    Rules of the fake:
      - ALWAYS emit at least one accepted claim.
      - If the input has 2+ segments, also emit one Rule-2 reject candidate
        (quote-mismatch) so the validator can prove Rule 2 fires.
      - Always emit one Rule-5 reject (multi-clause claim).
      - Always emit one forecast candidate (well-formed, accepted).
      - Always emit one well-formed concept candidate.
    """
    seg0 = input_payload.get("segments") or [{}]
    seg0_text = seg0[0].get("text", "好")
    tv_id = input_payload.get("transcript_version_id", "hctv_placeholder")
    video_id = input_payload.get("video_id", "aaaaaaaaaaa")
    raw_sha = (seg0[0].get("raw_cue_start") and
               "f" * 64) or ("a" * 64)

    accepted_claim = _fill_template(_WELL_FORMED_CLAIM, seg0_text,
                                     tv_id, video_id, raw_sha)
    multi_clause = _fill_template(_MULTI_CLAUSE_CLAIM, seg0_text,
                                  tv_id, video_id, raw_sha)
    quote_mismatch = _fill_template(_QUOTE_MISMATCH_CLAIM, seg0_text + "X",
                                    tv_id, video_id, raw_sha)

    bundle: dict[str, Any] = {
        "claims": [accepted_claim, multi_clause, quote_mismatch],
        "concept_links": [
            {"candidate_claim_index": 0,
             "concept_canonical_name": "中央财政",
             "relation": "defines"},
        ],
        "proposed_concepts": [
            {"canonical_name": "地方财政自主权",
             "definition": "地方政府在财政收支上的决策权限。",
             "domain_slugs": ["political_economy", "state_governance"],
             "first_segment_ordinal": 0,
             "first_start_ms": 0, "first_end_ms": 1000,
             "first_exact_quote": seg0_text,
             "first_timestamp_url":
                 f"https://www.youtube.com/watch?v={video_id}&t=0s",
             "first_raw_caption_sha256": raw_sha},
        ],
        "reasoning_edges": [],
        "evidence_mentions": [
            {"transcript_version_id": tv_id,
             "segment_ordinal": 0,
             "text": seg0_text,
             "mention_type": "quote_external",
             "external_entity_candidate": None},
        ],
        "forecast_candidates": [
            {"for_claim_index": 0,
             "time_window_start": "2025-01",
             "time_window_end": "2026-12",
             "outcome_condition": "中央对地方转移支付同比增长不低于 5%。"},
        ],
        "rejection_reasons": [],  # validator records its own reasons
    }
    # Sort keys deterministically (mirrors content-addressing).
    bundle = json.loads(json.dumps(bundle, sort_keys=True, ensure_ascii=False))
    return bundle


def _fill_template(template: dict, segment_text: str, tv_id: str,
                   video_id: str, raw_sha: str) -> dict:
    out = dict(template)
    out["transcript_version_id"] = tv_id
    out["exact_quote"] = template["exact_quote"].replace("__SEGMENT_TEXT__", segment_text)
    out["exact_quote"] = out["exact_quote"].replace(
        "__SEGMENT_TEXT_MANGLED__", segment_text + "X")
    out["timestamp_url"] = template["timestamp_url"].replace(
        "__VIDEO_ID__", video_id)
    out["raw_caption_sha256"] = raw_sha
    return out