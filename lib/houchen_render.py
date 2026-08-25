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


TEMPLATE_VERSION = "2026-08-25.3"

# Human-facing labels for Obsidian reading mode (brief §11 readability).
_CLAIM_TYPE_ZH = {
    "definition": "定义",
    "descriptive": "描述",
    "causal": "因果",
    "predictive": "预测",
    "normative": "规范",
    "interpretive": "解释",
}
_LAYER_ZH = {
    "speaker_statement": "主讲原话",
    "speaker_reasoning": "主讲推理",
    "system_evaluation": "系统评估",
}

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
    concept_names: dict[str, str] = field(default_factory=dict)
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


def _frontmatter(mapping: dict[str, str],
                 aliases: list[str] | None = None) -> str:
    lines = ["---"]
    for k, v in mapping.items():
        if v is None or v == "":
            continue
        s = str(v).replace('"', '\\"')
        lines.append(f'{k}: "{s}"')
    if aliases:
        seen: list[str] = []
        for a in aliases:
            if a and a not in seen:
                seen.append(a)
        if seen:
            lines.append("aliases:")
            for a in seen:
                s = a.replace('"', '\\"')
                lines.append(f'  - "{s}"')
    lines.append("---\n")
    return "\n".join(lines)


def _section(title: str) -> str:
    return f"## {title}\n\n"


def _parse_timestamp_seconds(timestamp_url: str) -> int | None:
    """Extract `t=` seconds from a YouTube (or compatible) timestamp URL."""
    if not timestamp_url:
        return None
    m = re.search(r"[?&#]t=(\d+)", timestamp_url)
    if m:
        return int(m.group(1))
    m = re.search(r"[?&#]t=(\d+)s\b", timestamp_url)
    if m:
        return int(m.group(1))
    return None


def _format_clock(seconds: int | None) -> str:
    if seconds is None:
        return ""
    h, rem = divmod(max(0, seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _date_only(iso: str) -> str:
    if not iso:
        return ""
    return iso[:10] if len(iso) >= 10 else iso


def _wiki(kind: str, key: str, label: str | None = None) -> str:
    if label:
        return f"[[{kind}/{key}|{label}]]"
    return f"[[{kind}/{key}]]"


def _same_text(a: str, b: str) -> bool:
    def n(s):
        return re.sub(r"\s+", "", (s or "").strip("「」\"'"))
    return bool(n(a)) and n(a) == n(b)


def _timestamp_link(timestamp_url: str) -> str:
    """Short readable jump link — avoid dumping the full URL as link text."""
    if not timestamp_url:
        return ""
    clock = _format_clock(_parse_timestamp_seconds(timestamp_url))
    label = f"▶ {clock}" if clock else "▶ 跳转原片"
    return f"[{label}]({timestamp_url})"


def _render_quote_block(exact_quote: str, timestamp_url: str,
                        speaker: str | None, layer: str) -> str:
    spk = f"{speaker}：" if speaker else ""
    layer_zh = _LAYER_ZH.get(layer, layer)
    jump = _timestamp_link(timestamp_url)
    lines = [f"> {spk}「{exact_quote}」\n"]
    if jump:
        lines.append(f">\n> {jump} · {layer_zh}\n")
    else:
        lines.append(f">\n> {layer_zh}\n")
    lines.append("\n")
    return "".join(lines)


def _claim_heading(claim_text: str) -> str:
    """One-line heading from claim_text; strip newlines for Markdown safety."""
    text = (claim_text or "").replace("\n", " ").strip() or "（无主张文本）"
    return text


_CONCEPT_STATUS_ZH = {
    "proposed": "候选",
    "canonical": "正式",
    "deprecated": "已弃用",
}
_SOURCE_KIND_ZH = {
    "model": "抽取",
    "human": "人工",
}


def _claim_meta_line(c: ClaimSummary) -> str:
    type_zh = _CLAIM_TYPE_ZH.get(c.claim_type, c.claim_type)
    layer_zh = _LAYER_ZH.get(c.layer, c.layer)
    jump = _timestamp_link(c.timestamp_url)
    bits = [type_zh]
    if jump:
        bits.append(jump)
    bits.append(layer_zh)
    return f"*{' · '.join(bits)}*\n\n"


def _render_claim_body(c: ClaimSummary) -> str:
    if c.exact_quote and not _same_text(c.claim_text, c.exact_quote):
        type_zh = _CLAIM_TYPE_ZH.get(c.claim_type, c.claim_type)
        return f"*{type_zh}*\n\n" + _render_quote_block(
            c.exact_quote, c.timestamp_url, c.speaker, c.layer)
    return _claim_meta_line(c)


def _render_source_line(s: ConceptSource) -> str:
    jump = _timestamp_link(s.timestamp_url)
    kind_zh = _SOURCE_KIND_ZH.get(s.source_kind, s.source_kind)
    quote = f"「{s.exact_quote}」" if s.exact_quote else ""
    if jump:
        return f"- {quote} {jump} · {kind_zh}\n"
    return f"- {quote} · {kind_zh}\n"


def render_video(p: VideoPage) -> str:
    badge = "已校验" if p.claim_count_rejected == 0 and \
        p.claim_count_needs_review == 0 else "需要复核"
    title = p.title or p.video_id
    fm = _frontmatter({
        "page_kind": "video",
        "video_id": p.video_id,
        "title": title,
        "status": badge,
        "template_version": TEMPLATE_VERSION,
    }, aliases=[title] if p.title else None)
    out = [fm]
    out.append(f"# {title}\n\n")
    if p.canonical_url:
        out.append(f"[打开视频]({p.canonical_url})")
        pub = _date_only(p.published_at)
        if pub:
            out.append(f" · {pub}")
        out.append(f" · {badge}\n\n")
    else:
        out.append(f"{badge}\n\n")

    out.append(_section("主张"))
    if not p.claims:
        out.append("（暂无通过校验的主张）\n\n")
    else:
        ordered = sorted(
            p.claims,
            key=lambda x: (
                _parse_timestamp_seconds(x.timestamp_url) is None,
                _parse_timestamp_seconds(x.timestamp_url) or 0,
                x.claim_id,
            ),
        )
        for i, c in enumerate(ordered, start=1):
            out.append(f"### {i}. {_claim_heading(c.claim_text)}\n\n")
            out.append(_render_claim_body(c))

    if p.concept_ids:
        out.append(_section("概念"))
        for cid in sorted(set(p.concept_ids)):
            name = (p.concept_names or {}).get(cid)
            out.append(f"- {_wiki('concept', cid, name)}\n")
        out.append("\n")
    n_fc = len(set(p.forecast_ids or []))
    if n_fc:
        out.append(_section("预测"))
        out.append(f"本视频有 {n_fc} 条预测候选。\n\n")

    return "".join(out)


def render_concept(p: ConceptPage) -> str:
    status_zh = _CONCEPT_STATUS_ZH.get(p.status, p.status)
    fm = _frontmatter({
        "page_kind": "concept",
        "concept_id": p.concept_id,
        "title": p.canonical_name,
        "status": status_zh,
        "template_version": TEMPLATE_VERSION,
    }, aliases=[p.canonical_name] if p.canonical_name else None)
    out = [fm]
    out.append(f"# {p.canonical_name}\n\n")
    if p.definition:
        out.append(f"{p.definition}\n\n")
    meta = []
    if p.domain_slugs:
        meta.append(f"- **领域**：{', '.join(sorted(set(p.domain_slugs)))}")
    first = _date_only(p.first_seen_at)
    last = _date_only(p.last_seen_at)
    if first:
        meta.append(f"- **首见**：{first}")
    if last and last != first:
        meta.append(f"- **最近**：{last}")
    if meta:
        out.append("\n".join(meta) + "\n\n")

    if p.canonical_definition_sources:
        out.append(_section("正式定义"))
        for s in sorted(p.canonical_definition_sources,
                        key=lambda x: (x.transcript_version_id, x.start_ms)):
            out.append(_render_source_line(s))
        out.append("\n")
    if p.speaker_use_sources:
        out.append(_section("讲话中的用法"))
        for s in sorted(p.speaker_use_sources,
                        key=lambda x: (x.transcript_version_id, x.start_ms)):
            out.append(_render_source_line(s))
        out.append("\n")
    if p.system_evaluations:
        out.append(_section("系统评估"))
        for c in sorted(p.system_evaluations,
                        key=lambda x: (x.transcript_version_id, x.claim_id)):
            assert c.layer == "system_evaluation", \
                f"concept page {p.concept_id} leaking layer={c.layer!r}"
            out.append(f"### {_claim_heading(c.claim_text)}\n\n")
            out.append(_render_claim_body(c))
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