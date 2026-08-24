"""PR-3 hard validator (brief §9.3).

Each candidate from the model's JSON output is checked against ONE OR MORE
hard rules. A violation produces a `Reject` with `rule_id` and `reason`. A
candidate that passes all applicable rules is accepted; a candidate that
passes most but has a warning goes to `needs_review`.

Brief §9.3 rule → function mapping:

  Rule 1  missing fields                          → `validate_claim_required_fields`
  Rule 2  quote not in segment.text               → `validate_quote_in_segment` (uses houchen_quote)
  Rule 3  segment range out of bounds / / reverse-time → `validate_segment_range`
  Rule 4  layer='speaker_statement' with unknown speaker → `validate_speaker_statement_speaker`
  Rule 5  multi-clause claim (heuristic)          → `validate_claim_atomicity`
  Rule 6  speaker_reasoning edge missing source    → `validate_reasoning_edge_source`
  Rule 7  concept missing concept_source          → `validate_concept_has_source`
  Rule 8  evaluation missing external_evidence    → `validate_evaluation_has_external`
  Rule 9  forecast outcome_condition empty        → `validate_forecast_has_criteria`
  Rule 10 model emitted layer='speaker_statement' → handled at validator entry point

Per-item rejection reasons (brief §9.3 last bullet) are emitted in
`ValidationResult.per_item_rejects` so the prompt can be revised or a
human can re-review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# CRITICAL: this is the ONLY allowed quote-comparison function (brief §8.6).
from houchen_quote import exact_quote_in_segment, normalize_for_compare


# Heuristics for Rule 5 (claim atomicity). Chinese + English causal markers
# that suggest multiple coupled judgments in one claim. If a candidate's
# claim_text contains MORE THAN ONE of these markers (in any combination),
# it is rejected as non-atomic.
_ATOMICITY_MARKERS_CN = re.compile(r"(因为|所以|然而|但是|尽管|虽然|并且|同时|此外)")
_ATOMICITY_MARKERS_EN = re.compile(
    r"\b(because|therefore|however|but|although|though|and also|"
    r"additionally|furthermore|moreover)\b", re.IGNORECASE)
_SENTENCE_TERMINATORS = re.compile(r"[。！？!?；;]")


@dataclass(frozen=True)
class Reject:
    candidate_ref: str
    rule_id: str
    reason: str


@dataclass
class ValidationResult:
    accepted: list[dict] = field(default_factory=list)
    needs_review: list[dict] = field(default_factory=list)
    per_item_rejects: list[Reject] = field(default_factory=list)

    def accepted_count(self) -> int:
        return len(self.accepted)

    def rejected_count(self) -> int:
        return len(self.per_item_rejects)


# ---------------------------------------------------------------------------
# Rule 1 — required fields present
# ---------------------------------------------------------------------------

_CLAIM_REQUIRED = (
    "claim_text", "claim_type", "layer",
    "transcript_version_id", "segment_start_ordinal", "segment_end_ordinal",
    "start_ms", "end_ms", "exact_quote", "timestamp_url", "raw_caption_sha256",
)


def validate_claim_required_fields(claim: dict) -> Reject | None:
    missing = [k for k in _CLAIM_REQUIRED if claim.get(k) in (None, "")]
    if missing:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R1",
            reason=f"missing required field(s): {', '.join(missing)}",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 2 — exact_quote MUST be a substring of the cited segment's text after
# the canonical NFC + whitespace-fold normalization (brief §8.6).
# ---------------------------------------------------------------------------

def validate_quote_in_segment(claim: dict, segment_text: str) -> Reject | None:
    quote = claim.get("exact_quote", "")
    if not quote:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R1",
            reason="exact_quote is empty",
        )
    if not exact_quote_in_segment(quote, segment_text):
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R2",
            reason="exact_quote not found in cited segment text after NFC + whitespace fold",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 3 — segment range must be valid (ordinals in range, end_ms >= start_ms)
# ---------------------------------------------------------------------------

def validate_segment_range(claim: dict, total_segments: int) -> Reject | None:
    start_o = claim.get("segment_start_ordinal")
    end_o = claim.get("segment_end_ordinal")
    start_ms = claim.get("start_ms")
    end_ms = claim.get("end_ms")
    if not (isinstance(start_o, int) and isinstance(end_o, int)
            and isinstance(start_ms, int) and isinstance(end_ms, int)):
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R3",
            reason="segment_ordinals or ms timestamps are not integers",
        )
    if start_o < 0 or end_o < start_o:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R3",
            reason=f"ordinal range invalid (start={start_o}, end={end_o})",
        )
    if end_o >= total_segments:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R3",
            reason=f"segment_end_ordinal {end_o} >= total {total_segments}",
        )
    if end_ms < start_ms:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R3",
            reason=f"end_ms {end_ms} < start_ms {start_ms}",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 4 — layer='speaker_statement' MUST have a known speaker; reject (not
# needs_review).
# ---------------------------------------------------------------------------

def validate_speaker_statement_speaker(claim: dict) -> Reject | None:
    if claim.get("layer") != "speaker_statement":
        return None
    speaker = (claim.get("speaker") or "").strip()
    if not speaker or speaker.lower() in ("unknown", "none", "n/a", "李厚辰?"):
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R4",
            reason="layer='speaker_statement' but speaker is unknown/empty",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 10 — model must NOT emit layer='speaker_statement' (per brief §3.1.5
# / §9.3 last bullet). If a candidate arrives with that layer and the
# validator is invoked in "model-output" mode, it is rejected here rather
# than silently downgraded to speaker_reasoning.
# ---------------------------------------------------------------------------

def validate_no_model_speaker_statement(claim: dict, *, from_model: bool) -> Reject | None:
    if from_model and claim.get("layer") == "speaker_statement":
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R10",
            reason="model output layer='speaker_statement'; only human-curated "
                   "speaker_statements are accepted (brief §3.1.5)",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 5 — claim atomicity heuristic (multi-clause coupling).
# ---------------------------------------------------------------------------

def validate_claim_atomicity(claim: dict) -> Reject | None:
    text = claim.get("claim_text", "") or ""
    cn_hits = len(_ATOMICITY_MARKERS_CN.findall(text))
    en_hits = len(_ATOMICITY_MARKERS_EN.findall(text))
    term_hits = len(_SENTENCE_TERMINATORS.findall(text))
    # Multi-clause if 2+ causal/coupling markers OR 3+ sentence terminators.
    if (cn_hits + en_hits) >= 2 or term_hits >= 3:
        return Reject(
            candidate_ref=f"claim[{claim.get('_index', '?')}]",
            rule_id="R5",
            reason=(f"non-atomic claim ({cn_hits + en_hits} coupling markers, "
                    f"{term_hits} sentence terminators)"),
        )
    return None


# ---------------------------------------------------------------------------
# Rule 6 — speaker_reasoning edge MUST have transcript_version_id + exact_quote.
# ---------------------------------------------------------------------------

def validate_reasoning_edge_source(edge: dict) -> Reject | None:
    if edge.get("layer") != "speaker_reasoning":
        return None
    tv = edge.get("transcript_version_id")
    eq = edge.get("exact_quote")
    if not tv or not eq:
        return Reject(
            candidate_ref=f"edge[{edge.get('_index', '?')}]",
            rule_id="R6",
            reason="speaker_reasoning edge missing transcript_version_id and/or exact_quote",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 7 — concept MUST have at least one concept_source with valid source_role
# when promoted to canonical. Discovered concepts come in as 'proposed' and
# do not require a source; only 'canonical' status does.
# ---------------------------------------------------------------------------

def validate_concept_has_source(concept: dict, *, has_source_row: bool) -> Reject | None:
    if concept.get("status") == "canonical" and not has_source_row:
        return Reject(
            candidate_ref=f"concept[{concept.get('_index', '?')}]",
            rule_id="R7",
            reason="canonical concept missing concept_source row",
        )
    return None


# ---------------------------------------------------------------------------
# Rule 8 — evaluation MUST have external_evidence (publisher + observed_period +
# content_sha256) when evaluator='macro_bridge'.
# ---------------------------------------------------------------------------

def validate_evaluation_has_external(eval_dict: dict, *,
                                    has_external_evidence: bool) -> Reject | None:
    if eval_dict.get("evaluator") == "macro_bridge" and not has_external_evidence:
        return Reject(
            candidate_ref=f"evaluation[{eval_dict.get('_index', '?')}]",
            rule_id="R8",
            reason="macro_bridge evaluation missing external_evidence row",
        )
    evidence = eval_dict.get("external_evidence")
    if eval_dict.get("evaluator") == "macro_bridge" and isinstance(evidence, dict):
        missing = [k for k in ("publisher", "content_sha256", "observed_period")
                   if not evidence.get(k)]
        if missing:
            return Reject(
                candidate_ref=f"evaluation[{eval_dict.get('_index', '?')}]",
                rule_id="R8",
                reason="external_evidence missing " + ", ".join(missing),
            )
    return None


# ---------------------------------------------------------------------------
# Rule 9 — forecast outcome_condition MUST be non-empty and time-bounded.
# ---------------------------------------------------------------------------

def validate_forecast_has_criteria(fcst: dict) -> Reject | None:
    cond = (fcst.get("outcome_condition") or "").strip()
    if not cond:
        return Reject(
            candidate_ref=f"forecast[{fcst.get('_index', '?')}]",
            rule_id="R9",
            reason="forecast outcome_condition is empty",
        )
    if not (fcst.get("time_window_start") or fcst.get("time_window_end")):
        return Reject(
            candidate_ref=f"forecast[{fcst.get('_index', '?')}]",
            rule_id="R9",
            reason="forecast has no time window (start/end)",
        )
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def validate_claim(claim: dict, *, segments_by_ordinal: dict,
                   from_model: bool) -> Reject | None:
    """Run Rules 1–5 + 10 in order; return the first failing reject or None.

    `segments_by_ordinal` maps ordinal (int) → segment dict (must contain
    `text`, `start_ms`, `end_ms`). The validator never raises on a single
    bad candidate; it returns a `Reject` and the orchestrator moves on.
    """
    idx = claim.get("_index", "?")
    for fn in (
        lambda: validate_claim_required_fields(claim),
        lambda: validate_no_model_speaker_statement(claim, from_model=from_model),
        lambda: validate_speaker_statement_speaker(claim),
        lambda: validate_claim_atomicity(claim),
        lambda: _rule3_then_2_then_segment_quote(claim, segments_by_ordinal, idx),
    ):
        r = fn()
        if r is not None:
            return r
    return None


def _rule3_then_2_then_segment_quote(claim: dict, segments_by_ordinal: dict,
                                     idx) -> Reject | None:
    # Rule 3 needs total_segments; pull it from the dict's max ordinal+1.
    total = (max(segments_by_ordinal.keys()) + 1) if segments_by_ordinal else 0
    r = validate_segment_range(claim, total)
    if r is not None:
        return r
    # Resolve the segment text by start ordinal; if missing → R1 (treat as
    # missing field; the segment range was nominally valid).
    text = segments_by_ordinal.get(claim.get("segment_start_ordinal"), {}).get("text", "")
    if not text:
        return Reject(
            candidate_ref=f"claim[{idx}]",
            rule_id="R1",
            reason="referenced segment text not found in transcript_version",
        )
    return validate_quote_in_segment(claim, text)


def validate_candidate_bundle(candidates: dict, *,
                              segments_by_ordinal: dict,
                              from_model: bool = True
                              ) -> ValidationResult:
    """Validate a model-output bundle end-to-end.

    `candidates` is the parsed JSON from the provider; it MUST contain
    keys 'claims', 'concept_links', 'proposed_concepts', 'reasoning_edges',
    'evidence_mentions', 'forecast_candidates' (per
    `houchen_prompt.analysis_input_json_schema`). Missing keys are tolerated
    as empty lists; a missing 'claims' key is an R1 rejection on every
    implicit empty claim (none in practice).
    """
    result = ValidationResult()
    claims = candidates.get("claims") or []
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            result.per_item_rejects.append(Reject(
                candidate_ref=f"claim[{i}]", rule_id="R1",
                reason="claim is not a JSON object"))
            continue
        claim = dict(claim)
        claim["_index"] = i
        r = validate_claim(claim, segments_by_ordinal=segments_by_ordinal,
                           from_model=from_model)
        if r is None:
            result.accepted.append(claim)
        else:
            result.per_item_rejects.append(r)
    # Concepts: a model may only submit proposed concepts by default. If it
    # asks for canonical state, it must include a backing concept_source.
    for i, concept in enumerate(candidates.get("proposed_concepts") or []):
        if not isinstance(concept, dict):
            result.per_item_rejects.append(Reject(
                candidate_ref=f"concept[{i}]", rule_id="R7",
                reason="concept is not a JSON object"))
            continue
        concept = dict(concept)
        concept["_index"] = i
        r = validate_concept_has_source(
            concept, has_source_row=bool(concept.get("concept_source")))
        if r is None:
            result.accepted.append(concept)
        else:
            result.per_item_rejects.append(r)
    # Evaluations are optional in v1's response schema, but validate them if
    # a provider supplies them. Macro-bridge never receives a free pass.
    for i, evaluation in enumerate(candidates.get("evaluations") or []):
        if not isinstance(evaluation, dict):
            result.per_item_rejects.append(Reject(
                candidate_ref=f"evaluation[{i}]", rule_id="R8",
                reason="evaluation is not a JSON object"))
            continue
        evaluation = dict(evaluation)
        evaluation["_index"] = i
        evidence = evaluation.get("external_evidence")
        r = validate_evaluation_has_external(
            evaluation, has_external_evidence=bool(evidence))
        if r is None:
            result.accepted.append(evaluation)
        else:
            result.per_item_rejects.append(r)
    # Reasoning edges: validate each.
    for i, edge in enumerate(candidates.get("reasoning_edges") or []):
        if not isinstance(edge, dict):
            result.per_item_rejects.append(Reject(
                candidate_ref=f"edge[{i}]", rule_id="R6",
                reason="edge is not a JSON object"))
            continue
        edge = dict(edge)
        edge["_index"] = i
        r = validate_reasoning_edge_source(edge)
        if r is None:
            result.accepted.append(edge)  # non-claim accepted items share list
        else:
            result.per_item_rejects.append(r)
    # Forecast candidates.
    for i, fcst in enumerate(candidates.get("forecast_candidates") or []):
        if not isinstance(fcst, dict):
            result.per_item_rejects.append(Reject(
                candidate_ref=f"forecast[{i}]", rule_id="R9",
                reason="forecast is not a JSON object"))
            continue
        fcst = dict(fcst)
        fcst["_index"] = i
        r = validate_forecast_has_criteria(fcst)
        if r is None:
            result.accepted.append(fcst)
        else:
            result.per_item_rejects.append(r)
    return result