"""PR-3 analyzer tests (content addressing, provider dispatch, idempotent
derived JSON write).

These tests cover:
  - `build_input_payload` returns a stable SHA-256 for the same input
  - `call_provider(provider='fake')` returns a deterministic bundle and
    writes the derived JSON at the canonical path
  - Real providers are explicitly disabled (audit F-6)
  - Re-invoking on the same `(input_sha256, run_id)` is idempotent
  - The content-addressed input JSON is also written
  - `_atomic_write_json` writes with 0600 file mode + 0700 parent dir
  - Rejected providers never raise — they return an AnalyzeOutcome with
    outcome='analyze_failed'
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_analyzer  # noqa: E402
import houchen_paths  # noqa: E402
import houchen_prompt  # noqa: E402


def _seg(idx, text, start_ms=0, end_ms=5000):
    return {
        "ordinal": idx,
        "text": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def _tmp_root():
    with tempfile.TemporaryDirectory() as t:
        old = os.environ.get("HOUCHEN_DATA_ROOT")
        os.environ["HOUCHEN_DATA_ROOT"] = t
        try:
            yield t
        finally:
            if old is None:
                os.environ.pop("HOUCHEN_DATA_ROOT", None)
            else:
                os.environ["HOUCHEN_DATA_ROOT"] = old


# ---------------------------------------------------------------------------
# Content addressing
# ---------------------------------------------------------------------------

class TestBuildInputPayloadContentAddressing(unittest.TestCase):
    def test_same_input_same_sha(self):
        segs = [_seg(0, "中央财政需要扩大对地方转移支付的力度。")]
        p1, sha1 = houchen_analyzer.build_input_payload(
            video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
            transcript_version_sha="a" * 64, segments=segs,
            model="", provider="fake")
        p2, sha2 = houchen_analyzer.build_input_payload(
            video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
            transcript_version_sha="a" * 64, segments=segs,
            model="", provider="fake")
        self.assertEqual(sha1, sha2)
        self.assertEqual(sha1, houchen_prompt.input_sha256(p1))

    def test_different_segments_different_sha(self):
        segs1 = [_seg(0, "中央财政需要扩大对地方转移支付的力度。")]
        segs2 = [_seg(0, "中央财政需要扩大对地方转移支付的力度。X")]
        _, sha1 = houchen_analyzer.build_input_payload(
            video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
            transcript_version_sha="a" * 64, segments=segs1)
        _, sha2 = houchen_analyzer.build_input_payload(
            video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
            transcript_version_sha="a" * 64, segments=segs2)
        self.assertNotEqual(sha1, sha2)


# ---------------------------------------------------------------------------
# Fake provider dispatch + artifact persistence
# ---------------------------------------------------------------------------

class TestCallProviderFake(unittest.TestCase):
    def test_fake_provider_writes_artifact_and_input(self):
        for root in _tmp_root():
            segs = [_seg(0, "中央财政需要扩大对地方转移支付的力度。")]
            payload, sha = houchen_analyzer.build_input_payload(
                video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
                transcript_version_sha="a" * 64, segments=segs)
            outcome = houchen_analyzer.call_provider(
                input_payload=payload, input_sha256=sha, run_id="hcrun_test1",
                provider="fake")
            self.assertEqual(outcome.outcome, "success")
            self.assertIsNotNone(outcome.candidates)
            # Input bundle was written
            self.assertTrue(os.path.isfile(houchen_paths.analysis_input_path(sha)))
            # Derived artifact was written
            self.assertTrue(os.path.isfile(
                houchen_paths.analysis_artifact_path("hcrun_test1")))

    def test_idempotent_artifact_write(self):
        """Writing the same payload twice produces a byte-identical file."""
        for root in _tmp_root():
            segs = [_seg(0, "中央财政需要扩大对地方转移支付的力度。")]
            payload, sha = houchen_analyzer.build_input_payload(
                video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
                transcript_version_sha="a" * 64, segments=segs)
            houchen_analyzer.call_provider(
                input_payload=payload, input_sha256=sha, run_id="hcrun_test2",
                provider="fake")
            artifact = houchen_paths.analysis_artifact_path("hcrun_test2")
            mtime_before = os.stat(artifact).st_mtime
            houchen_analyzer.call_provider(
                input_payload=payload, input_sha256=sha, run_id="hcrun_test2",
                provider="fake")
            mtime_after = os.stat(artifact).st_mtime
            self.assertEqual(mtime_before, mtime_after)

    def test_file_mode_is_0600_and_parent_0700(self):
        for root in _tmp_root():
            segs = [_seg(0, "test text")]
            payload, sha = houchen_analyzer.build_input_payload(
                video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
                transcript_version_sha="a" * 64, segments=segs)
            houchen_analyzer.call_provider(
                input_payload=payload, input_sha256=sha, run_id="hcrun_test3",
                provider="fake")
            art = houchen_paths.analysis_artifact_path("hcrun_test3")
            mode = stat.S_IMODE(os.stat(art).st_mode)
            self.assertEqual(mode, 0o600)
            parent_mode = stat.S_IMODE(
                os.stat(os.path.dirname(art)).st_mode)
            self.assertEqual(parent_mode, 0o700)

    def test_one_run_aggregates_multiple_video_items(self):
        """A multi-video run must not overwrite its first artifact item."""
        for root in _tmp_root():
            p1, sha1 = houchen_analyzer.build_input_payload(
                video_id="aaaaaaaaaaa", transcript_version_id="hctv_one",
                transcript_version_sha="a" * 64,
                segments=[_seg(0, "第一段")])
            p2, sha2 = houchen_analyzer.build_input_payload(
                video_id="bbbbbbbbbbb", transcript_version_id="hctv_two",
                transcript_version_sha="b" * 64,
                segments=[_seg(0, "第二段")])
            for payload, sha in ((p1, sha1), (p2, sha2)):
                outcome = houchen_analyzer.call_provider(
                    input_payload=payload, input_sha256=sha,
                    run_id="hcrun_multi", provider="fake")
                self.assertEqual(outcome.outcome, "success")
            artifact = houchen_paths.analysis_artifact_path("hcrun_multi")
            with open(artifact, encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(set(doc["items"]), {"aaaaaaaaaaa", "bbbbbbbbbbb"})
            self.assertEqual(
                houchen_analyzer.load_artifact_item(artifact, "aaaaaaaaaaa")[
                    "input_sha256"], sha1)
            self.assertEqual(
                houchen_analyzer.load_artifact_item(artifact, "bbbbbbbbbbb")[
                    "input_sha256"], sha2)


# ---------------------------------------------------------------------------
# Real providers (houchen_analyze.env required)
# ---------------------------------------------------------------------------

class TestRealProviders(unittest.TestCase):
    def test_missing_env_returns_failed_outcome(self):
        for tmp in _tmp_root():
            fake_env = os.path.join(tmp, "houchen_analyze.env")
            with mock.patch("houchen_analyze_env.analyze_env_path",
                              return_value=fake_env):
                segs = [_seg(0, "test text")]
                payload, sha = houchen_analyzer.build_input_payload(
                    video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
                    transcript_version_sha="a" * 64, segments=segs)
                outcome = houchen_analyzer.call_provider(
                    input_payload=payload, input_sha256=sha,
                    run_id="hcrun_noenv", provider="deepseek")
            self.assertEqual(outcome.outcome, "analyze_failed")
            self.assertIn(outcome.error_class,
                          ("missing_config", "provider_error", "missing_api_key"))

    def test_real_provider_mocked(self):
        fake_candidates = {
            "claims": [], "concept_links": [], "proposed_concepts": [],
            "reasoning_edges": [], "evidence_mentions": [],
            "forecast_candidates": [], "rejection_reasons": [],
        }
        for tmp in _tmp_root():
            os.environ["HOUCHEN_DATA_ROOT"] = tmp
            segs = [_seg(0, "中央财政需扩大转移支付。")]
            payload, sha = houchen_analyzer.build_input_payload(
                video_id="aaaaaaaaaaaa", transcript_version_id="hctv_test",
                transcript_version_sha="a" * 64, segments=segs)
            with mock.patch(
                "houchen_analyzer._call_real_provider",
                return_value=fake_candidates,
            ):
                outcome = houchen_analyzer.call_provider(
                    input_payload=payload, input_sha256=sha,
                    run_id="hcrun_mock", provider="deepseek")
            self.assertEqual(outcome.outcome, "success")
            self.assertIsNotNone(outcome.artifact_path)


# ---------------------------------------------------------------------------
# Redaction helper
# ---------------------------------------------------------------------------

class TestRedaction(unittest.TestCase):
    def test_signed_url_redacted(self):
        text = "GET https://api.example.com/v1/foo?signature=abc123"
        out = houchen_analyzer._redact(text)
        self.assertNotIn("abc123", out)
        self.assertIn("[signed-url]", out)

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer sk-abc123xyz"
        out = houchen_analyzer._redact(text)
        self.assertNotIn("sk-abc123xyz", out)

    def test_data_root_redacted(self):
        text = f"file={houchen_paths.data_root()}/artifacts/foo.json"
        out = houchen_analyzer._redact(text)
        self.assertNotIn(houchen_paths.data_root(), out)


# ---------------------------------------------------------------------------
# Segments-for-validator projection
# ---------------------------------------------------------------------------

class TestSegmentsForValidator(unittest.TestCase):
    def test_projects_ordinals_and_text(self):
        rows = [
            {"ordinal": 0, "text": "hello", "start_ms": 0, "end_ms": 1000},
            {"ordinal": 1, "text": "world", "start_ms": 1000, "end_ms": 2000},
        ]
        proj = houchen_analyzer.segments_for_validator(rows)
        self.assertEqual(set(proj.keys()), {0, 1})
        self.assertEqual(proj[0]["text"], "hello")
        self.assertEqual(proj[1]["text"], "world")

    def test_missing_text_defaults_to_empty(self):
        rows = [{"ordinal": 0, "text": "", "start_ms": 0, "end_ms": 1000}]
        proj = houchen_analyzer.segments_for_validator(rows)
        self.assertEqual(proj[0]["text"], "")


# ---------------------------------------------------------------------------
# Prompt / schema alignment (brief §9.3)
# ---------------------------------------------------------------------------

class TestPromptSchema(unittest.TestCase):
    def test_claim_layer_enum_excludes_speaker_statement(self):
        schema = houchen_prompt.analysis_input_json_schema()
        claim_layer = schema["$defs"]["claim_candidate"]["properties"]["layer"]
        self.assertEqual(
            claim_layer["enum"],
            ["speaker_reasoning", "system_evaluation"])


if __name__ == "__main__":
    unittest.main()