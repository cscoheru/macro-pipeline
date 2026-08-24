"""PR-3 analyzer (brief §9.1 / §9.2).

Builds the deterministic analysis INPUT bundle, invokes the configured
provider (default: `fake` for offline tests), persists the provider's
response as a content-addressed JSON, and exposes a tiny loader for the
validator.

The provider layer reuses `lib/insight_provider.ProviderConfig` semantics
(three backends + JSON schema / json_object outputs) but reads its own
configuration file (`config/houchen_analyze.env`, audit F-6), NOT
`config/insight.env`, to keep research and macro insight namespaces
independent.

Default behavior in tests is OFFLINE: `provider="fake"` returns a
deterministic, content-addressed JSON built from a fixture in
`scripts/houchen_fixtures/fake_provider.py`. Real-provider invocations
require explicit `--provider {anthropic|deepseek|minimax}` and the
operator-supplied env file.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_paths  # noqa: E402
import houchen_prompt  # noqa: E402


@dataclass
class AnalyzeOutcome:
    """Per-video analysis outcome (mirrors PR-2 runner pattern)."""
    video_id: str
    outcome: str           # 'success' / 'analyze_failed'
    error_class: str | None = None
    detail: str | None = None
    input_sha256: str | None = None
    artifact_path: str | None = None
    candidates: dict | None = None


# Redaction helper: keep all PR-2 + PR-3 detail logs free of signed URLs,
# Bearer tokens, or absolute paths under the research data root.

def _redact(text: str) -> str:
    if not text:
        return ""
    import re
    text = re.sub(r"https?://[^\s]*signature=[^\s]*", "[signed-url]", text)
    text = re.sub(r"(?i)authorization:\s*bearer\s+\S+", "[bearer]", text)
    text = re.sub(r"(?i)(api[_-]?key|token)\s*[=:]\]\s*\S+", "[secret]", text)
    text = re.sub(houchen_paths.data_root(), "[data-root]", text) \
        if isinstance(text, str) else text
    return text


def _call_real_provider(input_payload: dict, *, provider: str,
                        model: str) -> dict:
    """Invoke anthropic / deepseek / minimax via houchen_analyze.env."""
    import houchen_analyze_env
    import insight_provider

    cfg = houchen_analyze_env.load_provider_config(provider)
    if model:
        cfg = insight_provider.ProviderConfig(
            provider=cfg.provider,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=model,
            timeout_seconds=cfg.timeout_seconds,
            max_tokens=cfg.max_tokens,
            max_retries=cfg.max_retries,
            max_input_chars=cfg.max_input_chars,
        )
    prompt, schema, _ = houchen_prompt.load_analysis_prompt_and_schema()
    client = insight_provider.build_provider(cfg)
    return client.generate(input_payload, prompt=prompt, schema=schema)


def build_input_payload(*, video_id: str, transcript_version_id: str,
                         transcript_version_sha: str,
                         segments: list[dict],
                         model: str = "", provider: str = "") -> tuple[dict, str]:
    """Build the canonical input bundle and its SHA-256."""
    payload = houchen_prompt.build_analysis_input(
        video_id=video_id,
        transcript_version_id=transcript_version_id,
        transcript_version_sha=transcript_version_sha,
        segments=segments,
        model=model,
        provider=provider,
    )
    sha = houchen_prompt.input_sha256(payload)
    return payload, sha


def _atomic_write_json(target_path: str, payload: Any) -> None:
    """Atomic JSON write (temp + fsync + rename), 0700 parent + 0600 file.

    Mirrors the PR-2 normalizer install discipline. Idempotent: if the
    file already exists with byte-identical content, no rewrite.
    """
    parent = os.path.dirname(target_path)
    houchen_paths.assert_no_symlink_components(parent)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    tmp = f"{target_path}.tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    if not os.path.isfile(target_path):
        os.replace(tmp, target_path)
    else:
        existing = open(target_path, "rb").read()
        if existing != blob:
            os.replace(tmp, target_path)
        else:
            os.unlink(tmp)


def call_provider(*, input_payload: dict, input_sha256: str,
                  run_id: str, provider: str = "fake",
                  model: str = "") -> AnalyzeOutcome:
    """Invoke the configured provider for one analysis input.

    `provider='fake'` is the default (offline) and delegates to
    `scripts/houchen_fixtures.fake_provider.fake_analyze(input_payload)`,
    which returns deterministic candidates routed by `input_sha256`.

    Returns an `AnalyzeOutcome`. On success, `candidates` is populated and
    `artifact_path` points to the derived JSON. On failure,
    `outcome='analyze_failed'` with a redacted `detail` and `error_class`.
    Never raises to the caller — the runner persists the failure row.
    """
    artifact_path = houchen_paths.analysis_artifact_path(run_id)
    input_path = houchen_paths.analysis_input_path(input_sha256)
    try:
        # Persist the input bundle (content-addressed) first.
        _atomic_write_json(input_path, input_payload)
        if provider == "fake":
            from houchen_fixtures.fake_provider import fake_analyze
            candidates = fake_analyze(input_payload)
        else:
            candidates = _call_real_provider(
                input_payload, provider=provider, model=model)
        # A CLI analyze run can cover many videos. The run artifact therefore
        # aggregates one item per video instead of overwriting the previous
        # provider result at `<runs>/<run_id>.json`. Preserve the legacy
        # top-level `candidates` reader for one-item artifacts during the
        # PR-3 transition.
        doc = {"run_id": run_id, "items": {}}
        if os.path.isfile(artifact_path):
            try:
                with open(artifact_path, "r", encoding="utf-8") as f:
                    prior = json.load(f)
                if prior.get("run_id") == run_id:
                    doc = prior
                    if "items" not in doc:
                        # Compatibility for the first PR-3 artifact shape.
                        prior_video = doc.get("video_id")
                        if prior_video and "candidates" in doc:
                            doc["items"] = {prior_video: {
                                "input_sha256": doc.get("input_sha256"),
                                "transcript_version_id": doc.get(
                                    "transcript_version_id", ""),
                                "model": doc.get("model", ""),
                                "provider": doc.get("provider", ""),
                                "candidates": doc["candidates"],
                            }}
                        else:
                            doc["items"] = {}
            except (OSError, ValueError, json.JSONDecodeError):
                # Derived artifact corruption must not block a replay: the
                # current deterministic item becomes a fresh artifact.
                doc = {"run_id": run_id, "items": {}}
        video_id = input_payload.get("video_id", "")
        doc["items"][video_id] = {
            "input_sha256": input_sha256,
            "transcript_version_id": input_payload.get(
                "transcript_version_id", ""),
            "model": model,
            "provider": provider,
            "candidates": candidates,
        }
        _atomic_write_json(artifact_path, doc)
        return AnalyzeOutcome(
            video_id=input_payload.get("video_id", ""),
            outcome="success",
            input_sha256=input_sha256,
            artifact_path=artifact_path,
            candidates=candidates,
        )
    except Exception as e:  # noqa: BLE001 — best-effort boundary
        return AnalyzeOutcome(
            video_id=input_payload.get("video_id", ""),
            outcome="analyze_failed",
            error_class="provider_error",
            detail=_redact(str(e)),
            input_sha256=input_sha256,
        )


def load_candidates(artifact_path: str, *, video_id: str | None = None) -> dict:
    """Load candidates from a derived analysis artifact.

    Current artifacts aggregate one `items[video_id]` entry per video. A
    `video_id` is required if the artifact has multiple items so validation
    cannot accidentally bind one video's candidates to another transcript.
    First-generation single-item artifacts remain readable for replay.
    """
    with open(artifact_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if "candidates" in doc:  # first-generation one-video artifact
        return doc["candidates"]
    items = doc.get("items")
    if not isinstance(items, dict):
        raise ValueError(f"artifact {artifact_path} missing 'items' key")
    if video_id is None:
        if len(items) != 1:
            raise ValueError("multi-video artifact requires video_id")
        video_id = next(iter(items))
    item = items.get(video_id)
    if not isinstance(item, dict) or "candidates" not in item:
        raise ValueError(f"artifact {artifact_path} missing candidates for {video_id}")
    return item["candidates"]


def load_artifact_item(artifact_path: str, video_id: str) -> dict:
    """Return the exact per-video artifact item (input SHA + candidates)."""
    with open(artifact_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if "candidates" in doc:
        if doc.get("video_id") not in (None, video_id):
            raise ValueError(f"artifact {artifact_path} belongs to another video")
        return {
            "input_sha256": doc.get("input_sha256"),
            "transcript_version_id": doc.get("transcript_version_id", ""),
            "candidates": doc["candidates"],
        }
    items = doc.get("items")
    item = items.get(video_id) if isinstance(items, dict) else None
    if not isinstance(item, dict) or not item.get("input_sha256"):
        raise ValueError(f"artifact {artifact_path} missing input for {video_id}")
    return item


def load_input_bundle(input_sha256: str) -> dict:
    """Load the analysis INPUT bundle from its content-addressed path."""
    path = houchen_paths.analysis_input_path(input_sha256)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def segments_for_validator(segments_rows: list[dict]) -> dict:
    """Project `transcript_segment` rows (dict form) into the
    `segments_by_ordinal` mapping the validator expects.

    Each row must contain at least `ordinal` and `text`; missing values
    default to empty string / 0 so a malformed row is rejected (Rule 1)
    rather than crashing the orchestrator.
    """
    out: dict[int, dict] = {}
    for row in segments_rows:
        out[int(row.get("ordinal", -1))] = {
            "ordinal": int(row.get("ordinal", -1)),
            "text": row.get("text", ""),
            "start_ms": int(row.get("start_ms", 0)),
            "end_ms": int(row.get("end_ms", 0)),
        }
    return out