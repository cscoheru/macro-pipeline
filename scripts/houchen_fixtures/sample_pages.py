"""PR-4 Phase 1 — sample page dataclasses for renderer tests.

A small, deterministic fixture used by `scripts/test_houchen_render.py`
and `scripts/test_houchen_publisher.py`. The fixture is intentionally
minimal: one video, one concept, one forecast, one review-queue, and
one coverage page. The `claim` page kind is deliberately NOT provided
— the S-2 audit fix marks per-claim pages OFF by default in v1, so the
fixture exercises the opt-in path (`include_claim_pages=True`) with a
synthetic claim page only when a test asks for it.

Re-rendering the same input twice MUST yield byte-identical Markdown;
the tests rely on this property. `houchen_render.render_sha256` and
`render_video` etc. do not call `datetime.now()` anywhere — the only
time-like fields are values the caller passes in.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from houchen_render import (  # noqa: E402
    ClaimSummary, ConceptPage, ConceptSource, CoveragePage, ForecastPage,
    ReviewQueuePage, VideoPage,
)


# A canonical timestamp for deterministic rendering. Tests assert byte-
# identical output across two render passes; using a fixed timestamp
# avoids wall-clock drift if any future renderer change accidentally
# references `now()`.
_TS = "2026-08-24T00:00:00+00:00"


def make_video_page() -> VideoPage:
    return VideoPage(
        video_id="vid_aaaaaaaaaaa",
        canonical_url="https://example.com/v/aaaaaaaaaaa",
        title="央地财政关系分析",
        published_at=_TS,
        transcript_version_id="tv_vid_aaaaaaaaaaa",
        analysis_run_id="run_analyze_001",
        prompt_version="2026-08-24.1",
        claim_count_accepted=2,
        claim_count_rejected=0,
        claim_count_needs_review=1,
        claims=[
            ClaimSummary(
                claim_id="cl_vid_aaaaaaaaaaa_001",
                claim_text="中央财政转移支付对地方公共服务均等化有正向作用",
                claim_type="causal",
                layer="system_evaluation",
                speaker=None,
                exact_quote="中央财政转移支付能显著缩小地方公共服务差距",
                timestamp_url="https://example.com/v/aaaaaaaaaaa?t=120",
                transcript_version_id="tv_vid_aaaaaaaaaaa",
            ),
            ClaimSummary(
                claim_id="cl_vid_aaaaaaaaaaa_002",
                claim_text="基础设施投资是地方政府的重要工具",
                claim_type="descriptive",
                layer="speaker_statement",
                speaker="李厚辰",
                exact_quote="基础设施投资是地方政府推动增长的重要工具",
                timestamp_url="https://example.com/v/aaaaaaaaaaa?t=480",
                transcript_version_id="tv_vid_aaaaaaaaaaa",
            ),
        ],
        concept_ids=["con_001", "con_002"],
        forecast_ids=["fc_001"],
    )


def make_concept_page() -> ConceptPage:
    return ConceptPage(
        concept_id="con_001",
        canonical_name="财政转移支付",
        definition="中央对地方的财政转移支付制度。",
        status="canonical",
        domain_slugs=["finance", "governance"],
        first_seen_at=_TS,
        last_seen_at=_TS,
        canonical_definition_sources=[
            ConceptSource(
                transcript_version_id="tv_seed_001",
                start_ms=0,
                end_ms=1000,
                exact_quote="中央对地方的转移支付包括一般性和专项两类",
                role="canonical_definition",
                source_kind="human",
            ),
        ],
        speaker_use_sources=[
            ConceptSource(
                transcript_version_id="tv_vid_aaaaaaaaaaa",
                start_ms=120000,
                end_ms=121000,
                exact_quote="中央财政转移支付能显著缩小地方公共服务差距",
                role="usage",
                source_kind="model",
            ),
        ],
        system_evaluations=[
            ClaimSummary(
                claim_id="cl_vid_aaaaaaaaaaa_001",
                claim_text="中央财政转移支付对地方公共服务均等化有正向作用",
                claim_type="causal",
                layer="system_evaluation",
                speaker=None,
                exact_quote="中央财政转移支付能显著缩小地方公共服务差距",
                timestamp_url="https://example.com/v/aaaaaaaaaaa?t=120",
                transcript_version_id="tv_vid_aaaaaaaaaaa",
            ),
        ],
    )


def make_forecast_page() -> ForecastPage:
    return ForecastPage(
        forecast_id="fc_001",
        claim_id="cl_vid_aaaaaaaaaaa_001",
        time_window_start="2026-01-01",
        time_window_end="2026-12-31",
        outcome_condition=(
            "若 2026 年中央对地方一般性转移支付增幅 ≥ 8%，"
            "则地方公共服务均等化指数同比提升"
        ),
        status="candidate",
    )


def make_review_queue_page() -> ReviewQueuePage:
    return ReviewQueuePage(
        run_id="run_validate_001",
        started_at=_TS,
        summary="4 claims validated; 1 needs review",
        per_rule_reject_count={
            "rule_1_missing_video_id": 0,
            "rule_4_speaker_unknown": 1,
            "rule_9_forecast_empty_condition": 0,
        },
    )


def make_coverage_page() -> CoveragePage:
    return CoveragePage(
        schema_version=4,
        claim_outcomes={
            "accepted": 12,
            "needs_review": 3,
            "rejected": 1,
            "proposed": 2,
        },
        concept_state={
            "seed": 6,
            "proposed": 7,
            "canonical": 9,
            "deprecated": 0,
        },
        analyze_scope={
            "videos_pending": 4,
            "videos_analyzed": 22,
        },
        transcript_state={
            "ok": 22,
            "failed": 1,
        },
        next_render_sha="0" * 64,
    )


def all_sample_pages() -> dict:
    return {
        "video": make_video_page(),
        "concept": make_concept_page(),
        "forecast": make_forecast_page(),
        "review_queue": make_review_queue_page(),
        "coverage": make_coverage_page(),
    }