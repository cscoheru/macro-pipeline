"""Deterministic Markdown renderer and content-addressed artifact writer."""
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

import paths


@dataclass(frozen=True)
class RenderedInsight:
    vault_path: str
    content: str
    content_sha256: str


def _inline(value):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


# Validator error strings embed raw model output (untraceable numbers, IDs...).
# Neutralize markdown/link syntax before it reaches the 待审 note, or the
# model can smuggle renderable markdown through the error channel.
_NOTE_MD_PATTERN = re.compile(r"(!\[|\]\(|<[A-Za-z/!]|https?://)", re.IGNORECASE)


def _note_safe(value):
    def _break(match):
        token = match.group(0)
        return token[0] + " " + token[1:] if len(token) > 1 else token + " "
    return _NOTE_MD_PATTERN.sub(_break, _inline(value))


def _cell(value):
    """Inline + escape characters that would break a Markdown table cell."""
    return _inline(value).replace("\\", "\\\\").replace("|", "\\|")


def _yaml(value):
    return json.dumps(_inline(value), ensure_ascii=False)


def planned_vault_path(ins_id, as_of):
    """Deterministic vault path known at queue time (no model-dependent slug).

    Derived only from the insight id and the fact-pack as_of period, so the
    same path is computable at collection time (row insert) and at render
    time — keeping planned_vault_path immutable without a fallback spool.
    """
    if not re.fullmatch(r"ins_[0-9a-f]{32}", ins_id):
        raise ValueError("invalid generated insight id")
    period = str(as_of or "")[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise ValueError(f"as_of must be YYYY-MM, got {as_of!r}")
    return f"洞察/{period[:4]}/{period}-{ins_id[4:12]}.md"


def _source_lookup(fact_pack):
    return {item["id"]: item for item in fact_pack.get("evidence", [])}


def _safe_source_url(value):
    value = _inline(value)
    return value if value.startswith(("https://", "http://")) else ""


def _frontmatter(document, fact_pack, ins_id, input_sha256, prompt_version, generated_at):
    research = fact_pack["research_item"]
    return [
        "---",
        "type: generated_macro_insight",
        f"ins_id: {_yaml(ins_id)}",
        f"research_item_id: {_yaml(research['id'])}",
        f"generated_at: {_yaml(generated_at)}",
        f"as_of: {_yaml(fact_pack['as_of'])}",
        f"confidence: {_yaml(document['confidence'])}",
        f"input_sha256: {_yaml(input_sha256)}",
        f"prompt_version: {_yaml(prompt_version)}",
        "tags: [宏观, 洞察, 自动生成]",
        "machine_owned: true",
        "---",
    ]


def _render_changed(document):
    lines = ["## 发生了什么", ""]
    for item in document["what_changed"]:
        current = "—" if item["current_value"] is None else item["current_value"]
        previous = "—" if item["previous_value"] is None else item["previous_value"]
        lines.append(
            f"- **{_inline(item['evidence_id'])}**：{_inline(item['statement'])} "
            f"（当前 {current} {_inline(item['unit'])}；前值 {previous}；"
            f"{_inline(item['comparison'])}）"
        )
    return lines + [""]


def _render_mechanism(document):
    labels = {"observed": "观察", "derived": "派生", "inferred": "推断"}
    lines = ["## 机制链", ""]
    for index, item in enumerate(document["mechanism_chain"], 1):
        ids = ", ".join(f"`{_inline(value)}`" for value in item["supporting_ids"])
        lines.append(
            f"{index}. **{labels[item['kind']]}**：{_inline(item['statement'])}（{ids}）"
        )
    return lines + [""]


def _render_evidence(title, items):
    lines = [f"## {title}", ""]
    for item in items:
        lines.append(f"- `{_inline(item['id'])}`：{_inline(item['finding'])}")
    return lines + [""]


def _render_sources(document, fact_pack):
    evidence = _source_lookup(fact_pack)
    lines = ["## 来源表", "", "| Evidence | 发布方 | 指标 | 数据期 | 值 | 原始来源 |",
             "|---|---|---|---|---:|---|"]
    for row in document["source_table"]:
        item = evidence[row["evidence_id"]]
        value = "—" if item["value"] is None else f"{item['value']} {_inline(item['unit'])}"
        url = _safe_source_url(item.get("source_url"))
        source = f"[原文](<{url}>)" if url else "—"
        lines.append(
            f"| `{item['id']}` | {_cell(item['publisher'])} | "
            f"{_cell(item['metric_id'])} | {_cell(item['observed_period'])} | "
            f"{value} | {source} |"
        )
    return lines + [""]


def render_markdown(document, fact_pack, *, ins_id, input_sha256,
                    prompt_version, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    lines = _frontmatter(
        document, fact_pack, ins_id, input_sha256, prompt_version, generated_at,
    )
    lines += ["", f"# {_inline(document['headline'])}", "",
              "> 本文由机器流水线生成；所有状态以 append-only ledger 为准。", "",
              "## 结论", "", _inline(document["bottom_line"]["text"]), "",
              f"- **截至：** {_inline(document['bottom_line']['as_of'])}",
              f"- **置信度：** {_inline(document['confidence'])}", ""]
    lines += _render_changed(document)
    lines += _render_mechanism(document)
    lines += _render_evidence("支持证据", document["supporting_evidence"])
    lines += _render_evidence("反证与约束", document["counter_evidence"])
    lines += ["## 替代解释", ""]
    for item in document["alternative_explanations"]:
        lines.append(
            f"- **解释：** {_inline(item['explanation'])}  "
            f"**证伪条件：** {_inline(item['falsifier'])}"
        )
    lines += ["", "## 影响", ""]
    for item in document["implications"]:
        lines.append(f"- **{_inline(item['horizon'])}：** {_inline(item['statement'])}")
    lines += ["", "## 下一验证点", ""]
    for item in document["next_checks"]:
        threshold = "仅等待发布" if item["threshold"] is None else item["threshold"]
        lines.append(
            f"- **{_inline(item['metric'])}**：{_inline(item['direction'])} {threshold}；"
            f"数据期 {_inline(item['target_period'])}；复核 {_inline(item['review_due_at'])}；"
            f"来源 `{_inline(item['source_id'])}`"
        )
    lines += ["", "## 局限", ""]
    lines += [f"- {_inline(item)}" for item in document["limitations"]]
    lines += [""] + _render_sources(document, fact_pack)
    content = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return RenderedInsight(
        vault_path=planned_vault_path(ins_id, fact_pack["as_of"]),
        content=content,
        content_sha256=digest,
    )


def persist_artifact(rendered, directory=None):
    root = directory or paths.INSIGHT_ARTIFACTS
    os.makedirs(root, mode=0o700, exist_ok=True)
    target = os.path.join(root, f"{rendered.content_sha256}.md")
    if os.path.exists(target):
        with open(target, encoding="utf-8") as handle:
            if handle.read() != rendered.content:
                raise ValueError("content-address collision at artifact path")
        return target
    descriptor, temp_path = tempfile.mkstemp(prefix=".artifact-", dir=root, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return target


def persist_response(document, directory=None):
    """Content-addressed raw model response at responses/<sha>.json (0o600).

    Written before validation so a needs_review insight keeps its raw output
    for diagnosis even when the document fails the gates. Idempotent on
    identical content. Returns (path, sha256).
    """
    root = directory or paths.INSIGHT_RESPONSES
    body = json.dumps(document, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    os.makedirs(root, mode=0o700, exist_ok=True)
    target = os.path.join(root, f"{sha}.json")
    if os.path.exists(target):
        return target, sha
    descriptor, temp_path = tempfile.mkstemp(prefix=".response-", dir=root, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return target, sha


def render_review_note(ins_id, fact_pack, *, errors, reason,
                       response_path=None, response_sha=None):
    """Markdown body for 待审/<ins_id>.md — why an insight needs a human.

    Lists the failed gates, a fact-pack summary, and the local path to the
    raw model response so needs_review insights are diagnosable without the
    ledger (which stores only a detail hash, not the text).
    """
    as_of = fact_pack.get("as_of", "?")
    evidence = [e.get("id") or e.get("evidence_id")
                for e in fact_pack.get("evidence", [])]
    lines = [
        "---",
        f"ins_id: {_yaml(ins_id)}",
        "status: needs_review",
        f"as_of: {_yaml(as_of)}",
        "---",
        "",
        f"# 待人工复核：{_inline(ins_id)}",
        "",
        f"**原因**：{_note_safe(reason)}",
        "",
        "## 失败门禁",
    ]
    lines.extend(f"- {_note_safe(err)}" for err in errors)
    lines += [
        "",
        "## 事实包摘要",
        f"- as_of: {_inline(as_of)}",
        f"- 证据 ID: {', '.join(_inline(e) for e in evidence if e) or '（无）'}",
    ]
    if response_path:
        lines += ["", "## 模型原始响应", f"- 本地路径: `{_inline(response_path)}`"]
        if response_sha:
            lines.append(f"- 内容 sha256: `{_inline(response_sha)}`")
    lines += [
        "",
        "修复 prompt / 事实包后用 `python3 run.py --insights-only` 重跑该队列。",
    ]
    return "\n".join(lines) + "\n"
