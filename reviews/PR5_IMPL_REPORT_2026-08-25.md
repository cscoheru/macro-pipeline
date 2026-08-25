# PR-5 Implementation Report (2026-08-25)

> **响应**：`reviews/DUAL_TRACK_PR5_ASR_KICKOFF_2026-08-25.md` P1

---

## 测试

```text
pytest scripts/test_macro_bridge.py -q  →  28 passed (0.08s)
pytest scripts/ -q                      →  416 passed (17.85s, no regression)
```

### 测试覆盖

| 类别 | 测试数 | 关键项 |
|------|--------|--------|
| Safety | 5 | readonly reject writes / SHA match / SHA mismatch / macro readonly / SHA unchanged after scan |
| Functional | 16 | keyword match (CPI/中文/无匹配/空列表/去重) / relation (unresolved/contextualizes/predictive→unresolved/empty key) / find_candidates (有/无/ID/dict) / fetch_observations / load_keywords |
| Integration | 4 | scan writes candidates / export JSONL / import_to_evaluation / ensure_table (create/idempotent/CHECK) |
| **合计** | **28** | |

---

## 功能验证

```text
macro-bridge --verify-sha 4a8e409b…  →  sha_match: true
macro-bridge --scan                  →  claims_scanned: 6, candidates: 32, all contextualizes
macro-bridge --export macro_links.jsonl → exported: 32
```

### 候选分布

| relation | count | 说明 |
|----------|-------|------|
| contextualizes | 32 | v1 安全默认：所有匹配标记为背景关系 |
| supports | 0 | 需 v2 趋势分析 |
| challenges | 0 | 需 v2 趋势分析 |
| unresolved | 0 | 所有 claim 都匹配到了观测数据 |

---

## store.db SHA

```text
before = 4a8e409b7279b72a57364ef735f5f6066a20b6d99352d676dc94d9a549e8a43c
after  = 4a8e409b7279b72a57364ef735f5f6066a20b6d99352d676dc94d9a549e8a43c
✅ MATCH
```

---

## 文件清单

| 文件 | 动作 | 行数 |
|------|------|------|
| `lib/macro_bridge.py` | 新建 | ~300 |
| `config/macro_bridge_keywords.yaml` | 新建 | ~130 |
| `scripts/houchen_pipeline.py` | 修改 | +80 (cmd_macro_bridge + parser + dispatch) |
| `scripts/test_macro_bridge.py` | 新建 | ~340 (28 tests) |

共 4 文件，≤8 约束满足。

---

## 设计决策

1. **v1 全部 contextualizes**：safe default，不做自动 supports/challenges 判定（需趋势分析 v2）
2. **`_ensure_table` 而非 schema v5**：首版用 `CREATE TABLE IF NOT EXISTS` 避免完整 schema 迁移；后续 PR 可升级为正式 v5
3. **import_to_evaluation 未挂 CLI**：首版仅实现函数，需 `reviewed=1` 手动触发（按 kickoff 要求）
4. **UUIDv7 ID prefix `mlc_`**：与现有 `hcrun_`/`hcatt_`/`evl_` 同构
