"""PR-3 validator tests (brief §9.3 — all 10 rules).

Each brief §9.3 rule gets at least one positive and one negative case. The
validator is a pure function: feed it a candidate dict + segments_by_ordinal,
assert the resulting `Reject.rule_id` matches expectations.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import houchen_validator as hv  # noqa: E402


# Reusable fixtures.

_SEG_TEXT = "中央财政需要扩大对地方转移支付的力度。"
_SEGMENTS = {0: {"ordinal": 0, "text": _SEG_TEXT, "start_ms": 0, "end_ms": 5000}}


def _ok_claim(idx: int = 0, **overrides) -> dict:
    c = {
        "claim_text": "中央财政需扩大对地方转移支付的力度。",
        "claim_type": "normative",
        "speaker": "李厚辰",
        "layer": "speaker_reasoning",  # model can only emit reasoning / eval
        "temporal_scope": "2024-2026",
        "modality": "should",
        "transcript_version_id": "hctv_test",
        "segment_start_ordinal": 0,
        "segment_end_ordinal": 0,
        "start_ms": 0,
        "end_ms": 5000,
        "exact_quote": _SEG_TEXT,
        "timestamp_url": "https://www.youtube.com/watch?v=aaaaaaaaaaaa&t=0s",
        "raw_caption_sha256": "f" * 64,
    }
    c.update(overrides)
    c["_index"] = idx
    return c


def _bundle_with(claims=None, reasoning_edges=None, forecasts=None) -> dict:
    return {
        "claims": claims or [],
        "concept_links": [],
        "proposed_concepts": [],
        "reasoning_edges": reasoning_edges or [],
        "evidence_mentions": [],
        "forecast_candidates": forecasts or [],
    }


# ---------------------------------------------------------------------------
# Rule 1 — required fields present
# ---------------------------------------------------------------------------

class TestRule1RequiredFields(unittest.TestCase):
    def test_positive_all_fields_present(self):
        claim = _ok_claim()
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.per_item_rejects), 0)

    def test_negative_missing_exact_quote(self):
        claim = _ok_claim()
        claim.pop("exact_quote")
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R1")
        self.assertIn("exact_quote", result.per_item_rejects[0].reason)


# ---------------------------------------------------------------------------
# Rule 2 — exact_quote must be a substring of the cited segment after NFC +
# whitespace fold (brief §8.6 hard gate)
# ---------------------------------------------------------------------------

class TestRule2QuoteInSegment(unittest.TestCase):
    def test_positive_quote_is_substring(self):
        claim = _ok_claim()
        claim["exact_quote"] = _SEG_TEXT[:6]  # "中央财政"
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)

    def test_negative_quote_mismatch_one_char(self):
        claim = _ok_claim()
        claim["exact_quote"] = _SEG_TEXT + "X"  # extra char → not a substring
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R2")


# ---------------------------------------------------------------------------
# Rule 3 — segment range out of bounds / reverse-time
# ---------------------------------------------------------------------------

class TestRule3SegmentRange(unittest.TestCase):
    def test_positive_in_bounds(self):
        claim = _ok_claim()
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)

    def test_negative_end_ordinal_out_of_range(self):
        claim = _ok_claim(segment_end_ordinal=5)  # only 1 segment exists
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R3")

    def test_negative_end_ms_less_than_start_ms(self):
        claim = _ok_claim(start_ms=5000, end_ms=1000)
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R3")


# ---------------------------------------------------------------------------
# Rule 4 — layer='speaker_statement' with unknown speaker → reject (NOT
# needs_review; brief §3.1.5 / §9.3)
# ---------------------------------------------------------------------------

class TestRule4SpeakerStatementSpeaker(unittest.TestCase):
    def test_positive_known_speaker(self):
        claim = _ok_claim(layer="speaker_statement", speaker="李厚辰")
        # Bypass Rule 10 by passing from_model=False (simulating a
        # human-curated speaker_statement).
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=False)
        self.assertEqual(len(result.accepted), 1)

    def test_negative_unknown_speaker(self):
        claim = _ok_claim(layer="speaker_statement", speaker=None)
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=False)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R4")


# ---------------------------------------------------------------------------
# Rule 5 — multi-clause atomicity heuristic
# ---------------------------------------------------------------------------

class TestRule5Atomicity(unittest.TestCase):
    def test_positive_single_clause(self):
        claim = _ok_claim()
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)

    def test_negative_multi_coupling_markers(self):
        claim = _ok_claim(claim_text="因为财政紧缩，所以地方政府必须自行举债，但是法律不允许。")
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R5")


# ---------------------------------------------------------------------------
# Rule 6 — speaker_reasoning edge MUST have transcript_version_id +
# exact_quote
# ---------------------------------------------------------------------------

class TestRule6ReasoningEdgeSource(unittest.TestCase):
    def test_positive_edge_with_source(self):
        edge = {
            "layer": "speaker_reasoning",
            "transcript_version_id": "hctv_test",
            "exact_quote": _SEG_TEXT,
            "_index": 0,
        }
        result = hv.validate_candidate_bundle(
            _bundle_with(reasoning_edges=[edge]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)

    def test_negative_edge_missing_source(self):
        edge = {
            "layer": "speaker_reasoning",
            "transcript_version_id": None,
            "exact_quote": None,
            "_index": 0,
        }
        result = hv.validate_candidate_bundle(
            _bundle_with(reasoning_edges=[edge]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R6")


# ---------------------------------------------------------------------------
# Rule 7 — concept promoted to canonical MUST have a concept_source row
# ---------------------------------------------------------------------------

class TestRule7ConceptSource(unittest.TestCase):
    def test_positive_canonical_with_source(self):
        concept = {"status": "canonical", "_index": 0}
        # Function signature: (concept, has_source_row)
        r = hv.validate_concept_has_source(concept, has_source_row=True)
        self.assertIsNone(r)

    def test_negative_canonical_without_source(self):
        concept = {"status": "canonical", "_index": 0}
        r = hv.validate_concept_has_source(concept, has_source_row=False)
        self.assertIsNotNone(r)
        self.assertEqual(r.rule_id, "R7")

    def test_proposed_without_source_is_ok(self):
        concept = {"status": "proposed", "_index": 0}
        r = hv.validate_concept_has_source(concept, has_source_row=False)
        self.assertIsNone(r)


# ---------------------------------------------------------------------------
# Rule 8 — evaluation MUST have external_evidence when evaluator='macro_bridge'
# ---------------------------------------------------------------------------

class TestRule8EvaluationExternalEvidence(unittest.TestCase):
    def test_positive_macro_bridge_with_evidence(self):
        ev = {"evaluator": "macro_bridge", "_index": 0}
        r = hv.validate_evaluation_has_external(ev, has_external_evidence=True)
        self.assertIsNone(r)

    def test_negative_macro_bridge_without_evidence(self):
        ev = {"evaluator": "macro_bridge", "_index": 0}
        r = hv.validate_evaluation_has_external(ev, has_external_evidence=False)
        self.assertIsNotNone(r)
        self.assertEqual(r.rule_id, "R8")

    def test_human_evaluator_does_not_require_evidence(self):
        ev = {"evaluator": "human", "_index": 0}
        r = hv.validate_evaluation_has_external(ev, has_external_evidence=False)
        self.assertIsNone(r)

    def test_negative_external_evidence_missing_required_fields(self):
        ev = {
            "evaluator": "macro_bridge", "_index": 0,
            "external_evidence": {"publisher": "FRED"},
        }
        r = hv.validate_evaluation_has_external(ev, has_external_evidence=True)
        self.assertIsNotNone(r)
        self.assertEqual(r.rule_id, "R8")
        self.assertIn("content_sha256", r.reason)


# ---------------------------------------------------------------------------
# Rule 9 — forecast outcome_condition MUST be non-empty + time-bounded
# ---------------------------------------------------------------------------

class TestRule9ForecastCriteria(unittest.TestCase):
    def test_positive_forecast_with_condition_and_window(self):
        fcst = {
            "outcome_condition": "中央对地方转移支付同比增长不低于 5%",
            "time_window_start": "2025-01",
            "time_window_end": "2026-12",
            "_index": 0,
        }
        r = hv.validate_forecast_has_criteria(fcst)
        self.assertIsNone(r)

    def test_negative_empty_condition(self):
        fcst = {
            "outcome_condition": "",
            "time_window_start": "2025-01",
            "time_window_end": "2026-12",
            "_index": 0,
        }
        r = hv.validate_forecast_has_criteria(fcst)
        self.assertIsNotNone(r)
        self.assertEqual(r.rule_id, "R9")

    def test_negative_no_time_window(self):
        fcst = {
            "outcome_condition": "some outcome",
            "time_window_start": None,
            "time_window_end": None,
            "_index": 0,
        }
        r = hv.validate_forecast_has_criteria(fcst)
        self.assertIsNotNone(r)
        self.assertEqual(r.rule_id, "R9")


# ---------------------------------------------------------------------------
# Rule 10 — model must NOT emit layer='speaker_statement'
# ---------------------------------------------------------------------------

class TestRule10NoModelSpeakerStatement(unittest.TestCase):
    def test_negative_model_emits_speaker_statement(self):
        claim = _ok_claim(layer="speaker_statement", speaker="李厚辰")
        # from_model=True must reject even when speaker is known.
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R10")

    def test_positive_human_speaker_statement_is_accepted(self):
        # Same layer, but from_model=False → allowed (human-curated).
        claim = _ok_claim(layer="speaker_statement", speaker="李厚辰")
        result = hv.validate_candidate_bundle(
            _bundle_with(claims=[claim]),
            segments_by_ordinal=_SEGMENTS, from_model=False)
        self.assertEqual(len(result.accepted), 1)


# ---------------------------------------------------------------------------
# Bundle-level integration: fake_provider-style mix
# ---------------------------------------------------------------------------

class TestBundleAcceptanceAndRejection(unittest.TestCase):
    def test_accepted_and_rejected_kept_separate(self):
        accepted = _ok_claim()
        rejected = _ok_claim(claim_text="因为A，所以B，但是C。", idx=1)
        bundle = _bundle_with(claims=[accepted, rejected])
        result = hv.validate_candidate_bundle(
            bundle, segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R5")

    def test_non_dict_claim_rejected_as_R1(self):
        bundle = _bundle_with(claims=["not a dict"])  # type: ignore[list-item]
        result = hv.validate_candidate_bundle(
            bundle, segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(len(result.per_item_rejects), 1)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R1")

    def test_bundle_rejects_model_canonical_concept_without_source(self):
        bundle = _bundle_with()
        bundle["proposed_concepts"] = [{"status": "canonical"}]
        result = hv.validate_candidate_bundle(
            bundle, segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R7")

    def test_bundle_rejects_macro_bridge_without_evidence(self):
        bundle = _bundle_with()
        bundle["evaluations"] = [{"evaluator": "macro_bridge"}]
        result = hv.validate_candidate_bundle(
            bundle, segments_by_ordinal=_SEGMENTS, from_model=True)
        self.assertEqual(result.per_item_rejects[0].rule_id, "R8")


if __name__ == "__main__":
    unittest.main()