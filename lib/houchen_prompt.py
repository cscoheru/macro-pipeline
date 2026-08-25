"""PR-3 prompt + JSON schema templates (brief §9.1 / §9.2).

A single, versioned source of truth for:

  - The canonical analysis INPUT bundle (content-addressed, deterministic).
  - The JSON Schema the model output MUST conform to before validation.

The input bundle is the deterministic payload sent to the model provider;
its SHA-256 is the idempotency key. The JSON schema describes the CANDIDATE
shape — atomic claims, concept links, proposed concepts, reasoning edges,
evidence mentions, forecast candidates, and per-item rejection reasons
(brief §9.2 last bullet). After the model returns, the hard validator in
`lib/houchen_validator.py` enforces brief §9.3.

Forbidden in the input: API keys, cookies, signed URLs, full model responses,
user-specific identifiers. The bundle is research-library-internal data only.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

PROMPT_VERSION = "2026-08-25.2"
SCHEMA_VERSION = "claim_extraction_v1"


# Brief §7.2 — domain skeleton (audit F-1: SEVEN entries, not six).
DEFAULT_DOMAIN_SKELETON = [
    {"slug": "political_economy",  "name": "政治经济与分配"},
    {"slug": "state_governance",   "name": "国家、央地关系与治理"},
    {"slug": "society_psychology", "name": "社会结构、群体心理与行动"},
    {"slug": "international_order","name": "国际秩序与地缘政治"},
    {"slug": "technology_ai",      "name": "技术、平台与人工智能"},
    {"slug": "history_interpretation", "name": "历史解释"},
    {"slug": "method_media",       "name": "方法论、知识生产与媒体"},
]


def build_analysis_input(*, video_id: str, transcript_version_id: str,
                         transcript_version_sha: str,
                         segments: list[dict],
                         domain_skeleton: list[dict] | None = None,
                         prompt_version: str = PROMPT_VERSION,
                         schema_version: str = SCHEMA_VERSION,
                         model: str = "",
                         provider: str = "",
                         raw_caption_sha256: str = "") -> dict:
    """Construct the canonical analysis INPUT bundle.

    `segments` is the verbatim list of `transcript_segment` rows (ordinal,
    start_ms, end_ms, text, raw_cue_start, raw_cue_end, speaker). The bundle
    embeds the segment text directly — the model needs the text, and
    re-fetching would risk drift.
    """
    if not video_id or not transcript_version_id:
        raise ValueError("video_id and transcript_version_id are required")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list of segment dicts")
    return {
        "schema": "houchen/analysis_input/v1",
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "video_id": video_id,
        "transcript_version_id": transcript_version_id,
        "transcript_version_sha": transcript_version_sha,
        "raw_caption_sha256": raw_caption_sha256,
        "domain_skeleton": list(domain_skeleton) if domain_skeleton is not None
                          else list(DEFAULT_DOMAIN_SKELETON),
        "model": model,
        "provider": provider,
        "segments": [
            {
                "ordinal": s["ordinal"],
                "start_ms": s["start_ms"],
                "end_ms": s["end_ms"],
                "text": s["text"],
                "raw_cue_start": s.get("raw_cue_start"),
                "raw_cue_end": s.get("raw_cue_end"),
                "speaker": s.get("speaker"),
            } for s in segments
        ],
    }


def input_sha256(payload: dict) -> str:
    """Content-addressed SHA-256 of the canonical input bundle.

    Uses `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
    so two builds with the same logical content produce the same digest. This
    is the idempotency key for `analysis_input_path`.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def serialize_input(payload: dict) -> bytes:
    """Canonical bytes form used for both SHA computation and disk write."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def analysis_prompt_path() -> str:
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "config", "houchen_analysis_prompt.md")


def load_analysis_prompt_and_schema() -> tuple[str, dict, str]:
    """Load houchen analysis prompt + JSON schema (not macro insight files)."""
    with open(analysis_prompt_path(), encoding="utf-8") as fh:
        prompt = fh.read()
    schema = analysis_input_json_schema()
    version = hashlib.sha256(
        serialize_input({"prompt": prompt, "schema": schema})
    ).hexdigest()[:16]
    return prompt, schema, version


def analysis_input_json_schema() -> dict:
    """The JSON Schema the model's response must conform to (brief §9.2).

    All fields the validator cares about are listed; the validator does
    additional structural / quote checks on top of this schema.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "houchen.claim_extraction.v1",
        "type": "object",
        "required": ["claims", "concept_links", "proposed_concepts",
                     "reasoning_edges", "evidence_mentions",
                     "forecast_candidates", "rejection_reasons"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {"$ref": "#/$defs/claim_candidate"},
            },
            "concept_links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["candidate_claim_index", "concept_canonical_name",
                                 "relation"],
                    "properties": {
                        "candidate_claim_index": {"type": "integer"},
                        "concept_canonical_name": {"type": "string"},
                        "relation": {"type": "string",
                                      "enum": ["defines", "uses",
                                               "exemplifies", "qualifies",
                                               "relates"]},
                    },
                },
            },
            "proposed_concepts": {
                "type": "array",
                "items": {"$ref": "#/$defs/concept_candidate"},
            },
            "reasoning_edges": {
                "type": "array",
                "items": {"$ref": "#/$defs/reasoning_edge_candidate"},
            },
            "evidence_mentions": {
                "type": "array",
                "items": {"$ref": "#/$defs/evidence_mention_candidate"},
            },
            "forecast_candidates": {
                "type": "array",
                "items": {"$ref": "#/$defs/forecast_candidate"},
            },
            "rejection_reasons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["candidate_ref", "rule_id", "reason"],
                    "properties": {
                        "candidate_ref": {"type": "string"},
                        "rule_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
        "$defs": {
            "claim_candidate": {
                "type": "object",
                "required": ["claim_text", "claim_type", "layer",
                             "transcript_version_id", "segment_start_ordinal",
                             "segment_end_ordinal", "start_ms", "end_ms",
                             "exact_quote", "timestamp_url",
                             "raw_caption_sha256"],
                "properties": {
                    "claim_text": {"type": "string", "minLength": 1},
                    "claim_type": {"type": "string",
                                   "enum": ["definition", "descriptive",
                                            "causal", "predictive",
                                            "normative", "interpretive"]},
                    "speaker": {"type": ["string", "null"]},
                    "layer": {"type": "string",
                              "enum": ["speaker_reasoning",
                                       "system_evaluation"]},
                    "temporal_scope": {"type": ["string", "null"]},
                    "modality": {"type": ["string", "null"]},
                    "transcript_version_id": {"type": "string"},
                    "segment_start_ordinal": {"type": "integer", "minimum": 0},
                    "segment_end_ordinal": {"type": "integer", "minimum": 0},
                    "start_ms": {"type": "integer", "minimum": 0},
                    "end_ms": {"type": "integer", "minimum": 0},
                    "exact_quote": {"type": "string", "minLength": 1},
                    "timestamp_url": {"type": "string", "minLength": 1},
                    "raw_caption_sha256": {"type": "string"},
                },
            },
            "concept_candidate": {
                "type": "object",
                "required": ["canonical_name", "definition",
                             "domain_slugs", "first_segment_ordinal",
                             "first_start_ms", "first_end_ms",
                             "first_exact_quote", "first_timestamp_url",
                             "first_raw_caption_sha256"],
                "properties": {
                    "canonical_name": {"type": "string", "minLength": 1},
                    "definition": {"type": "string"},
                    "domain_slugs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "first_segment_ordinal": {"type": "integer", "minimum": 0},
                    "first_start_ms": {"type": "integer", "minimum": 0},
                    "first_end_ms": {"type": "integer", "minimum": 0},
                    "first_exact_quote": {"type": "string", "minLength": 1},
                    "first_timestamp_url": {"type": "string", "minLength": 1},
                    "first_raw_caption_sha256": {"type": "string"},
                },
            },
            "reasoning_edge_candidate": {
                "type": "object",
                "required": ["from_claim_index", "to_claim_index",
                             "relation", "layer"],
                "properties": {
                    "from_claim_index": {"type": "integer"},
                    "to_claim_index": {"type": "integer"},
                    "relation": {"type": "string",
                                  "enum": ["supports", "causes", "qualifies",
                                           "contradicts", "predicts",
                                           "defines", "exemplifies"]},
                    "layer": {"type": "string",
                              "enum": ["speaker_reasoning",
                                       "system_evaluation"]},
                    "transcript_version_id": {"type": ["string", "null"]},
                    "exact_quote": {"type": ["string", "null"]},
                    "start_ms": {"type": ["integer", "null"]},
                    "end_ms": {"type": ["integer", "null"]},
                    "timestamp_url": {"type": ["string", "null"]},
                },
            },
            "evidence_mention_candidate": {
                "type": "object",
                "required": ["transcript_version_id", "segment_ordinal",
                             "text", "mention_type"],
                "properties": {
                    "transcript_version_id": {"type": "string"},
                    "segment_ordinal": {"type": "integer", "minimum": 0},
                    "text": {"type": "string", "minLength": 1},
                    "mention_type": {"type": "string",
                                      "enum": ["data", "example", "analogy",
                                               "reference", "quote_external"]},
                    "external_entity_candidate": {"type": ["string", "null"]},
                },
            },
            "forecast_candidate": {
                "type": "object",
                "required": ["for_claim_index", "outcome_condition"],
                "properties": {
                    "for_claim_index": {"type": "integer"},
                    "time_window_start": {"type": ["string", "null"]},
                    "time_window_end": {"type": ["string", "null"]},
                    "outcome_condition": {"type": "string", "minLength": 1},
                },
            },
        },
    }