# PR-5 — Macro Bridge: 宏观数据 × HouChen Claims 交叉验证

**Date:** 2026-08-25
**Status:** Implemented (landed 2026-08-25)
**Source of truth:** Brief §12 / §16 PR-5
**上游依赖:** PR-3 (claim extraction) merged; PR-4 (research map) in progress

---

## 0. 核心原则

| 约束 | 说明 |
|------|------|
| **零写宏观库** | `data/store.db` 只读打开；PR-5 前后 SHA 不变 |
| **无自动联动** | 首版只产出候选链接 + JSONL 导出；不自动写回 houchen claim/evaluation |
| **硬拒绝** | 无来源的 macro_bridge 引用被 R8 规则拒绝（已有先例） |

---

## 1. 数据模型

### 1.1 宏观侧（只读）

**`data/store.db`** — 宏观经济流水线

| 表 | 用途 | 关键字段 |
|---|------|---------|
| `observations` | 一手数据点 | `(source, series, date, value)` |
| `evidence_snapshot` | 账本证据 | `snapshot_id, source, series, period, value, content_sha256` |
| `claim` (账本) | 宏观研究主张 | `claim_id, claim_text, status` |
| `forecast` | 宏观预测 | `forecast_id, threshold, review_due_at` |

**`data/latest_readings.json`** — 最新读数快照（JSON，含 economy/name/unit/value/yoy_pct/trend/period）

### 1.2 HouChen 侧（写入目标）

**已有表**（PR-3 建立）:

| 表 | 用途 | 关键字段 |
|---|------|---------|
| `claim` | HouChen 主张 | `claim_id, claim_text, claim_type, status` (55 accepted) |
| `evaluation` | 评估记录 | `evaluator='macro_bridge'` 已预留 |
| `external_evidence` | 外部证据 | `publisher, observed_period, grade` |

### 1.3 新增表: `macro_link_candidate`

建在 **houchen.db**（非 store.db）：

```sql
CREATE TABLE macro_link_candidate (
    candidate_id    TEXT PRIMARY KEY,        -- UUIDv7, prefix 'mlc_'
    claim_id        TEXT NOT NULL REFERENCES claim(claim_id),
    -- 宏观侧引用（不存值，只存指针）
    macro_source    TEXT NOT NULL,           -- 'fred', 'cn_stats_cpi', etc.
    macro_series    TEXT NOT NULL,           -- 'CPIAUCSL', 'cpi_yoy', etc.
    macro_period    TEXT NOT NULL,           -- '2026-07-01', '2026-07', etc.
    macro_value     REAL,                   -- 从 store.db 读出时的值（审计用）
    -- 关系评估
    relation        TEXT NOT NULL CHECK(relation IN (
                        'supports',        -- 宏观数据支持 claim
                        'challenges',      -- 宏观数据挑战 claim
                        'contextualizes',  -- 宏观数据为 claim 提供背景
                        'unresolved'       -- 无法判定
                    )),
    confidence      TEXT CHECK(confidence IN ('high','medium','low')),
    reasoning       TEXT,                   -- 为什么判定此关系
    -- 元数据
    created_at      TEXT NOT NULL,
    method          TEXT NOT NULL DEFAULT 'keyword_match',  -- 匹配方法
    reviewed        INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0,1))
);

CREATE INDEX idx_mlc_claim ON macro_link_candidate(claim_id);
CREATE INDEX idx_mlc_macro ON macro_link_candidate(macro_source, macro_series);
CREATE INDEX idx_mlc_relation ON macro_link_candidate(relation);
```

**设计决策**：
- `macro_value` 存快照值用于审计，但**不引用** store.db 外键（跨库引用不可行）
- `method` 区分匹配策略（keyword_match / llm_match / manual），便于后续评估精度
- `reviewed` 标记人工审核状态

---

## 2. 接口设计

### 2.1 只读打开 store.db

```python
# lib/macro_bridge.py
import sqlite3

def open_macro_store_readonly() -> sqlite3.Connection:
    """只读打开宏观 store.db，PRAGMA 确保无副作用"""
    uri = f"file:{MACRO_STORE_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")  # 双保险
    return conn
```

**验证**：打开前后 SHA 必须一致；CI 中用 `PRAGMA query_only` + `mode=ro` 双重保障。

### 2.2 核心函数

```python
def find_candidates(
    claim_id: str,
    claim_text: str,
    macro_conn: sqlite3.Connection,
) -> list[MacroLinkCandidate]:
    """为一个 houchen claim 搜索宏观数据匹配"""
    ...

def evaluate_candidate(
    candidate: MacroLinkCandidate,
    macro_observation: dict,
) -> MacroLinkCandidate:
    """评估候选链接的 relation + confidence"""
    ...

def export_jsonl(
    candidates: list[MacroLinkCandidate],
    output_path: Path,
) -> int:
    """导出候选链接为 JSONL（独立消费）"""
    ...

def import_to_evaluation(
    candidate: MacroLinkCandidate,
    houchen_conn: sqlite3.Connection,
) -> str:  # evaluation_id
    """将已审核的候选链接导入 houchen evaluation 表"""
    ...
```

### 2.3 CLI

```bash
# 扫描全部 accepted claims，生成候选链接
python3 scripts/houchen_pipeline.py macro-bridge --scan

# 导出 JSONL
python3 scripts/houchen_pipeline.py macro-bridge --export data/houchen/macro_links.jsonl

# 验证 store.db 未被修改
python3 scripts/houchen_pipeline.py macro-bridge --verify-sha
```

---

## 3. 匹配策略 (首版: keyword_match)

### 3.1 关键词映射

```python
MACRO_KEYWORDS = {
    'CPI':      ['cpi_yoy', 'CPIAUCSL', 'PCEPI', 'de_cpi', 'cn_stats_cpi'],
    '通胀':     ['cpi_yoy', 'CPIAUCSL', 'PCEPI'],
    'GDP':      ['gdp_yoy', 'GDPC1', 'de_gdp', 'cn_stats_gdp'],
    '失业率':   ['unemployment', 'UNRATE', 'de_unrate'],
    '利率':     ['policy_rate', 'FEDFUNDS', 'jp_policy'],
    '财政':     ['fiscal', 'GFDEBTN', 'FYFSD', 'cn_mof'],
    'PMI':      ['pmi', 'cn_stats_pmi'],
    'M2':       ['m2', 'cn_pbc_m2'],
    '贸易战':   ['tariff', 'trade'],  # 无直接宏观序列，标记 contextualizes
    '化债':     ['debt', 'GFDEBTN', 'cn_mof'],
}
```

### 3.2 关系判定逻辑

```
claim 提及 CPI/通胀 + claim_type=predictive + 实际 CPI 趋势与预测方向一致 → supports
claim 提及 CPI/通胀 + claim_type=predictive + 实际 CPI 趋势与预测方向相反 → challenges
claim 提及某指标但非核心论点 → contextualizes
无法匹配到宏观序列 → unresolved
```

---

## 4. 与 external_evidence 的关系

已审核 (reviewed=1) 的候选链接可升级为 `external_evidence` + `evaluation`：

```
macro_link_candidate (reviewed=1)
  ↓ 升级
external_evidence (publisher=macro_source, grade='A' 因一手数据)
  ↓ 关联
evaluation (evaluator='macro_bridge', verdict=supports/challenges/...)
```

这复用了 PR-3 已有的 evaluation 基础设施，`evaluator='macro_bridge'` 已在 CHECK 约束中预留。

---

## 5. 测试矩阵

### 5.1 安全测试（P0）

| 测试 | 验证 |
|------|------|
| `test_store_db_readonly` | 打开后执行 INSERT → 抛异常 |
| `test_sha_unchanged` | scan 前后 `store.db` SHA 一致 |
| `test_no_macro_write_import` | `lib/macro_bridge.py` 无 INSERT/UPDATE/DELETE 到 store.db |

### 5.2 功能测试

| 测试 | 验证 |
|------|------|
| `test_keyword_match_cpi` | claim 提及"通胀" → 匹配到 CPI 序列 |
| `test_relation_supports` | CPI claim + 实际 CPI 上升 → supports |
| `test_relation_challenges` | CPI claim + 实际 CPI 下降 → challenges |
| `test_export_jsonl` | JSONL 输出格式正确、幂等 |
| `test_no_match_unresolved` | 无宏观数据匹配 → unresolved |

### 5.3 集成测试

| 测试 | 验证 |
|------|------|
| `test_e2e_scan` | 全量 scan 55 accepted claims → 产出 N 条候选 |
| `test_import_to_evaluation` | 审核后的候选正确写入 houchen evaluation |

---

## 6. 首版范围

### ✅ 做

1. `lib/macro_bridge.py` — 只读 store.db + 候选搜索 + 关系评估
2. `macro_link_candidate` 表 (houchen.db)
3. CLI: `macro-bridge --scan / --export / --verify-sha`
4. JSONL 导出（独立消费，不依赖 houchen pipeline）
5. 关键词匹配（keyword_match 方法）
6. 安全测试 + 功能测试

### ❌ 不做

1. LLM 匹配（`llm_match` 方法）→ PR-6
2. 自动写入 evaluation（需人工审核 reviewed=1 后手动触发）
3. 双向联动（macro → houchen 方向）
4. UI / Dashboard
5. 实时监听宏观数据更新

---

## 7. 文件清单（≤8）

| 文件 | 动作 | 说明 |
|------|------|------|
| `lib/macro_bridge.py` | 新建 | 核心逻辑：只读打开 + 匹配 + 评估 + 导出 |
| `lib/houchen_schema.py` | 修改 | 添加 `macro_link_candidate` 建表 DDL |
| `scripts/houchen_pipeline.py` | 修改 | 添加 `macro-bridge` CLI 子命令 |
| `tests/test_macro_bridge.py` | 新建 | 安全 + 功能 + 集成测试 |
| `config/macro_bridge_keywords.yaml` | 新建 | 关键词映射配置（可从代码中抽出） |
| `docs/plans/pr5-macro-bridge.md` | 本文件 | 计划 |

共 6 文件。

---

## 8. 退出条件

1. [x] `store.db` SHA scan 前后一致（自动化验证）
2. [x] 55 accepted claims 全量扫描产出候选链接
3. [x] JSONL 导出格式稳定、可重复
4. [x] 安全测试全绿（无 store.db 写入）
5. [x] 功能测试全绿（关键词匹配 + 关系判定）
6. [x] 无 hardcoded API key / 无 `pip install` 新依赖
7. [x] Cursor 审验通过

---

## 9. 风险

| 风险 | 缓解 |
|------|------|
| 关键词匹配精度低 | 首版 accept 低精度/高召回；人工审核后升级到 evaluation |
| claim 中文表述多样 | 关键词表支持同义词扩展；后续加 embedding 匹配 |
| 宏观数据粒度不匹配 | claim 可能提及"近几个月"但宏观数据只有月度；标记 unresolved |
| store.db 并发访问 | `mode=ro` + `PRAGMA query_only` 确保只读；busy_timeout=5000 |
