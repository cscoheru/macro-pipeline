# PR-3 — 世界苦茶研究库：Atomic Claim Extraction + Concept Seeding

## Context

PR-1 (corpus foundation) + PR-2 (transcript normalizer) 已交付并 commit (`15db01e`)；用户验收（`COMMIT_VERIFIED_2026-08-24.md`）+ Live smoke PASS。

PR-3 是 brief §9 的 Analysis Contract 层：在 PR-2 的 transcript_version / transcript_segment 之上，
跑 LLM 分析，提取**原子主张 (atomic claim)**、**概念 (concept)**、**论证边 (reasoning edge)**、
**证据提及 (evidence mention)**，经**硬校验器**过滤后写入正式表。三层分离 (`speaker_statement` /
`speaker_reasoning` / `system_evaluation`) 是硬门禁。

PR-3 是 brief 第 3 大节「目标 5：严格分离三层」和 brief §9 Analysis Contract 的核心实现。
约束：

- 不修改 brief / PR-1 红线 / PR-2 行为
- 不调用真实模型（默认 fake provider；真模型走 ENGINEERING_TEST_PLAN §10 的 eval 流程）
- 不弱化 brief §9.3 的硬校验（10 条规则任一违反 → needs_review 或 per-item reject）
- 不自动判定预测命中/失败、不自动 promote proposed → canonical
- `claim_source.exact_quote` 严格走 `houchen_quote.exact_quote_in_segment`（brief §8.6 hard gate）

## Approach

镜像 PR-1 + PR-2 的分层（schema → migrations → paths → 业务模块 → runner → status → CLI → tests），
**模块数突破 brief §7.7 的 8 个上限，需要在 PR1_HANDOFF §10.2 记录拆分理由**：

| 模块 | 拆分理由 |
|------|---------|
| `houchen_analyzer` (NEW) | 分析 input bundle 构造 + LLM 调用编排（单一职责：与 provider 对接）|
| `houchen_validator` (NEW) | brief §9.3 硬校验器是纯函数；分离便于单测和审计；将来可被 PR-4 复用 |
| `houchen_concept` (NEW) | concept 生命周期（proposed → canonical / alias merge）与 claim 抽取解耦 |
| `houchen_prompt` (NEW) | prompt + JSON schema 模板管理（brief §9.2 强制 schema 版本化）|

合计：PR-2 = 9 个 lib；PR-3 = +4 = 13 个。**已在 plan 中固定记录**，与 brief §7.7 「必要时拆分但需说明」一致。

### 1. Schema (v3 migration)

**File**: `lib/houchen_schema.py` — 扩展 `_V3_*` 验证结构 + `_V3_STATEMENTS`。模式严格镜像 PR-2 v2。

新表（brief §7.2）：
- `domain(slug TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT)` — 固定领域骨架（6 个 seed）
- `concept(concept_id TEXT PK, definition TEXT, status TEXT CHECK IN ('proposed','canonical','deprecated'), origin TEXT CHECK IN ('seed','corpus','human'), first_seen_at TEXT, last_seen_at TEXT)` — **新发现自动 = 'proposed'**（brief §7.2）
- `concept_alias(alias_id PK, concept_id FK, alias TEXT, source TEXT, created_at TEXT, UNIQUE(concept_id, alias))`
- `concept_domain(concept_id FK, domain_slug FK, PRIMARY KEY(concept_id, domain_slug))` — m2m（brief §7.2「骨架是导航，不强迫单领域」）
- `concept_source(concept_id, transcript_version_id, segment_start_ordinal, segment_end_ordinal, start_ms, end_ms, exact_quote, timestamp_url, raw_caption_sha256, source_role TEXT CHECK IN ('canonical_definition','usage','speaker_definition'))` — 等价字段如 `claim_source`
- `claim(claim_id PK, video_id FK, claim_text TEXT NOT NULL CHECK(claim_text != ''), claim_type TEXT CHECK IN ('definition','descriptive','causal','predictive','normative','interpretive'), speaker TEXT, layer TEXT CHECK IN ('speaker_statement','speaker_reasoning','system_evaluation') NOT NULL, temporal_scope TEXT, modality TEXT, status TEXT CHECK IN ('proposed','accepted','needs_review','rejected'), analysis_run_id FK, created_at TEXT, UNIQUE(claim_id))` — **`speaker_statement` 的 `speaker` 必须已知；未知则强制 needs_review**
- `claim_source(claim_id FK, transcript_version_id FK, segment_start_ordinal INTEGER, segment_end_ordinal INTEGER, start_ms INTEGER CHECK(start_ms >= 0), end_ms INTEGER CHECK(end_ms >= start_ms), exact_quote TEXT NOT NULL, timestamp_url TEXT NOT NULL, raw_caption_sha256 TEXT NOT NULL, PRIMARY KEY(claim_id, segment_start_ordinal))` — **`exact_quote` 必须通过 `houchen_quote.exact_quote_in_segment`（brief §9.3 hard rule）**
- `claim_concept(claim_id, concept_id, relation TEXT CHECK IN ('defines','uses','exemplifies','qualifies','relates'), analysis_run_id, PRIMARY KEY(claim_id, concept_id))`
- `reasoning_edge(from_claim_id, to_claim_id, relation TEXT CHECK IN ('supports','causes','qualifies','contradicts','predicts','defines','exemplifies'), layer TEXT CHECK IN ('speaker_reasoning','system_evaluation') NOT NULL, source_id TEXT, transcript_version_id, exact_quote TEXT, start_ms, end_ms, timestamp_url, analysis_run_id, PRIMARY KEY(from_claim_id, to_claim_id, relation))` — **`speaker_reasoning` 边必须有 transcript_version_id + exact_quote；`system_evaluation` 边必须有 analysis_run_id 标注**
- `evidence_mention(mention_id PK, video_id FK, transcript_version_id, segment_ordinal INTEGER, text TEXT, mention_type TEXT CHECK IN ('data','example','analogy','reference','quote_external'), external_entity_candidate TEXT, created_at TEXT)`
- `external_evidence(evidence_id PK, source_url TEXT, local_data_key TEXT, publisher TEXT, observed_period TEXT, fetched_at TEXT, content_sha256 TEXT NOT NULL, grade TEXT CHECK IN ('A','B','C','D'))`
- `evaluation(evaluation_id PK, target_kind TEXT CHECK IN ('claim','reasoning_edge'), target_id TEXT NOT NULL, evaluator TEXT CHECK IN ('human','model','macro_bridge') NOT NULL, as_of TEXT, verdict TEXT CHECK IN ('confirmed','contested','partial','pending'), reasoning TEXT, status TEXT CHECK IN ('draft','final','superseded'), external_evidence_id TEXT, created_at TEXT)`
- `forecast(forecast_id PK, claim_id FK, time_window_start TEXT, time_window_end TEXT, outcome_condition TEXT NOT NULL CHECK(outcome_condition != ''), status TEXT CHECK IN ('candidate','verified_hit','failed','superseded','withdrawn') NOT NULL DEFAULT 'candidate', evaluated_at TEXT, evaluated_by TEXT)`

同时 v3 把 `corpus_run.kind` 扩到包含 `'analyze' | 'validate' | 'concept_seed'`；`corpus_attempt.stage` 扩到包含 `'analyze' | 'validate' | 'concept_seed'`。

### 2. Migration

**File**: `lib/houchen_migrations.py` — 镜像 `_apply_v3()` 模式：
`BEGIN IMMEDIATE` → 版本检查 → DDL + 扩 CHECK（rename → create → copy → drop → index，**复用 PR-2 已固化的索引顺序陷阱**）→ `validate_schema(conn)` 全表校验 → 写 `schema_version` 行 → COMMIT。

`LATEST_VERSION = houchen_schema.VERSION = 3`。

### 3. Paths

**File**: `lib/houchen_paths.py` — 新增（**全部走 `assert_no_symlink_components` + `_reject_symlink_ancestors`**）：
```python
def analysis_input_path(input_sha256: str) -> str
    # <root>/artifacts/analysis/inputs/<sha[:2]>/<sha>.json
def analysis_artifact_path(run_id: str) -> str
    # <root>/artifacts/analysis/runs/<run_id>.json
def prompt_template_path(name: str, version: str) -> str
    # <root>/prompts/<name>-<version>.md  (可空)
def concept_failure_path(run_id: str, video_id: str) -> str
    # <root>/failures/<run_id>/<video_id>.json
```

### 4. Prompt + schema 模块（NEW）

**File**: `lib/houchen_prompt.py`（NEW，~80 行）：
- `PROMPT_VERSION = "2026-08-24.1"`、`SCHEMA_VERSION = "claim_extraction_v1"`
- `build_analysis_input(*, video_id, transcript_version, segments, domain_skeleton, prompt_version, schema_version, model, provider) → dict`：内容寻址的 input bundle（video_id + transcript_version + segment 列表 + 7 个领域 slug + prompt/schema version + model/provider 标识）。**禁止在 input 中塞任何 secret、API key、user-specific 数据**。
- `input_sha256(payload) → str`：canonical SHA，对同一输入 + 同一 prompt/schema version 必须稳定。
- `analysis_input_json_schema() → dict`：JSON Schema 定义 brief §9.2 的 6 类输出（atomic claim candidates、concept links、proposed concepts、speaker reasoning edges、evidence mentions、forecast candidates + 拒绝原因）。

### 5. Analyzer 模块（NEW）

**File**: `lib/houchen_analyzer.py`（NEW，~250 行）：

```python
def build_input_payload(*, video_id, transcript_segments, domain_skeleton,
                       raw_caption_sha256) -> dict
    # 构造分析 input bundle；序列化 + SHA-256

def call_provider(*, input_payload, schema, prompt_version, provider_config,
                  output_dir, run_id) -> ProviderResult
    # 调用 lib/insight_provider.build_provider()；output_dir 为 <root>/artifacts/analysis/runs/<run_id>.json
    # 失败类型（ProviderError / NetworkError / TimeoutError）→ outcome='analyze_failed'

def load_candidates(artifact_path) -> dict
    # 从 derived JSON 读 model 输出；JSON 解析失败 → raise ValueError
```

`provider_config` 从 `lib/insight_provider.py` 复用（`ProviderConfig` dataclass），但使用**新的 prompt/env**，不复用 macro insight 的 env（**研究库与宏观库命名空间独立**）。建议：研究库用 `config/houchen_analyze.env`（mode 0600）。

### 6. Hard Validator 模块（NEW — brief §9.3 全部 10 条规则）

**File**: `lib/houchen_validator.py`（NEW，~300 行）：

```python
@dataclass
class ValidationResult:
    accepted: list[Candidate]      # 通过所有规则的 candidate
    per_item_rejects: list[Reject]  # 每个拒绝的理由（brief §9.3 最后一行强制）
    needs_review: list[Candidate]   # 通过部分规则但有警告

def validate_claim(candidate, *, transcript_version, segments_by_ordinal) -> Reject | None
    # Rule 1: 缺 video_id / transcript_version_id / segment_range / timestamp_url / exact_quote → reject
    # Rule 2: exact_quote not in segment.text (via houchen_quote.exact_quote_in_segment) → reject
    # Rule 3: segment range 越界或 end_ms < start_ms → reject
    # Rule 4: layer='speaker_statement' and speaker is None or 'unknown' → reject
    # Rule 5: 多可拆分判断（heuristic: 包含多个「因为」/「所以」/句末标点 >1） → reject
    # Rule 6: speaker_reasoning edge without transcript_version_id + exact_quote → reject

def validate_concept(candidate, *, known_speakers) -> Reject | None
    # Rule 7: 已被 propose 为 canonical 但没有 concept_source → reject

def validate_evaluation(candidate) -> Reject | None
    # Rule 8: external_evidence 缺 publisher + content_sha256 + observed_period → reject

def validate_forecast(candidate) -> Reject | None
    # Rule 9: outcome_condition 为空或纯陈述无时间范围 → reject
```

**关键不变量（与 brief §3.1.5、§7.2、§9 一致）**：
- `exact_quote` 永远走 `houchen_quote.exact_quote_in_segment`；**禁止**自行实现
- `layer='speaker_statement'` 的 claim 必带已知 speaker；缺则 reject（不进入 needs_review）
- model 不能产出 `speaker_statement`（model 输出 layer ∈ {speaker_reasoning?, system_evaluation}；brief §3.1.5「speaker_statement 只来自实际说话」）
  - 注：实际分析中 model 会尝试给 `speaker_statement`；本 PR-3 validator **强制 reject** 而非 promote 到 speaker_reasoning，避免静默降级
- `concept.status='proposed'` 不自动 promote；只有显式人工审批才能进入 `canonical`

### 7. Concept 模块（NEW）

**File**: `lib/houchen_concept.py`（NEW，~150 行）：
- `seed_domain_skeleton(conn, skeleton)` — 启动时一次性植入 6 个 domain slug（brief §7.2 列表）
- `upsert_proposed_concept(conn, *, canonical_name, definition, analysis_run_id) → concept_id` — model 提出的新概念入库为 `proposed`
- `merge_aliases(conn, *, alias, target_concept_id, actor) → None` — 可逆操作（brief §7.2「别名合并必须可逆并记录操作者和时间」）
- `promote_to_canonical(conn, *, concept_id, actor, evidence_source_id) → None` — 必须有 concept_source 引用（brief §7.2 没有语料来源时不得显示为 canonical）

### 8. Runner

**File**: `lib/houchen_runner.py`（EXTEND）：
- `run_analyze(conn, *, video_ids=None, pending_only=True, limit=None, dry_run=False, prompt_version=DEFAULT, schema_version=DEFAULT) → dict`：选择 `transcript_version.status='ok'` 但无对应 `analysis_run` 的视频 → 构造 input → 调 provider → 写 `corpus_run(kind='analyze', ...)` + `corpus_attempt(stage='analyze', outcome='success'/'analyze_failed')` → 写 derived JSON。
- `run_validate(conn, *, analyze_artifact_paths=None, dry_run=False) → dict`：读 derived JSON → 调 validator → 写 `claim` / `claim_source` / `claim_concept` / `reasoning_edge` 等正式行 → 失败的进 `claim.status='rejected'`，警告的进 `'needs_review'`。
- `run_concept_seed(conn, *, dry_run=False) → dict`：一次性植入 domain skeleton。
- `_select_analyze_scope(conn, *, video_ids, pending_only)`：LEFT JOIN transcript_version vs analysis_run，single-SQL CTE（PR-1 P1-3 + PR-2 复用模式）。
- 幂等：UNIQUE(claim_id) + analysis_run_id 唯一约束。

### 9. Status

**File**: `lib/houchen_status.py`（EXTEND）：
- `status()` 新增 `"claims": {"accepted": N, "needs_review": N, "rejected": N}` 桶
- `coverage()` 新增 `"claim_outcomes": {...}`、`"concept_state": {"seed": N, "proposed": N, "canonical": N, "deprecated": N}`

### 10. CLI

**File**: `scripts/houchen_pipeline.py`（EXTEND）：
- `cmd_analyze` / `cmd_validate` / `cmd_concept_seed`，**完全镜像** `cmd_normalize` 模式（dry-run / pending-only / --video-id / --limit / exit codes）
- 新增 `--provider {anthropic|deepseek|minimax|fake}` 参数（默认 `fake`，默认离线）
- 新增 `--prompt-version` / `--schema-version`（默认 constants）

### 11. Fixtures

**File**: `scripts/houchen_fixtures/scenario.py` + 新 `scripts/houchen_fixtures/fake_provider.py`（NEW，~150 行）：
- `fake_provider.py`：返回固定 JSON 字符串（含至少 1 个 claim + 1 个 concept + 1 个 evidence_mention + 1 个 forecast），按 `input_sha256` 路由以保证可重放
- 测试可断言每条候选的接受/拒绝/警告路径

### 12. Tests

**File**: `scripts/test_houchen_validator.py`（NEW，~400 行）：

每个 brief §9.3 规则至少 1 个正例 + 1 个反例：

| Rule | 正例 | 反例 |
|------|------|------|
| 1 (缺 video_id 等) | 完整字段 | 缺 exact_quote → reject |
| 2 (quote 不在 segment 中) | 真子串 | 多 1 个字符 → reject |
| 3 (段越界 / 倒序) | 合法范围 | end_ms < start_ms → reject |
| 4 (speaker 缺) | speaker='李厚辰' | layer='speaker_statement', speaker=None → reject |
| 5 (多可拆分) | 单一断言 | 含「因为 ... 所以 ...」 → reject |
| 6 (speaker_reasoning 缺 source) | 带 exact_quote | 无 transcript_version_id → reject |
| 7 (concept 无 source) | 有 concept_source | 无 → reject |
| 8 (eval 缺 source) | 有 external_evidence | 无 → reject |
| 9 (forecast 无 criteria) | 有 outcome_condition | 空 → reject |

**File**: `scripts/test_houchen_analyzer.py`（NEW，~250 行）：
- `build_input_payload` 内容寻址：相同输入 → 相同 SHA
- `call_provider` 用 fake_provider；超时 / 网络错误分类
- 派生 JSON 落盘 0600 mode + 父目录 0700
- 幂等：相同 input → 不重写 derived JSON

**File**: `scripts/test_houchen_pipeline.py`（EXTEND）：CLI analyze / validate / concept-seed 子命令 ~6 测试。

**File**: `scripts/test_houchen_schema.py`（EXTEND）：v3 双版本校验（v3 表 + 扩 CHECK）。

## Critical files to be modified

| 文件 | 动作 | 估算行数 |
|------|------|---------|
| `lib/houchen_schema.py` | `+_V3_*`、`validate_schema` 三版本、`VERSION=3`、扩 v2 CHECK | +250 |
| `lib/houchen_migrations.py` | `+_apply_v3()` + 扩 `_recreate_with_widened_check` 支持 3 表 | +100 |
| `lib/houchen_paths.py` | `+analysis_input_path / analysis_artifact_path / concept_failure_path` | +40 |
| `lib/houchen_prompt.py` | **NEW** prompt + JSON schema + content addressing | ~80 |
| `lib/houchen_analyzer.py` | **NEW** provider orchestration + derived JSON write | ~250 |
| `lib/houchen_validator.py` | **NEW** brief §9.3 硬校验器（10 条规则） | ~300 |
| `lib/houchen_concept.py` | **NEW** domain seed + concept lifecycle | ~150 |
| `lib/houchen_runner.py` | `+run_analyze / run_validate / run_concept_seed / _select_analyze_scope` | +250 |
| `lib/houchen_status.py` | `+claims` / `+concept_state` 桶 + 扩 CTE | +60 |
| `scripts/houchen_pipeline.py` | `+cmd_analyze / cmd_validate / cmd_concept_seed` | +120 |
| `scripts/houchen_fixtures/fake_provider.py` | **NEW** fake model provider | ~150 |
| `scripts/houchen_fixtures/scenario.py` | `+fake_provider` 路径 + fixture | +30 |
| `scripts/test_houchen_validator.py` | **NEW** 每条规则正反例 | ~400 |
| `scripts/test_houchen_analyzer.py` | **NEW** 输入 bundle / provider / 幂等 | ~250 |
| `scripts/test_houchen_pipeline.py` | `+analyze / validate CLI 测试` | +120 |
| `scripts/test_houchen_schema.py` | `+v3 校验` | +40 |

**总计 ~2590 行；lib 文件 13 个（PR-2 9 + PR-3 +4），突破 brief §7.7 8 上限。** 拆分理由已在 plan §「Approach」开头固定记录。

## Existing utilities to reuse

- `houchen_quote.exact_quote_in_segment` — **唯一允许**的 exact_quote 匹配（PR-2 §8.6 hard gate；PR-3 §9.3 Rule 2）
- `houchen_normalizer.transcribe_video` 结果的 `transcript_version_id` + `transcript_segment[]`
- `houchen_paths.assert_no_symlink_components` + `_reject_symlink_ancestors` — PR-3 所有派生路径
- `houchen_paths.content_addressed` 模式 — `analysis_input/<sha[:2]>/<sha>.json` 复用
- `houchen_status.video_states` single-SQL 模式 — `_select_analyze_scope` 复用
- `lib/insight_provider.build_provider` / `ProviderConfig` — 模型调用复用，但**新 prompt/env** 不复用 macro insight 的 env
- PR-2 `_recreate_with_widened_check` 模式 — PR-3 v3 迁移复用
- PR-2 `_persist_transcript_version` UNIQUE 模式 — `claim` UNIQUE 约束同款

## Hard rules (brief §9.3 — must all be validators that reject)

1. 缺 video_id / transcript_version_id / segment_range / timestamp_url / exact_quote → reject
2. `exact_quote_in_segment(quote, segment.text) == False` → reject（**唯一调用** `houchen_quote`）
3. 段范围越界或 `end_ms < start_ms` → reject
4. `layer='speaker_statement'` 且 speaker 为 None/unknown → reject（**不**进 needs_review）
5. 一条 claim 含多个可拆分判断（启发式：「因为 ... 所以 ...」、多句末标点） → reject
6. `speaker_reasoning` 边缺 `transcript_version_id` + `exact_quote` → reject
7. `concept.status='canonical'` 但没有 `concept_source` → reject
8. `external_evidence` 缺 publisher + content_sha256 + observed_period → reject
9. `forecast.outcome_condition` 空或无时间范围 → reject
10. model 输出 `layer='speaker_statement'` → reject（**不**降级到 speaker_reasoning；记录 reject 理由）

`ValidationResult.per_item_rejects` 必须包含每条拒绝的理由（brief §9.3 最后一行），便于 prompt 修订 / 人工复核。

## Verification

PR-3 实现完成后顺序运行：

```bash
cd /Users/kjonekong/macro-pipeline

# 1. PR-3 validator 单测（每条 §9.3 规则正反例）
python3 -m pytest scripts/test_houchen_validator.py -v
# 预期: ≥ 18 passed

# 2. PR-3 analyzer + 幂等 + 内容寻址
python3 -m pytest scripts/test_houchen_analyzer.py -v
# 预期: ≥ 8 passed

# 3. PR-1 + PR-2 + PR-3 全回归（保证 v3 不破坏 v1/v2）
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
# 预期: ≥ 180 passed (PR-2 R3 终态 141 + PR-3 新增)

# 4. 全量（包含 verify/restore / presnapshot / ledger / migrations）
python3 -m pytest scripts -q
# 预期: ≥ 300 passed (PR-2 终态 259 + PR-3 新增)

# 5. 静态编译（13 lib 文件）
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
# 预期: exit 0

# 6. PR-1 + PR-2 红线 0 漂移
shasum -a 256 \
  docs/厚辰/不明白访谈厚辰.docx \
  docs/厚辰/重庆上街-厚辰.docx \
  docs/厚辰/世界苦茶研究库/{CLAUDE_CODE_IMPLEMENTATION_BRIEF,CODEX_ACCEPTANCE_PROTOCOL,ENGINEERING_TEST_PLAN}.md
shasum -a 256 data/store.db
# 预期: store.db = 52c12c82… (与 R3 一致)
find data/houchen -type f | wc -l
# 预期: 0

# 7. CLI dry-run 零副作用
python3 scripts/houchen_pipeline.py --data-root /tmp/hc analyze --dry-run
python3 scripts/houchen_pipeline.py --data-root /tmp/hc validate --dry-run
python3 scripts/houchen_pipeline.py --data-root /tmp/hc concept-seed --dry-run
# 预期: exit 0，无任何写

# 8. End-to-end（仅 fake_provider，离线）：复用 live smoke 已有的 4 个 transcript_version
python3 scripts/houchen_pipeline.py --data-root /tmp/hc-smoke-live analyze --provider fake
python3 scripts/houchen_pipeline.py --data-root /tmp/hc-smoke-live validate
# 预期: claim 表新增 N 行，needs_review + rejected 桶有据可查
```

## Out of scope for PR-3（明确推迟）

- FTS5 全文检索（brief §10）→ PR-4
- Obsidian 发布（brief §11）→ PR-5
- Macro bridge（brief §12）→ PR-6
- 真模型 eval（brief §10 + ENGINEERING_TEST_PLAN §10）→ 由用户在 PR-3 验收后单独授权
- 真人 speaker 解析（brief §7.1 `speaker` nullable for now）→ 未来 PR
- Concept 自动 promote → 严格人工审批（brief §7.2 明确要求）

## PR-3 完成后交付清单

- 4 新 lib + 6 扩展 lib + 2 新 fixtures + 2 新测试 + 1 扩展测试
- 全量 pytest 300+ passed
- PR-1 + PR-2 红线 0 漂移
- `PR1_HANDOFF.md` §10 增补 PR-3 摘要（含 §10.2 拆分理由）
- `docs/plans/pr3-claim-extraction.md` 复制 plan 路径（用户要求）
- 等待 Cursor 第三轮 PR-3 验收

## Plan content 落点

**Plan 内容同时落地到**：
- `/Users/kjonekong/.claude/plans/expressive-growing-wirth.md`（plan mode 期间管理文件）
- 实施时复制到 `/Users/kjonekong/macro-pipeline/docs/plans/pr3-claim-extraction.md`（CC §4 P2-C 要求路径）