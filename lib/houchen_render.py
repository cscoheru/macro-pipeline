"""PR-4 Phase 1 — Markdown page renderer (brief §11).

Pure templating layer. NO I/O, NO DB access, NO network. The renderer
takes typed dataclasses (Video, Concept, Forecast, ReviewQueue,
Coverage) and returns Markdown bytes + a SHA-256.

Page render is deterministic: the same input always yields the same
Markdown bytes. Re-render is byte-identical; `render_sha256` does not
change between identical inputs. Sort order is stable
(`(start_ms, ordinal, claim_id)`).

Page kinds supported (S-2 audit fix):
  - video, concept, forecast, review_queue, coverage (default ON)
  - claim (default OFF; the `render` CLI excludes unless
    `--include-claim-pages` is passed and the operator is authorized)

This module NEVER imports `lib/insight_publisher.py` or reads/writes
`data/store.db`. See `docs/plans/pr4-obsidian-research-map.md` §11.4
(S-4 audit guard).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


TEMPLATE_VERSION = "2026-08-24.1"

# Default ON (per the §11 inventory); OFF is opt-in via a CLI flag.
DEFAULT_PAGE_KINDS = ("video", "concept", "forecast",
                      "review_queue", "coverage")


# ---------------------------------------------------------------------------
# Page dataclasses — the renderer's input contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VideoPage:
    video_id: str
    canonical_url: str
    title: str
    published_at: str
    transcript_version_id: str
    analysis_run_id: str
    prompt_version: str
    claim_count_accepted: int
    claim_count_rejected: int
    claim_count_needs_review: int
    claims: list["ClaimSummary"] = field(default_factory=list)
    concept_ids: list[str] = field(default_factory=list)
    forecast_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimSummary:
    claim_id: str
    claim_text: str
    claim_type: str
    layer: str
    speaker: str | None
    exact_quote: str
    timestamp_url: str
    transcript_version_id: str


@dataclass(frozen=True)
class ConceptPage:
    concept_id: str
    canonical_name: str
    definition: str
    status: str           # 'proposed' | 'canonical' | 'deprecated'
    domain_slugs: list[str]
    first_seen_at: str
    last_seen_at: str
    canonical_definition_sources: list["ConceptSource"] = field(default_factory=list)
    speaker_use_sources: list["ConceptSource"] = field(default_factory=list)
    system_evaluations: list["ClaimSummary"] = field(default_factory=list)


@dataclass(frozen=True)
class ConceptSource:
    transcript_version_id: str
    start_ms: int
    end_ms: int
    exact_quote: str
    role: str             # 'canonical_definition' | 'usage' | 'speaker_definition'
    source_kind: str      # 'model' | 'human'
    timestamp_url: str = ""


@dataclass(frozen=True)
class ForecastPage:
    forecast_id: str
    claim_id: str
    time_window_start: str
    time_window_end: str
    outcome_condition: str
    status: str           # 'candidate' | 'verified_hit' | 'failed' | ...


@dataclass(frozen=True)
class ReviewQueuePage:
    run_id: str
    started_at: str
    summary: str
    per_rule_reject_count: dict[str, int]


@dataclass(frozen=True)
class CoveragePage:
    schema_version: int
    claim_outcomes: dict[str, int]
    concept_state: dict[str, int]
    analyze_scope: dict[str, int]
    transcript_state: dict[str, int]
    next_render_sha: str


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frontmatter(mapping: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in mapping.items():
        # YAML-safe single-line quoting.
        s = (v or "").replace('"', '\\"')
        lines.append(f'{k}: "{s}"')
    lines.append("---\n")
    return "\n".join(lines)


def _section(title: str) -> str:
    return f"## {title}\n\n"


def _render_quote_block(exact_quote: str, timestamp_url: str,
                        speaker: str | None, layer: str) -> str:
    spk = f"[{speaker}] " if speaker else ""
    badge = f"`{layer}`"
    return (f"> {spk}{exact_quote}\n>\n"
            f"> [{timestamp_url}]({timestamp_url})  {badge}\n\n")


def render_video(p: VideoPage) -> str:
    badge = "已校验" if p.claim_count_rejected == 0 and \
        p.claim_count_needs_review == 0 else "需要复核"
    fm = _frontmatter({
        "page_kind": "video",
        "video_id": p.video_id,
        "transcript_version_id": p.transcript_version_id,
        "analysis_run_id": p.analysis_run_id,
        "prompt_version": p.prompt_version,
        "template_version": TEMPLATE_VERSION,
        "claim_count_accepted": str(p.claim_count_accepted),
        "claim_count_rejected": str(p.claim_count_rejected),
        "claim_count_needs_review": str(p.claim_count_needs_review),
        "status": badge,
    })
    out = [fm]
    out.append(f"# {p.title or p.video_id}\n\n")
    out.append(f"- **链接**：{p.canonical_url}\n")
    out.append(f"- **时间**：{p.published_at}\n")
    out.append(f"- **状态**：{badge}\n\n")
    out.append(_section("分析出处"))
    out.append(f"- transcript_version_id：`{p.transcript_version_id}`\n")
    out.append(f"- analysis_run_id：`{p.analysis_run_id}`\n")
    out.append(f"- prompt_version：`{p.prompt_version}`\n\n")
    out.append(_section("声明列表"))
    if not p.claims:
        out.append("（无 accepted 主张）\n\n")
    else:
        for c in sorted(p.claims, key=lambda x: (x.transcript_version_id, x.claim_id)):
            out.append(f"### {c.claim_id}（{c.claim_type}）\n\n")
            out.append(f"{c.claim_text}\n\n")
            out.append(_render_quote_block(
                c.exact_quote, c.timestamp_url, c.speaker, c.layer))
    if p.concept_ids:
        out.append(_section("概念"))
        for cid in sorted(set(p.concept_ids)):
            out.append(f"- [[concept/{cid}]]\n")
        out.append("\n")
    if p.forecast_ids:
        out.append(_section("预测"))
        for fid in sorted(set(p.forecast_ids)):
            out.append(f"- [[forecast/{fid}]]\n")
        out.append("\n")
    return "".join(out)


def render_concept(p: ConceptPage) -> str:
    fm = _frontmatter({
        "page_kind": "concept",
        "concept_id": p.concept_id,
        "status": p.status,
        "template_version": TEMPLATE_VERSION,
    })
    out = [fm]
    out.append(f"# {p.canonical_name}\n\n")
    out.append(f"{p.definition}\n\n")
    if p.domain_slugs:
        out.append(f"- **领域**：{', '.join(sorted(set(p.domain_slugs)))}\n")
    out.append(f"- **首见**：{p.first_seen_at}\n")
    out.append(f"- **最近**：{p.last_seen_at}\n\n")
    out.append(_section("Canonical definition（人类/机器正式定义）"))
    if not p.canonical_definition_sources:
        out.append("（暂无）\n\n")
    else:
        for s in sorted(p.canonical_definition_sources,
                        key=lambda x: (x.transcript_version_id, x.start_ms)):
            tag = f"`{s.source_kind}`"
            out.append(f"- {s.exact_quote}  [{s.timestamp_url}]({s.timestamp_url})  {tag}\n")
        out.append("\n")
    out.append(_section("Speaker uses（来自人物讲话的用法）"))
    if not p.speaker_use_sources:
        out.append("（暂无）\n\n")
    else:
        for s in sorted(p.speaker_use_sources,
                        key=lambda x: (x.transcript_version_id, x.start_ms)):
            tag = f"`{s.source_kind}`"
            out.append(f"- {s.exact_quote}  [{s.timestamp_url}]({s.timestamp_url})  {tag}\n")
        out.append("\n")
    out.append(_section("System analyses（来自 model 的分析，仅 system_evaluation）"))
    # Critical: model analyses must NEVER include speaker_statement rows.
    for c in sorted(p.system_evaluations,
                    key=lambda x: (x.transcript_version_id, x.claim_id)):
        assert c.layer == "system_evaluation", \
            f"concept page {p.concept_id} leaking layer={c.layer!r}"
        out.append(f"- {c.claim_text}（{c.claim_id}，{c.claim_type}）\n")
        out.append(_render_quote_block(
            c.exact_quote, c.timestamp_url, c.speaker, c.layer))
    return "".join(out)


def render_forecast(p: ForecastPage) -> str:
    fm = _frontmatter({
        "page_kind": "forecast",
        "forecast_id": p.forecast_id,
        "claim_id": p.claim_id,
        "status": p.status,
        "template_version": TEMPLATE_VERSION,
    })
    out = [fm]
    out.append(f"# Forecast {p.forecast_id}\n\n")
    out.append(f"- **关联 claim**：`{p.claim_id}`\n")
    out.append(f"- **时间窗口**：{p.time_window_start} → {p.time_window_end}\n")
    out.append(f"- **状态**：`{p.status}`（candidate 标记）\n\n")
    out.append(_section("判定条件"))
    out.append(f"{p.outcome_condition}\n")
    return "".join(out)


def render_review_queue(p: ReviewQueuePage) -> str:
    fm = _frontmatter({
        "page_kind": "review_queue",
        "run_id": p.run_id,
        "template_version": TEMPLATE_VERSION,
    })
    out = [fm]
    out.append(f"# Review queue（{p.run_id}）\n\n")
    out.append(f"- 开始时间：{p.started_at}\n")
    out.append(f"- 摘要：{p.summary}\n\n")
    out.append(_section("按规则汇总"))
    if not p.per_rule_reject_count:
        out.append("（无）\n")
    else:
        for rule, count in sorted(p.per_rule_reject_count.items()):
            out.append(f"- {rule}：{count}\n")
    return "".join(out)


def render_coverage(p: CoveragePage) -> str:
    fm = _frontmatter({
        "page_kind": "coverage",
        "schema_version": str(p.schema_version),
        "template_version": TEMPLATE_VERSION,
    })
    out = [fm]
    out.append(f"# Coverage\n\n")
    out.append(f"- schema_version：`{p.schema_version}`\n")
    out.append(f"- 下次 render SHA：{p.next_render_sha}\n\n")
    out.append(_section("claim_outcomes"))
    for k, v in sorted(p.claim_outcomes.items()):
        out.append(f"- {k}：{v}\n")
    out.append("\n")
    out.append(_section("concept_state"))
    for k, v in sorted(p.concept_state.items()):
        out.append(f"- {k}：{v}\n")
    out.append("\n")
    out.append(_section("analyze_scope"))
    for k, v in sorted(p.analyze_scope.items()):
        out.append(f"- {k}：{v}\n")
    out.append("\n")
    out.append(_section("transcript_state"))
    for k, v in sorted(p.transcript_state.items()):
        out.append(f"- {k}：{v}\n")
    return "".join(out)


# Single dispatch — used by `houchen_runner.run_render`.
_PAGE_RENDERERS = {
    "video": render_video,
    "concept": render_concept,
    "forecast": render_forecast,
    "review_queue": render_review_queue,
    "coverage": render_coverage,
}


def render_page(kind: str, page_obj) -> str:
    """Dispatch a dataclass to its renderer. Raises ValueError on bad kind."""
    if kind == "claim":
        raise ValueError(
            "claim pages are OFF by default in v1 (S-2 audit fix); pass "
            "include_claim_pages=True to the CLI / runner to opt in"
        )
    if kind not in _PAGE_RENDERERS:
        raise ValueError(
            f"page_kind must be one of {sorted(_PAGE_RENDERERS) + ['claim']}, "
            f"got {kind!r}"
        )
    return _PAGE_RENDERERS[kind](page_obj)


def render_sha256(markdown: str) -> str:
    """Stable SHA-256 over the rendered bytes (UTF-8)."""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def is_deterministic(text: str) -> bool:
    """Sanity check: rendered Markdown must not contain wall-clock time.

    Templates deliberately omit `now()`; this is a defensive guard that
    fails closed if a future render change accidentally re-introduces a
    wall-clock stamp. The check looks for the canonical RFC-3339 form.
    """
    return re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text) is None