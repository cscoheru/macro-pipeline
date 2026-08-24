# PR-3 计划审核 — Claude Code 执行授权

> **签发**：Cursor 架构/质量审核（只读，2026-08-24）
> **计划文件**：`docs/plans/pr3-claim-extraction.md`（324 行）
> **用户裁定**：见 §用户一句

---

## 用户一句

**批准启动 PR-3 实现**（按本文件 §3 顺序与 §4 开工前修正）。未 push；PR-1 红线每阶段复验。

---

## 1. P2-C 核对清单

| 要求 | 结果 |
|------|------|
| 路径 `docs/plans/pr3-claim-extraction.md` | ✅ |
| schema v3 草案 | ✅ §1（多表 + CHECK） |
| `claim` + `claim_source` | ✅ |
| `exact_quote` 硬门禁 → `houchen_quote` | ✅ §6 Rule 2 + §Existing utilities |
| 测试矩阵 | ✅ §12 + §Verification |
| 拟改文件清单 | ✅ §Critical files |
| 13 lib 拆分理由 | ✅ §Approach 表（9+4） |

**结论**：P2-C **PASS**（计划可执行）。

---

## 2. 审核意见（开工前须纳入实现，非重新立项）

| ID | 项 | 动作 |
|----|-----|------|
| F-1 | **领域 seed 数量** | brief §7.2 为 **7** 个 `domain` slug（含 `method_media`）；plan 多处写「6 个」→ 实现与测试统一为 **7** |
| F-2 | **`analysis_run_id`** | 无独立 `analysis_run` 表；FK 应指向 **`corpus_run.run_id`**（`kind='analyze'`）。在 schema DDL 与 runner 注释中写清 |
| F-3 | **`concept` 列** | brief 要求 `canonical_name`；plan `upsert_proposed_concept` 须包含该字段 |
| F-4 | **Rule 4 vs Rule 10** | Rule 4：validator 输入缺 speaker → reject；Rule 10：model 产出 `speaker_statement` → reject。两者并存，测试分开 |
| F-5 | **macro 隔离** | PR-3 验收须加：fake E2E 后 `data/store.db` SHA 仍 `52c12c82…`（可扩展现有 macro isolation 或新测） |
| F-6 | **env 隔离** | `config/houchen_analyze.env` + `.example`；**禁止** commit 真实 key；复用 `insight_provider` 接口但不读 `insight.env` |
| F-7 | **brief 基线文档** | 不修改 `CLAUDE_CODE_IMPLEMENTATION_BRIEF` / `CODEX_ACCEPTANCE_PROTOCOL` / `ENGINEERING_TEST_PLAN` 正文 |

### 已知接受风险（不阻断）

- Rule 5 启发式（「因为/所以」）可能误杀；用 fixture 固化边界即可。
- PR-3 brief 退出条件（20–30 主张 / 8–12 视频）本 PR 以 **fake 垂直切片 + 测试** 为满足，真模型 eval 仍 out of scope。

---

## 3. CC 实现顺序（强制）

与 plan「按顺序」一致，**每步独立 pytest 子集通过后再下一步**：

```text
1. houchen_schema.py      _V3_* + validate_schema(v3) + VERSION=3
2. houchen_migrations.py  _apply_v3()（复用 v2 recreate 索引顺序）
3. houchen_paths.py       analysis_* / concept_failure / prompt 路径
4. houchen_prompt.py      input bundle + schema JSON + input_sha256
5. houchen_validator.py   §9.3 10 规则 + per_item_rejects
6. houchen_concept.py     domain seed(7) + proposed/alias/promote
7. houchen_analyzer.py    build_input + call_provider + derived JSON
8. houchen_runner.py      run_analyze / run_validate / run_concept_seed
9. houchen_status.py      claims + concept_state 桶
10. houchen_pipeline.py   analyze / validate / concept-seed CLI
11. fixtures              fake_provider.py + scenario 扩展
12. tests                 validator → analyzer → schema v3 → pipeline CLI
```

**禁止跳步一次性大提交**；**禁止** PR-4/PR-5 代码。

---

## 4. 阶段门禁（每阶段结束跑）

```bash
cd /Users/kjonekong/macro-pipeline

# 红线（每阶段）
shasum -a 256 data/store.db   # 52c12c82…
find data/houchen -type f | wc -l   # 0

# 回归（每阶段）
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q

# 全量（仅 PR-3 完工）
python3 -m pytest scripts -q
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
```

PR-3 完工预期：`scripts` ≥300 passed（plan §Verification）。

---

## 5. 交付与验收（PR-3 完成后）

| 交付物 | 路径 |
|--------|------|
| 实现 + 测试 | 见 plan §Critical files |
| Handoff | `PR1_HANDOFF.md` **§11 PR-3**（非改 §10 历史） |
| 交付摘要 | `reviews/PR3_DELIVERY_2026-08-24.md`（新建） |
| 计划状态 | 本文件 §6 勾选完成 |

**不要 commit/push**，除非用户另行要求（与 PR-1/2 一致）。

---

## 6. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 | Plan 落档；Cursor 审核 **批准实现**（F-1～F-7） |
