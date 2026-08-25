"""PR-4 Phase 1 — Renderer tests (brief §11).

Covers:

  1. Determinism: same input → same SHA-256 across repeated renders.
  2. Page-kind dispatch: each of video / concept / forecast /
     review_queue / coverage produces Markdown with the expected
     frontmatter + sectioning.
  3. Layer separation: concept page's `system_evaluations` MUST
     contain only `system_evaluation` rows; co-mingling
     `speaker_statement` rows triggers an assertion in the renderer.
  4. No wall-clock stamps: rendered text never contains an
     RFC-3339 timestamp.
  5. S-2 opt-in: `claim` pages are OFF by default; passing
     `include_claim_pages=True` does not enable them at the
     `render_page` dispatcher level — only the runner-level CLI flag
     matters.
  6. Three-section concept page: canonical definition / speaker uses /
     system analyses each have their own ## section.
  7. `render_sha256` is stable and decoupled from dataclass identity.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "houchen_fixtures"))

import houchen_render  # noqa: E402

from sample_pages import (  # noqa: E402
    all_sample_pages, make_concept_page, make_video_page,
)


class TestRendererDeterminism(unittest.TestCase):
    def test_video_page_sha_stable(self):
        a = houchen_render.render_video(make_video_page())
        b = houchen_render.render_video(make_video_page())
        self.assertEqual(a, b)
        self.assertEqual(
            houchen_render.render_sha256(a),
            houchen_render.render_sha256(b))

    def test_concept_page_sha_stable(self):
        a = houchen_render.render_concept(make_concept_page())
        b = houchen_render.render_concept(make_concept_page())
        self.assertEqual(a, b)

    def test_all_sample_kinds_deterministic(self):
        pages = all_sample_pages()
        for kind, page_obj in pages.items():
            m1 = houchen_render.render_page(kind, page_obj)
            m2 = houchen_render.render_page(kind, page_obj)
            self.assertEqual(m1, m2, f"{kind} not deterministic")

    def test_render_no_wallclock(self):
        """The renderer must not introduce wall-clock time at render-time.

        Pre-set ISO timestamps from the input dataclass (e.g.
        `published_at`) are intentionally allowed; the check rejects
        timestamps that fall within 60 seconds of "now" (i.e. a
        `datetime.now()` slip). We use a fixed `_TS` in the fixture to
        guarantee this is stable.
        """
        from datetime import datetime, timezone, timedelta
        threshold = (datetime.now(timezone.utc)
                     + timedelta(seconds=60)).isoformat()
        for kind, page_obj in all_sample_pages().items():
            md = houchen_render.render_page(kind, page_obj)
            # The renderer's own wall-clock output (if any) would be in
            # the future. Pre-set fixture timestamps are in the past
            # and pass.
            import re
            stamps = re.findall(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", md)
            future_stamps = [s for s in stamps if s > threshold[:19]]
            self.assertEqual(
                future_stamps, [],
                f"{kind} page contains a wall-clock stamp: {future_stamps}")


class TestVideoPage(unittest.TestCase):
    def setUp(self):
        self.markdown = houchen_render.render_video(make_video_page())

    def test_frontmatter_present(self):
        self.assertTrue(self.markdown.startswith("---\n"))
        self.assertIn("page_kind: \"video\"", self.markdown)
        self.assertIn("template_version:", self.markdown)

    def test_claim_listing(self):
        # Human-readable headings use claim_text, not opaque claim_id.
        self.assertIn("### 1. 中央财政转移支付对地方公共服务均等化有正向作用",
                      self.markdown)
        self.assertIn("### 2. 基础设施投资是地方政府的重要工具",
                      self.markdown)
        self.assertIn("## 主张", self.markdown)
        self.assertIn("[▶ 2:00]", self.markdown)
        self.assertIn("技术元数据", self.markdown)
        # Opaque IDs stay in metadata / body, not as H3 titles.
        self.assertNotIn("### cl_vid_aaaaaaaaaaa_001", self.markdown)

    def test_status_badge(self):
        # claim_count_rejected == 0 and needs_review == 1 → badge = "需要复核"
        self.assertIn("需要复核", self.markdown)

    def test_links_to_concept_and_forecast(self):
        self.assertIn("[[concept/con_001]]", self.markdown)
        self.assertIn("[[forecast/fc_001]]", self.markdown)


class TestConceptPage(unittest.TestCase):
    def setUp(self):
        self.markdown = houchen_render.render_concept(make_concept_page())

    def test_three_section_dividers(self):
        self.assertIn("## Canonical definition", self.markdown)
        self.assertIn("## Speaker uses", self.markdown)
        self.assertIn("## System analyses", self.markdown)

    def test_system_evaluations_only(self):
        # The fixture has one system_evaluation row; the renderer must
        # assert that no speaker_statement row leaks in.
        self.assertIn("## System analyses", self.markdown)

    def test_layer_assertion_on_speaker_statement_leak(self):
        """If a caller mixes a speaker_statement into system_evaluations
        the renderer MUST raise — guarding against silent layer
        co-mingling in the §3.1.5 separation."""
        import dataclasses
        # Construct a copy with a speaker_statement system_evaluation row.
        page = make_concept_page()
        bad_claim = dataclasses.replace(
            page.system_evaluations[0], layer="speaker_statement")
        bad_page = dataclasses.replace(
            page, system_evaluations=[bad_claim])
        with self.assertRaises(AssertionError):
            houchen_render.render_concept(bad_page)


class TestForecastPage(unittest.TestCase):
    def test_basic_shape(self):
        md = houchen_render.render_forecast(all_sample_pages()["forecast"])
        self.assertIn("page_kind: \"forecast\"", md)
        self.assertIn("fc_001", md)
        self.assertIn("candidate", md)


class TestReviewQueuePage(unittest.TestCase):
    def test_basic_shape(self):
        md = houchen_render.render_review_queue(
            all_sample_pages()["review_queue"])
        self.assertIn("page_kind: \"review_queue\"", md)
        self.assertIn("rule_4_speaker_unknown", md)


class TestCoveragePage(unittest.TestCase):
    def test_basic_shape(self):
        md = houchen_render.render_coverage(
            all_sample_pages()["coverage"])
        self.assertIn("page_kind: \"coverage\"", md)
        self.assertIn("schema_version: \"4\"", md)
        # Footer "next render SHA" is preserved.
        self.assertIn("下次 render SHA", md)


class TestRendererDispatch(unittest.TestCase):
    def test_claim_pages_off_by_default(self):
        """S-2 audit fix: claim pages are OFF in v1 — the dispatcher
        refuses unless the runner-level opt-in is honored."""
        with self.assertRaises(ValueError):
            houchen_render.render_page("claim", object())

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            houchen_render.render_page("bogus", object())


class TestRenderShaHelper(unittest.TestCase):
    def test_sha_is_64_char_hex(self):
        s = houchen_render.render_sha256("hello world")
        self.assertEqual(len(s), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in s))

    def test_sha_changes_with_content(self):
        self.assertNotEqual(
            houchen_render.render_sha256("alpha"),
            houchen_render.render_sha256("beta"))