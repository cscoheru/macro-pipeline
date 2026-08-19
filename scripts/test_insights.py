"""Fact-pack, provider, validator, renderer and publisher tests; no real API or Vault."""
import copy
import hashlib
import json
import os
import sqlite3
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import insight_context
import insight_provider
import insight_publisher
import insight_render
import insight_runner
import insight_validate
import ledger


def _seed_insight_case(conn):
    """Seed an insight scenario onto conn and return its metadata.

    Shared by the in-memory `insight_case` fixture and the file-backed
    run.py integration test, which needs a real multi-connection store
    (run.py's helpers open/close their own connections).
    """
    conn.execute("PRAGMA foreign_keys=ON")
    ledger.init_schema(conn)
    conn.execute(
        "CREATE TABLE observations (source TEXT, series TEXT, date TEXT, value REAL, "
        "PRIMARY KEY(source, series, date))"
    )
    conn.executemany(
        "INSERT INTO observations(source, series, date, value) VALUES (?,?,?,?)",
        [
            ("cn_pbc", "pbc_m2", "2026-05", 7.8),
            ("cn_pbc", "pbc_m2", "2026-06", 8.0),
            ("cn_stats_cpi", "cpi_yoy", "2026-05", 0.3),
            ("cn_stats_cpi", "cpi_yoy", "2026-06", 0.5),
        ],
    )
    evi_m2 = ledger.create_evidence_snapshot(
        conn, source_url="https://www.pbc.gov.cn/release", publisher="中国人民银行",
        published_at="2026-07", observed_period="2026-06",
        metric_id="cn_pbc:pbc_m2", value=8.0, unit="%同比",
        content_sha256="a" * 64, raw_path="/snapshot/pbc.txt",
        included=["M2同比8.0%"], missing=[],
    )
    evi_cpi = ledger.create_evidence_snapshot(
        conn, source_url="https://www.stats.gov.cn/release", publisher="国家统计局",
        published_at="2026-07", observed_period="2026-06",
        metric_id="cn_stats_cpi:cpi_yoy", value=0.5, unit="%同比",
        content_sha256="b" * 64, raw_path="/snapshot/cpi.txt",
        included=["CPI同比0.5%"], missing=[],
    )
    claim = ledger.create_claim(
        conn, statement="货币增速与消费价格存在背离", scope="中国·货币与价格",
        evidence_ids=[evi_m2, evi_cpi], alternatives=["需求恢复存在时滞"],
        confidence="中",
    )
    forecast = ledger.create_forecast(
        conn, claim_id=claim, metric_id="cn_m2_minus_cpi",
        target_period="2026-07", decision_rule="增速差低于7.5则背离收窄",
        review_due_at="2026-08-20", threshold=7.5, direction="below",
    )
    research = ledger.create_research_item(
        conn, queue_source="cross", title="M2与CPI增速差更新", claim_id=claim,
    )
    readings = {
        "cn_pbc:pbc_m2": {"yoy_pct": 8.0, "period": "2026-06"},
        "cn_stats_cpi:cpi_yoy": {"yoy_pct": 0.5, "period": "2026-06"},
    }
    fact_pack, digest = insight_context.build_fact_pack(
        conn, research_item_id=research, evidence_ids=[evi_m2, evi_cpi],
        readings=readings, flags=["M2-CPI增速差超过7.5个百分点"],
        forecast_ids=[forecast],
    )
    document = {
        "headline": "货币增速与消费价格背离仍需需求侧验证",
        "bottom_line": {
            "text": "截至2026-06，M2同比与CPI同比的预计算差为7.5个百分点，但单一背离不足以确认需求走向。",
            "as_of": "2026-06",
        },
        "what_changed": [
            {
                "statement": "M2同比为8.0%",
                "evidence_id": evi_m2,
                "current_value": 8.0,
                "previous_value": 7.8,
                "unit": "%同比",
                "comparison": "前值为7.8%",
            },
            {
                "statement": "CPI同比为0.5%",
                "evidence_id": evi_cpi,
                "current_value": 0.5,
                "previous_value": 0.3,
                "unit": "%同比",
                "comparison": "前值为0.3%",
            },
        ],
        "mechanism_chain": [
            {
                "kind": "derived",
                "statement": "Python预计算的增速差为7.5个百分点",
                "supporting_ids": [evi_m2, evi_cpi],
            },
            {
                "kind": "inferred",
                "statement": "背离可能意味着货币尚未充分传导至消费需求",
                "supporting_ids": [evi_m2, evi_cpi, claim],
            },
        ],
        "supporting_evidence": [
            {"id": evi_m2, "finding": "M2同比高于消费价格同比"},
            {"id": evi_cpi, "finding": "CPI同比仍处于较低水平"},
        ],
        "counter_evidence": [
            {"id": evi_cpi, "finding": "CPI仍是正增长，不能直接写成通缩"},
        ],
        "alternative_explanations": [
            {
                "explanation": "货币传导可能存在时间滞后",
                "falsifier": "后续消费价格与需求指标仍未改善",
            }
        ],
        "implications": [
            {
                "statement": "短期应继续核对需求数据而不是只看货币总量",
                "horizon": "near_term",
            }
        ],
        "next_checks": [
            {
                "metric": "M2与CPI增速差",
                "threshold": 7.5,
                "direction": "below",
                "target_period": "2026-07",
                "review_due_at": "2026-08-20",
                "source_id": forecast,
            }
        ],
        "confidence": "medium",
        "limitations": ["当前证据只覆盖货币与价格两本账，尚缺就业和财政验证"],
        "source_table": [
            {
                "evidence_id": evi_m2, "publisher": "中国人民银行",
                "period": "2026-06", "metric": "cn_pbc:pbc_m2", "unit": "%同比",
            },
            {
                "evidence_id": evi_cpi, "publisher": "国家统计局",
                "period": "2026-06", "metric": "cn_stats_cpi:cpi_yoy", "unit": "%同比",
            },
        ],
    }
    conn.commit()
    return {
        "fact_pack": fact_pack, "digest": digest,
        "document": document, "research": research, "readings": readings,
        "evidence": [evi_m2, evi_cpi],
    }


@pytest.fixture
def insight_case():
    conn = sqlite3.connect(":memory:")
    case = _seed_insight_case(conn)
    yield {"conn": conn, **case}
    conn.close()


def test_fact_pack_is_canonical_and_hash_sensitive(insight_case):
    case = insight_case
    again, digest = insight_context.build_fact_pack(
        case["conn"], research_item_id=case["research"],
        evidence_ids=case["evidence"], readings=case["readings"],
        flags=["M2-CPI增速差超过7.5个百分点"],
    )
    assert insight_context.canonical_json(again) == insight_context.canonical_json(case["fact_pack"])
    assert digest == case["digest"]
    assert again["derived_values"][0]["value"] == 7.5
    assert again["quality_gate"]["independent_publisher_count"] == 2

    changed = copy.deepcopy(case["readings"])
    changed["cn_stats_cpi:cpi_yoy"]["yoy_pct"] = 0.6
    _, changed_digest = insight_context.build_fact_pack(
        case["conn"], research_item_id=case["research"],
        evidence_ids=case["evidence"], readings=changed,
    )
    assert changed_digest != digest


def test_validator_accepts_grounded_document(insight_case):
    result = insight_validate.validate_output(
        insight_case["document"], insight_case["fact_pack"]
    )
    assert result.ok, result.errors
    assert set(insight_case["evidence"]).issubset(result.cited_ids)


def test_validator_rejects_source_table_metadata_drift(insight_case):
    doc = copy.deepcopy(insight_case["document"])
    doc["source_table"][0]["publisher"] = "央行"  # abbreviated, not verbatim
    result = insight_validate.validate_output(doc, insight_case["fact_pack"])
    assert not result.ok
    assert any("source_table[0] metadata" in e for e in result.errors)


def test_validator_rejects_non_primary_evidence(insight_case):
    pack = copy.deepcopy(insight_case["fact_pack"])
    pack["evidence"][0]["official_primary"] = False
    result = insight_validate.validate_output(insight_case["document"], pack)
    assert not result.ok
    assert any("non-primary evidence" in e for e in result.errors)


def test_validator_causal_requires_two_independent_publishers(insight_case):
    pack = copy.deepcopy(insight_case["fact_pack"])
    for ev in pack["evidence"]:
        ev["publisher"] = "中国人民银行"  # both evidence from one publisher
    result = insight_validate.validate_output(insight_case["document"], pack)
    assert not result.ok
    assert any("two independent publishers" in e for e in result.errors)


def test_validator_rejects_precise_crisis_countdown(insight_case):
    doc = copy.deepcopy(insight_case["document"])
    doc["bottom_line"]["text"] += "若不干预，预计3个月内将出现危机。"
    result = insight_validate.validate_output(doc, insight_case["fact_pack"])
    assert not result.ok
    assert any("precise crisis countdown" in e for e in result.errors)


def test_validator_rejects_bare_url_in_narrative(insight_case):
    doc = copy.deepcopy(insight_case["document"])
    doc["bottom_line"]["text"] += "详见 https://example.com/data。"
    result = insight_validate.validate_output(doc, insight_case["fact_pack"])
    assert not result.ok
    assert any("markdown links" in e for e in result.errors)


def test_review_note_sanitizes_model_output_embedded_in_errors(insight_case):
    note = insight_render.render_review_note(
        "ins_test", insight_case["fact_pack"],
        errors=["untraceable number '5' in text with ![img](https://evil.example/x)"],
        reason="validation failed",
    )
    # Model-controlled substring must not survive as renderable markdown.
    assert "![" not in note
    assert "](https" not in note


def test_runner_non_retryable_provider_failure_goes_to_review(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    provider = FakeProvider(error=insight_provider.ProviderError(
        "api key rejected", retryable=False, error_class="auth_failed"))
    writer = FakeVaultWriter()
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv", writer=writer,
    )
    assert outcome == "needs_review"
    assert ledger.current_status(conn, "generated_insight", ins_id) == "needs_review"
    assert f"待审/{ins_id}.md" in writer.store


def test_provider_envelope_missing_content_or_choices_is_invalid_response():
    with pytest.raises(insight_provider.ProviderError) as exc:
        insight_provider._extract_anthropic_json({})
    assert exc.value.error_class == "invalid_response"
    with pytest.raises(insight_provider.ProviderError):
        insight_provider._extract_openai_json({})
    with pytest.raises(insight_provider.ProviderError):
        insight_provider._extract_openai_json({"choices": []})


def test_ledger_current_statuses_matches_full_replay(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    ledger.transition(conn, "generated_insight", ins_id, "generating", "t", "x")
    conn.commit()
    batch = ledger.current_statuses(conn, "generated_insight")
    replayed = ledger.current_status(conn, "generated_insight", ins_id)
    assert batch[ins_id] == replayed == "generating"


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d["bottom_line"].update(text=d["bottom_line"]["text"] + " 另有99%增长。"),
         "untraceable number"),
        (lambda d: d["supporting_evidence"][0].update(id="evi_" + "f" * 32),
         "fabricated IDs"),
        (lambda d: d.update(counter_evidence=[]), "too few items"),
        (lambda d: d.update(headline="市场必然马上崩溃"), "prohibited certainty"),
        (lambda d: d["what_changed"][0].update(unit="亿元"), "unit does not match"),
        (lambda d: d.update(extra_path="../../manual-note.md"), "unexpected field"),
    ],
)
def test_validator_rejects_ungrounded_output(insight_case, mutate, expected):
    document = copy.deepcopy(insight_case["document"])
    mutate(document)
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert expected in " | ".join(result.errors)


def test_validator_returns_failure_instead_of_crashing_on_wrong_types(insight_case):
    """A malformed model output must produce a validation failure, never an exception."""
    document = copy.deepcopy(insight_case["document"])
    document["mechanism_chain"] = "not-an-array"
    document["next_checks"] = 7
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("mechanism_chain" in error or "next_checks" in error for error in result.errors)


def test_validator_rejects_fabricated_id_in_prose(insight_case):
    document = copy.deepcopy(insight_case["document"])
    fake = "evi_" + "f" * 32
    document["supporting_evidence"][0]["finding"] += f" 另见 {fake}。"
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("narrative references unknown ID" in error for error in result.errors)


def test_validator_rejects_scientific_notation_number(insight_case):
    """1e9 must not be tokenised as 1 (which fact_pack_version leaks into the pool)."""
    document = copy.deepcopy(insight_case["document"])
    document["bottom_line"]["text"] += " 隐含规模约1e9。"
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("untraceable number" in error for error in result.errors)


def test_validator_rejects_whitespace_only_narrative(insight_case):
    document = copy.deepcopy(insight_case["document"])
    document["limitations"] = ["        "]
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("empty or whitespace-only" in error for error in result.errors)


def test_validator_rejects_markdown_injection(insight_case):
    document = copy.deepcopy(insight_case["document"])
    document["headline"] = "背离跟踪 见 ![图](https://attacker.example/p.png)"
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("markdown" in error for error in result.errors)


def test_validator_rejects_causal_step_without_own_evidence(insight_case):
    """A derived step citing only the research item must not borrow global support."""
    document = copy.deepcopy(insight_case["document"])
    document["mechanism_chain"][0]["supporting_ids"] = [insight_case["research"]]
    result = insight_validate.validate_output(document, insight_case["fact_pack"])
    assert not result.ok
    assert any("needs two Evidence IDs" in error for error in result.errors)


def test_renderer_has_fixed_path_frontmatter_and_content_hash(insight_case, tmp_path):
    ins_id = "ins_" + "1" * 32
    rendered = insight_render.render_markdown(
        insight_case["document"], insight_case["fact_pack"], ins_id=ins_id,
        input_sha256=insight_case["digest"], prompt_version="prompt-v1",
        generated_at="2026-08-14T09:07:00+00:00",
    )
    assert rendered.vault_path == "洞察/2026/2026-06-" + "1" * 12 + ".md"
    assert ".." not in rendered.vault_path
    assert f'ins_id: "{ins_id}"' in rendered.content
    assert "## 反证与约束" in rendered.content
    assert rendered.content_sha256 == insight_context.content_sha256(rendered.content)
    path = insight_render.persist_artifact(rendered, str(tmp_path))
    assert os.path.basename(path) == f"{rendered.content_sha256}.md"
    assert insight_render.persist_artifact(rendered, str(tmp_path)) == path


def test_planned_vault_path_uses_random_tail_not_timestamp():
    """UUIDv7 shares its leading 12 hex across same-millisecond insights —
    the path suffix must come from the random tail or batch siblings collide."""
    id_a = "ins_" + "a" * 12 + "b" * 20
    id_b = "ins_" + "a" * 12 + "c" * 20
    path_a = insight_render.planned_vault_path(id_a, "2026-06")
    path_b = insight_render.planned_vault_path(id_b, "2026-06")
    assert path_a != path_b


class FakeResponse:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


def test_provider_retries_429_and_returns_structured_json(insight_case):
    calls = []
    responses = [
        FakeResponse(429, {}, {"retry-after": "0"}),
        FakeResponse(200, {
            "content": [{"type": "text", "text": json.dumps(insight_case["document"])}]
        }),
    ]

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return responses.pop(0)

    sleeps = []
    config = insight_provider.ProviderConfig(
        api_key="secret-never-in-body", base_url="https://api.example",
        max_retries=1,
    )
    provider = insight_provider.AnthropicInsightProvider(
        config, post=post, sleep=sleeps.append,
    )
    output = provider.generate(
        insight_case["fact_pack"], prompt="prompt", schema={"type": "object"},
    )
    assert output == insight_case["document"]
    assert len(calls) == 2 and sleeps == [0.0]
    assert "secret-never-in-body" not in json.dumps(calls[0]["json"])
    assert calls[0]["headers"]["x-api-key"] == "secret-never-in-body"


def test_provider_errors_do_not_leak_response_or_secret(insight_case):
    def post(url, **kwargs):
        return FakeResponse(400, {"error": "secret-token echoed by upstream"})

    provider = insight_provider.AnthropicInsightProvider(
        insight_provider.ProviderConfig(api_key="secret-token", max_retries=0),
        post=post,
    )
    with pytest.raises(insight_provider.ProviderError) as error:
        provider.generate(insight_case["fact_pack"], prompt="p", schema={"type": "object"})
    assert "secret-token" not in str(error.value)


def test_provider_network_failure_is_retryable(insight_case):
    def post(url, **kwargs):
        raise requests.ConnectionError("offline")

    provider = insight_provider.AnthropicInsightProvider(
        insight_provider.ProviderConfig(api_key="x", max_retries=0), post=post,
    )
    with pytest.raises(insight_provider.ProviderError) as error:
        provider.generate(insight_case["fact_pack"], prompt="p", schema={"type": "object"})
    assert error.value.retryable
    assert error.value.error_class == "network_error"


def test_env_file_requires_private_permissions(tmp_path):
    env_file = tmp_path / "insight.env"
    env_file.write_text("ANTHROPIC_API_KEY=test\nINSIGHT_MAX_RETRIES=0\n", encoding="utf-8")
    os.chmod(env_file, 0o644)
    with pytest.raises(insight_provider.ConfigurationError, match="permissions"):
        insight_provider.load_config(str(env_file), environ={})
    os.chmod(env_file, 0o600)
    config = insight_provider.load_config(str(env_file), environ={})
    assert config.api_key == "test"
    assert config.max_retries == 0


# ---------------------------------------------------------------------------
# DeepSeek (OpenAI-compatible) provider
# ---------------------------------------------------------------------------

def _ds_config(**overrides):
    base = dict(provider="deepseek", api_key="ds-secret",
                base_url="https://api.deepseek.com", model="deepseek-chat",
                max_retries=1)
    base.update(overrides)
    return insight_provider.ProviderConfig(**base)


def test_deepseek_retries_429_and_parses_openai_content(insight_case):
    calls = []
    responses = [
        FakeResponse(429, {}, {"retry-after": "0"}),
        FakeResponse(200, {"choices": [{"message": {
            "content": json.dumps(insight_case["document"], ensure_ascii=False),
        }}]}),
    ]

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return responses.pop(0)

    sleeps = []
    provider = insight_provider.DeepSeekInsightProvider(
        _ds_config(), post=post, sleep=sleeps.append,
    )
    output = provider.generate(
        insight_case["fact_pack"], prompt="prompt", schema={"type": "object"},
    )
    assert output == insight_case["document"]
    assert len(calls) == 2 and sleeps == [0.0]
    # OpenAI-compatible auth + endpoint; key in header only, never in body.
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer ds-secret"
    assert "ds-secret" not in json.dumps(calls[0]["json"])
    # json_object mode requested; streaming off.
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert calls[0]["json"]["stream"] is False


def test_deepseek_tolerates_code_fenced_json(insight_case):
    fenced = "```json\n" + json.dumps(insight_case["document"]) + "\n```"

    def post(url, **kwargs):
        return FakeResponse(200, {"choices": [{"message": {"content": fenced}}]})

    provider = insight_provider.DeepSeekInsightProvider(
        _ds_config(max_retries=0), post=post, sleep=lambda _s: None,
    )
    assert provider.generate(
        insight_case["fact_pack"], prompt="p", schema={"type": "object"},
    ) == insight_case["document"]


def test_deepseek_invalid_json_is_retryable_classified_error(insight_case):
    def post(url, **kwargs):
        return FakeResponse(200, {"choices": [{"message": {"content": "not json"}}]})

    provider = insight_provider.DeepSeekInsightProvider(
        _ds_config(max_retries=0), post=post, sleep=lambda _s: None,
    )
    with pytest.raises(insight_provider.ProviderError) as error:
        provider.generate(insight_case["fact_pack"], prompt="p", schema={"type": "object"})
    assert error.value.error_class == "invalid_json"


def test_build_provider_factory_selects_by_config_provider():
    ds = insight_provider.build_provider(_ds_config(max_retries=0))
    assert isinstance(ds, insight_provider.DeepSeekInsightProvider)
    an = insight_provider.build_provider(insight_provider.ProviderConfig(
        provider="anthropic", api_key="x", max_retries=0))
    assert isinstance(an, insight_provider.AnthropicInsightProvider)


def test_load_config_selects_deepseek_and_requires_its_key(tmp_path):
    env_file = tmp_path / "insight.env"
    env_file.write_text(
        "INSIGHT_PROVIDER=deepseek\nDEEPSEEK_API_KEY=dk-test\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com\nINSIGHT_MODEL=deepseek-reasoner\n",
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)
    cfg = insight_provider.load_config(str(env_file), environ={})
    assert cfg.provider == "deepseek"
    assert cfg.api_key == "dk-test"
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.model == "deepseek-reasoner"

    env_file.write_text("INSIGHT_PROVIDER=deepseek\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    with pytest.raises(insight_provider.ConfigurationError, match="DEEPSEEK_API_KEY"):
        insight_provider.load_config(str(env_file), environ={})


def test_load_config_selects_minimax_and_requires_its_key(tmp_path):
    env_file = tmp_path / "insight.env"
    env_file.write_text(
        "INSIGHT_PROVIDER=minimax\nMINIMAX_API_KEY=mk-test\n"
        "MINIMAX_BASE_URL=https://api.minimaxi.com/v1\nINSIGHT_MODEL=MiniMax-Text-01\n",
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)
    cfg = insight_provider.load_config(str(env_file), environ={})
    assert cfg.provider == "minimax"
    assert cfg.api_key == "mk-test"
    assert cfg.base_url == "https://api.minimaxi.com/v1"
    assert cfg.model == "MiniMax-Text-01"

    env_file.write_text("INSIGHT_PROVIDER=minimax\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    with pytest.raises(insight_provider.ConfigurationError, match="MINIMAX_API_KEY"):
        insight_provider.load_config(str(env_file), environ={})


def test_build_provider_factory_selects_minimax():
    cfg = insight_provider.ProviderConfig(
        provider="minimax", api_key="mk-test", max_retries=0,
    )
    p = insight_provider.build_provider(cfg)
    assert isinstance(p, insight_provider.MiniMaxInsightProvider)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

_UNSET = object()


def _ready_insight(conn, tmp_path, content="hello vault",
                   path="洞察/2026/test.md", supersedes_id=None):
    research = ledger.create_research_item(conn, queue_source="cross", title="t")
    # Unique input sha per (content, path): create_generated_insight dedupes
    # on (input_sha256, prompt_version, model), so a fixed sha would alias
    # two insights in the same test.
    input_sha = hashlib.sha256(f"{path}:{content}".encode("utf-8")).hexdigest()
    ins_id = ledger.create_generated_insight(
        conn, research_item_id=research, input_sha256=input_sha,
        prompt_version="pv", generator="test", model="test-model",
        planned_vault_path=path, supersedes_id=supersedes_id,
    )
    art = tmp_path / "art.md"
    art.write_text(content, encoding="utf-8")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    ledger.create_insight_artifact(
        conn, ins_id=ins_id, content_sha256=sha, local_path=str(art),
        validation={"ok": True},
    )
    ledger.transition(conn, "generated_insight", ins_id, "generating", "tester", "claimed")
    ledger.transition(conn, "generated_insight", ins_id, "ready", "tester", "ready")
    conn.commit()
    return ins_id, sha


class FakeVaultWriter:
    def __init__(self, *, put_error=None, get_override=_UNSET, readback_corrupt=False):
        self.store = {}
        self.put_error = put_error
        self.get_override = get_override
        self.readback_corrupt = readback_corrupt
        self.put_count = 0

    def put_pipeline(self, rel_path, content):
        self.put_count += 1
        if self.put_error:
            raise self.put_error
        self.store[rel_path] = content
        return 204

    def get_pipeline(self, rel_path):
        if self.get_override is not _UNSET:
            return self.get_override
        if self.readback_corrupt:
            return (self.store.get(rel_path) or "") + "tampered"
        return self.store.get(rel_path)


def test_publisher_supersedes_predecessor_on_revision_publish(tmp_path):
    """A revision article carrying supersedes_id retires its published
    predecessor once the revision itself is durably published."""
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    writer = FakeVaultWriter()

    # Predecessor: published article citing evidence of fred:FEDFUNDS.
    evi = ledger.create_evidence_snapshot(
        conn, source_url="https://fred.stlouisfed.org/series/FEDFUNDS",
        publisher="FRED (St. Louis Fed)", published_at="2026-07",
        observed_period="2026-07", metric_id="fred:FEDFUNDS", value=3.63,
        unit="%", content_sha256="e" * 64, raw_path="snap.csv",
        included=["FEDFUNDS=3.63"], missing=[])
    old_id, _ = _ready_insight(conn, tmp_path, content="old article",
                               path="洞察/2026/old.md")
    ledger.create_insight_provenance(
        conn, ins_id=old_id, source_type="evidence_snapshot", source_id=evi,
        role="evidence", ordinal=0)
    insight_publisher.publish(conn, ins_id=old_id, writer=writer)
    assert ledger.current_status(conn, "generated_insight", old_id) == "published"
    assert ledger.latest_published_for_metrics(conn, ["fred:FEDFUNDS"]) == old_id

    # Revision article supersedes the old one (set at queue time, not UPDATE —
    # generated_insight rows are trigger-guarded against UPDATE).
    new_id, _ = _ready_insight(conn, tmp_path, content="revised article",
                               path="洞察/2026/new.md", supersedes_id=old_id)
    insight_publisher.publish(conn, ins_id=new_id, writer=writer)
    assert ledger.current_status(conn, "generated_insight", new_id) == "published"
    assert ledger.current_status(conn, "generated_insight", old_id) == "superseded"


def test_publisher_leaves_unpublished_predecessor_alone(tmp_path):
    """supersedes_id pointing at a never-published insight is a no-op."""
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    writer = FakeVaultWriter()
    old_id, _ = _ready_insight(conn, tmp_path, content="stuck in review",
                               path="洞察/2026/stuck.md")
    ledger.transition(conn, "generated_insight", old_id, "needs_review",
                      "tester", "gate failed")
    conn.commit()
    new_id, _ = _ready_insight(conn, tmp_path, content="revision",
                               path="洞察/2026/rev.md", supersedes_id=old_id)
    insight_publisher.publish(conn, ins_id=new_id, writer=writer)
    assert ledger.current_status(conn, "generated_insight", new_id) == "published"
    # Old one keeps needs_review — only published articles get superseded.
    assert ledger.current_status(conn, "generated_insight", old_id) == "needs_review"


def test_publisher_publishes_ready_insight_and_verifies_readback(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    ins_id, _ = _ready_insight(conn, tmp_path)
    writer = FakeVaultWriter()
    assert insight_publisher.publish(conn, ins_id=ins_id, writer=writer) is True
    assert ledger.current_status(conn, "generated_insight", ins_id) == "published"
    assert writer.store["洞察/2026/test.md"] == "hello vault"
    assert writer.put_count == 1


def test_publisher_is_idempotent_when_already_published(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    ins_id, _ = _ready_insight(conn, tmp_path)
    writer = FakeVaultWriter()
    insight_publisher.publish(conn, ins_id=ins_id, writer=writer)
    # Re-publishing must not PUT again and stays True.
    assert insight_publisher.publish(conn, ins_id=ins_id, writer=writer) is True
    assert writer.put_count == 1


def test_publisher_put_failure_keeps_ready_and_is_retryable(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    ins_id, _ = _ready_insight(conn, tmp_path)
    writer = FakeVaultWriter(put_error=RuntimeError("obsidian offline"))
    with pytest.raises(insight_publisher.PublishError) as exc:
        insight_publisher.publish(conn, ins_id=ins_id, writer=writer)
    assert exc.value.retryable
    assert ledger.current_status(conn, "generated_insight", ins_id) == "ready"


def test_publisher_readback_mismatch_is_retryable(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    ins_id, _ = _ready_insight(conn, tmp_path)
    writer = FakeVaultWriter(readback_corrupt=True)
    with pytest.raises(insight_publisher.PublishError) as exc:
        insight_publisher.publish(conn, ins_id=ins_id, writer=writer)
    assert exc.value.retryable
    assert "readback" in exc.value.error_class
    assert ledger.current_status(conn, "generated_insight", ins_id) == "ready"


def test_publisher_rejects_non_ready_state(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    research = ledger.create_research_item(conn, queue_source="cross", title="t")
    ins_id = ledger.create_generated_insight(
        conn, research_item_id=research, input_sha256="b" * 64,
        prompt_version="pv", generator="test", model="m",
        planned_vault_path="洞察/2026/x.md",
    )
    conn.commit()  # left in 'queued' state
    writer = FakeVaultWriter()
    with pytest.raises(insight_publisher.PublishError) as exc:
        insight_publisher.publish(conn, ins_id=ins_id, writer=writer)
    assert exc.value.error_class == "invalid_state"


def test_publisher_detects_corrupt_artifact_before_put(tmp_path):
    conn = sqlite3.connect(":memory:")
    ledger.init_schema(conn)
    ins_id, _ = _ready_insight(conn, tmp_path, content="original")
    (tmp_path / "art.md").write_text("tampered content", encoding="utf-8")
    writer = FakeVaultWriter()
    with pytest.raises(insight_publisher.PublishError) as exc:
        insight_publisher.publish(conn, ins_id=ins_id, writer=writer)
    assert exc.value.error_class == "corrupt_artifact"
    assert writer.put_count == 0
    assert ledger.current_status(conn, "generated_insight", ins_id) == "ready"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _queued_insight_for(conn, fact_pack, input_sha=None):
    research = ledger.create_research_item(conn, queue_source="cross", title="t")
    sha = input_sha or insight_context.content_sha256(fact_pack)
    ins_id = ledger.new_id("generated_insight")
    path = insight_render.planned_vault_path(ins_id, fact_pack["as_of"])
    created = ledger.create_generated_insight(
        conn, research_item_id=research, input_sha256=sha,
        prompt_version="pv", generator="test", model="test-model",
        planned_vault_path=path, ins_id=ins_id,
    )
    conn.commit()
    assert created == ins_id  # caller-supplied id is honored
    return ins_id


class FakeProvider:
    def __init__(self, document=None, error=None):
        self.document = document
        self.error = error

    def generate(self, fact_pack, *, prompt=None, schema=None):
        if self.error:
            raise self.error
        return copy.deepcopy(self.document)


def test_runner_process_one_generates_validates_and_advances_to_ready(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    provider = FakeProvider(document=insight_case["document"])
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
        generated_at="2026-08-14T09:07:00+00:00",
    )
    assert outcome == "ready"
    assert ledger.current_status(conn, "generated_insight", ins_id) == "ready"
    row = conn.execute(
        "SELECT content_sha256 FROM insight_artifact WHERE ins_id=?", (ins_id,),
    ).fetchone()
    assert row is not None


def test_runner_validation_failure_goes_to_needs_review(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    bad = copy.deepcopy(insight_case["document"])
    bad["headline"] = "市场必然马上崩溃"  # prohibited certainty -> validation fail
    provider = FakeProvider(document=bad)
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
        generated_at="2026-08-14T09:07:00+00:00",
    )
    assert outcome == "needs_review"
    assert ledger.current_status(conn, "generated_insight", ins_id) == "needs_review"
    # No artifact should be registered for a failed validation.
    row = conn.execute(
        "SELECT 1 FROM insight_artifact WHERE ins_id=?", (ins_id,),
    ).fetchone()
    assert row is None


def test_runner_retryable_provider_failure_requeues(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    provider = FakeProvider(error=insight_provider.ProviderError(
        "provider offline", retryable=True, error_class="network_error"))
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
    )
    assert outcome == "queued"
    assert ledger.current_status(conn, "generated_insight", ins_id) == "queued"


def test_runner_fact_pack_hash_mismatch_stays_queued(insight_case):
    conn = insight_case["conn"]
    # Queue with a sha that does NOT match the supplied fact pack.
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"], input_sha="0" * 64)
    provider = FakeProvider(document=insight_case["document"])
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
    )
    assert outcome == "queued"
    assert ledger.current_status(conn, "generated_insight", ins_id) == "queued"
    # Provider must never have been called against an unverified input.
    assert provider.document is insight_case["document"]


def test_runner_drain_publishes_ready_insight_end_to_end(insight_case):
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    provider = FakeProvider(document=insight_case["document"])
    writer = FakeVaultWriter()

    def loader(_ins_id, _sha):
        return insight_case["fact_pack"]

    summary = insight_runner.drain(
        conn, provider=provider, writer=writer, fact_pack_loader=loader,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
        auto_publish=True,
    )
    assert summary["published"] == 1
    assert ledger.current_status(conn, "generated_insight", ins_id) == "published"
    assert writer.put_count == 1


def test_runner_generate_runs_without_open_transaction(insight_case):
    """commit-before-generate: the 90s model call must not hold the write lock."""
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    seen = {}

    class LockProbeProvider(FakeProvider):
        def generate(self, fact_pack, *, prompt=None, schema=None):
            seen["in_transaction"] = conn.in_transaction
            return super().generate(fact_pack, prompt=prompt, schema=schema)

    provider = LockProbeProvider(document=insight_case["document"])
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
    )
    assert outcome == "ready"
    assert seen["in_transaction"] is False


def test_runner_drain_recovers_stuck_generating(insight_case):
    """A crash between 'generating' and the next transition is requeued on drain."""
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    ledger.transition(conn, "generated_insight", ins_id, "generating",
                      "test", "simulated crash mid-generate")
    conn.commit()

    requeued = insight_runner.recover_stuck_generating(conn)
    assert ins_id in requeued
    assert ledger.current_status(conn, "generated_insight", ins_id) == "queued"
    # Idempotent: nothing stuck the second time.
    assert insight_runner.recover_stuck_generating(conn) == []


def test_runner_drain_missing_fact_pack_is_failed_not_crashed(insight_case):
    conn = insight_case["conn"]
    _queued_insight_for(conn, insight_case["fact_pack"])
    provider = FakeProvider(document=insight_case["document"])
    writer = FakeVaultWriter()

    def loader(_ins_id, _sha):
        raise FileNotFoundError("fact pack not persisted")

    summary = insight_runner.drain(
        conn, provider=provider, writer=writer, fact_pack_loader=loader,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
    )
    assert summary["failed"] == 1
    assert summary["published"] == 0


def test_summarize_counts_states_backlog_and_error():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    ledger.init_schema(conn)
    fact_pack = {"as_of": "2026-06"}
    queued_id = _queued_insight_for(conn, fact_pack)
    ready_id = _queued_insight_for(conn, {"as_of": "2026-05"})
    review_id = _queued_insight_for(conn, {"as_of": "2026-04"})
    # transition to 'ready' requires an artifact row (state machine enforces it).
    ledger.create_insight_artifact(
        conn, ins_id=ready_id, content_sha256="c" * 64,
        local_path="/tmp/dummy-insight-artifact.md", validation={"ok": True},
    )
    ledger.transition(conn, "generated_insight", ready_id, "generating", "system", "g")
    ledger.transition(conn, "generated_insight", ready_id, "ready", "system", "r")
    ledger.transition(conn, "generated_insight", review_id, "generating", "system", "g")
    ledger.transition(conn, "generated_insight", review_id, "needs_review",
                      "system", "validation failed")
    ledger.record_insight_attempt(
        conn, ins_id=review_id, stage="validate", outcome="needs_review",
        error_class="validation_failed", detail="missing counter",
    )
    conn.commit()

    s = insight_runner.summarize(conn)
    assert s["queued"] == 1
    assert s["ready"] == 1
    assert s["needs_review"] == 1
    assert s["published"] == 0
    assert s["generating"] == 0
    assert s["superseded"] == 0
    expected_oldest = conn.execute(
        "SELECT created_at FROM generated_insight WHERE ins_id=?", (queued_id,),
    ).fetchone()[0]
    assert s["oldest_queued_created_at"] == expected_oldest
    assert s["last_error_class"] == "validation_failed"


def test_runpy_queue_then_runner_drain_end_to_end(monkeypatch, tmp_path):
    """run.py _queue_source_insight -> runner drain -> publisher, against a
    file-backed store, mock provider and fake writer. No real DB / Vault / API.

    run.py's queue helper opens its own connection and closes it in finally, so
    we back store._connect with a temp file (multi-connection, like the real
    store) rather than a single :memory: conn.
    """
    import run as runmod
    db_path = tmp_path / "store.db"

    def fake_connect():
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(runmod.store, "_connect", fake_connect)
    monkeypatch.setattr(runmod.paths, "INSIGHT_FACTS", str(tmp_path / "facts"))
    monkeypatch.setattr(runmod.paths, "INSIGHT_ARTIFACTS", str(tmp_path / "artifacts"))

    seed_conn = fake_connect()
    case = _seed_insight_case(seed_conn)
    seed_conn.close()

    rit = case["research"]
    updates = [{"evi_id": evi} for evi in case["evidence"]]
    ins_id = runmod._queue_source_insight(
        "cross", updates, flags=["M2-CPI增速差超过7.5个百分点"],
        cache=case["readings"], rit_id=rit)
    assert ins_id is not None

    # The queued row + provenance are visible from a fresh connection.
    drain_conn = fake_connect()
    assert ledger.current_status(drain_conn, "generated_insight", ins_id) == "queued"
    count = drain_conn.execute(
        "SELECT COUNT(*) FROM insight_provenance WHERE ins_id=?", (ins_id,),
    ).fetchone()[0]
    assert count == len(case["evidence"])
    stored_sha = drain_conn.execute(
        "SELECT input_sha256 FROM generated_insight WHERE ins_id=?", (ins_id,),
    ).fetchone()[0]
    assert os.path.exists(os.path.join(str(tmp_path / "facts"), f"{stored_sha}.json"))

    # Drain via the runner with a mock provider + fake writer, bypassing
    # _drain_insights' load_config() (which needs a real API key).
    provider = FakeProvider(document=case["document"])
    writer = FakeVaultWriter()
    summary = insight_runner.drain(
        drain_conn, provider=provider, writer=writer,
        prompt="p", schema={"type": "object"}, prompt_version="pv",
        auto_publish=True,
    )
    assert summary["published"] == 1
    assert ledger.current_status(drain_conn, "generated_insight", ins_id) == "published"
    assert writer.put_count == 1
    drain_conn.close()


def test_persist_response_is_content_addressed_and_idempotent(tmp_path):
    store = tmp_path / "responses"
    doc = {"headline": "测试", "value": 7.5, "nested": {"k": ["a", "b"]}}
    path, sha = insight_render.persist_response(doc, directory=str(store))
    assert sha == hashlib.sha256(
        json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert os.path.basename(path) == f"{sha}.json"
    assert os.path.exists(path)
    assert oct(os.stat(path).st_mode)[-3:] == "600"
    # Idempotent: identical content returns the same path/sha, no duplicate.
    path2, sha2 = insight_render.persist_response(doc, directory=str(store))
    assert (path2, sha2) == (path, sha)
    # Different content -> a distinct content-addressed file.
    path3, sha3 = insight_render.persist_response(
        {**doc, "value": 8.0}, directory=str(store))
    assert sha3 != sha
    assert os.path.exists(path3)


def test_render_review_note_lists_reason_errors_and_response():
    fact_pack = {"as_of": "2026-06", "evidence": [{"id": "evi_a"}]}
    note = insight_render.render_review_note(
        "ins_deadbeef", fact_pack,
        errors=["prohibited certainty language: 必然", "untraceable number '9'"],
        reason="validation failed",
        response_path="/data/insights/responses/abc.json", response_sha="abc",
    )
    assert "待人工复核" in note
    assert "validation failed" in note
    assert "prohibited certainty language: 必然" in note
    assert "evi_a" in note
    assert "/data/insights/responses/abc.json" in note
    assert "abc" in note
    # No response section when the response path is omitted (e.g. provider error).
    note2 = insight_render.render_review_note(
        "ins_deadbeef", fact_pack, errors=["boom"],
        reason="provider failure: bad_json",
    )
    assert "模型原始响应" not in note2


def test_validator_exempts_bare_year_but_not_untraceable_numbers(insight_case):
    base = insight_case["document"]
    fact_pack = insight_case["fact_pack"]
    # A standalone four-digit year in narrative prose is a date, not a statistic.
    with_year = copy.deepcopy(base)
    with_year["limitations"].append("这是2026年的观察窗口")
    assert insight_validate.validate_output(with_year, fact_pack).ok
    # A genuinely untraceable number is still rejected by the number gate.
    with_num = copy.deepcopy(base)
    with_num["limitations"].append("出现999这个无法溯源的数字")
    result = insight_validate.validate_output(with_num, fact_pack)
    assert not result.ok
    assert any("untraceable number" in e for e in result.errors)


def test_validator_exempts_bare_month_in_date_ranges(insight_case):
    base = insight_case["document"]
    fact_pack = insight_case["fact_pack"]
    # A month-only fragment like "至7月" (left after stripping "2026年5月" from
    # "2026年5月至7月") is a date, not a statistic of 7 units.
    with_range = copy.deepcopy(base)
    with_range["limitations"].append("历史窗口为2026年5月至7月，区间内数值平稳")
    result = insight_validate.validate_output(with_range, fact_pack)
    assert result.ok, result.errors
    assert not any("untraceable number '7'" in e for e in result.errors)


def test_runner_needs_review_writes_review_note_with_response(
        insight_case, tmp_path, monkeypatch):
    # Redirect the response store so the test never touches the real data dir.
    monkeypatch.setattr(insight_render.paths, "INSIGHT_RESPONSES", str(tmp_path / "responses"))
    conn = insight_case["conn"]
    ins_id = _queued_insight_for(conn, insight_case["fact_pack"])
    bad = copy.deepcopy(insight_case["document"])
    bad["headline"] = "市场必然马上崩溃"  # prohibited certainty -> needs_review
    writer = FakeVaultWriter()
    provider = FakeProvider(document=bad)
    outcome = insight_runner.process_one(
        conn, ins_id=ins_id, fact_pack=insight_case["fact_pack"], provider=provider,
        prompt="p", schema={"type": "object"}, prompt_version="pv", writer=writer,
    )
    assert outcome == "needs_review"
    # The review note is written to the vault writer with failure reasons.
    note = writer.store.get(f"待审/{ins_id}.md")
    assert note is not None
    assert "validation failed" in note
    assert "必然" in note
    # The raw model response was persisted BEFORE validation (even malformed
    # output is captured) and its local path is cited in the review note.
    files = list((tmp_path / "responses").glob("*.json"))
    assert len(files) == 1
    assert str(files[0]) in note
