# Phase 1 · 严格判断账本 实施计划

> 状态：plan-eng-review 锁定中（2026-08-13）
> 上游规格：`~/.gstack/projects/garrytan-gstack/kjonekong-frontend-design-20260812-213000.md`
> 评估文档：`docs/judgement-ledger-evaluation.md`（6 P0 + 路线图）
> 命题：**「中国需求是否进入持续修复」**
> 审查基线：对 `lib/store.py` / `run.py` / `lib/vault_writer.py` 第一手核实（2026-08-13）

---

## 0. 已锁定的决定（本次 review 确认）

| 决定 | 选择 | 依据 |
|---|---|---|
| 模块结构 | 单 `lib/ledger.py`（函数式，匹配 store.py 习惯） | 7 实体皆同库追加行；4 文件 < 8 复杂度阈值 |
| ID 方案 | UUIDv7 + 类型前缀（Python 3.14 原生 `uuid.uuid7()`） | stdlib 时间序，零手写单调性风险；复审 #7 |
| 账本库 | 同一 `store.db`，并排建表 | 复用 ACID 单写；零迁移 |
| 测试框架 | **pytest**（项目首次引入） | 用户 D2 选定；验收门禁可重复 |
| `_yoy` bug | **Phase 1 内顺手修** + 回归测试 | 用户 D3 选定；CN 证据键正确 |
| 状态存储 | **从 ledger_event 回放派生**（见 §2 强化点） | trigger 一刀切禁 UPDATE 的前提 |
| D1 双签 | **双帽自签（同日）**：同一人以 author + reviewer 两角色签，均记入事件链 | 用户 8/13 决策；单人兑现结构双签；统一设计文档 self-review 与评估文档双签分歧 |
| PRAGMA | `_connect` 内 `busy_timeout=5000` + `foreign_keys=ON` | 复审 #5/#6；防 SQLITE_BUSY 静默失败 + 悬挂引用 |
| 备份 | 建表前 `cp store.db store.db.bak.<date>`；日备脚本 | 复审 #4；不可替代账本 + 数据丢失史 |

## NOT in scope
海关源端到端 / FOMC·BLS·BEA 直连 / PostgreSQL·DuckDB 迁移 / 双向同步 / 图谱·向量检索 / Dashboard / 多用户 / 自动写研究结论 / DecisionRecord / 批量回填 8 份积压 / 观测表历史修订保留（P2）。

## What already exists（复用，不重建）
- `store.py` SQLite ACID 单写 → ledger 同库并排
- `run.py:save_local_snapshot` → 证据快照机制已存在，只补 sha256
- `vault_writer.put_pipeline` 单向写 → claim 报告卡复用
- `detector.is_new_period/mark_seen` → ResearchItem 在 NEW period 入队
- `paths.SNAPS/STORE_DB` → 路径已就位

---

## 1. 文件结构（4 文件）

```
lib/ledger.py        [新]  schema DDL + init_schema() + ulid() + append_event()
                          + transition() + current_status() + create_*() 
                          + record_failure() + seed_phase1()
lib/store.py         [改]  _connect() 内并排调 ledger.init_schema()
                          修 _yoy 双后缀（key 已含 _yoy 时不再拼）
run.py               [改]  3 钩子 + _yoy 修复（见 §4）
scripts/test_ledger.py  [新]  trigger 拒绝 + 状态机 + 重建验收（pytest）
pyproject.toml 或 requirements-dev.txt  [新]  pytest 依赖
```

## 2. 核心架构强化点（review 新增）

**问题**：严格账本说"实体永不 UPDATE/DELETE"，但 Claim/Forecast/ResearchItem 有 `status` 字段需要流转。若 status 是可变列，trigger 禁 UPDATE 会连合法状态流转也挡掉。

**解法**：纯事件溯源——
- 实体行 **INSERT 一次**（creation record，含初始 status）。
- 所有后续状态流转 **只追加 `ledger_event`**，实体行永不再动。
- `current_status(entity_type, entity_id)` = 回放该实体事件链取最新 `to_status`，无事件则取 creation status。

这样 trigger 对 7 表一刀切 `BEFORE UPDATE/DELETE → RAISE(ABORT)` 是**正确的**，因为合法代码从不 UPDATE 实体。这也直接满足验收门禁"随机 claim 可仅从事件链重放"。

```
数据流（单向，authority boundary）:

  一手源 → fetcher → run.py ─┬─► store.observations (时序, 可 REPLACE)
                             ├─► save_local_snapshot + sha256  →  evidence_snapshot (不可变)
                             ├─► record_failure()  ───────────►  ledger_event(source 失败)
                             └─► NEW period → create_research_item() → queued
                                                                    ↓ (人: claim→forecast→review)
                              ledger 实体表 (INSERT-once) ← append_event (每次流转)
                                                                    ↓ (单向生成)
                              vault_writer.put_pipeline → 宏观经济/_pipeline/_ledger/*.md
```

## 2a. 复审硬性强化（outside voice 13 条 → 已吸收，2026-08-13）

| # | 强化 | 落地位置 |
|---|---|---|
| 3 | 保存路径**内容寻址** `{label}-{period}-{sha[:12]}.{ext}`（修订不碰撞） | run.py `save_local_snapshot` |
| 4 | 建表前 `cp store.db → .bak.<date>` + 日备脚本 | `scripts/backup_ledger.sh` + 实施步骤 0 |
| 5 | `PRAGMA busy_timeout=5000` | store.py `_connect` |
| 6 | `PRAGMA foreign_keys=ON` | store.py `_connect` |
| 7 | UUIDv7（`uuid.uuid7()`）替代手写 ULID | ledger.py `new_id()` |
| 9 | ResearchItem 为**权威**；vault brief 仅显示、带 `rit_id` | run.py + render |
| 13 | 报告卡**自包含**：内联证据路径/URL/阈值，重建=读卡不查 sqlite | ledger.py `render_claim_card` |
| 2 | live 同周期修订检测（detector 严格 `>`）**划 P2**；Phase 1 种子用历史快照不受影响 | scope |
| #1 | trigger/status 矛盾 → §2 事件溯源已解（实体 INSERT-once，status 回放派生） | §2 |
| #8 | D1 双签 → **双帽自签同日**（用户 8/13 决策） | `seed_phase1` ClientImplication |
| #10 | FRED 失败站点(117/120)已在 §4 G1 钩子覆盖 | §4 |
| #11 | 源缺失走 `indeterminate`（设计已支持），不靠延期 | 状态机 |
| #12 | markdown+git 战略挑战 → 用户决策**锁 B + 加固** | 本节 |

---

## 3. Schema DDL（lib/ledger.py 内 SCHEMA 常量）

```sql
-- 7 张实体表，全部 INSERT-only。trigger 一刀切禁 UPDATE/DELETE。
CREATE TABLE IF NOT EXISTS evidence_snapshot (
  evi_id TEXT PRIMARY KEY, source_url TEXT, publisher TEXT,
  published_at TEXT, retrieved_at TEXT, observed_period TEXT,
  metric_id TEXT, value REAL, unit TEXT, methodology_version TEXT,
  content_sha256 TEXT NOT NULL, raw_path TEXT NOT NULL,
  included_metrics TEXT, missing_metrics TEXT,       -- JSON array, G2
  initial_status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim (
  clm_id TEXT PRIMARY KEY, as_of_time TEXT, statement TEXT NOT NULL,
  scope TEXT, mechanism TEXT, alternative_explanations TEXT,  -- JSON
  confidence TEXT, initial_status TEXT NOT NULL DEFAULT 'draft',
  supersedes_id TEXT, evidence_ids TEXT,  -- JSON array of evi_id
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast (
  fcst_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL,
  metric_id TEXT, target_period TEXT, decision_rule TEXT NOT NULL,
  threshold REAL, direction TEXT, review_due_at TEXT NOT NULL,
  initial_status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review (
  rev_id TEXT PRIMARY KEY, forecast_id TEXT NOT NULL, reviewed_at TEXT,
  outcome TEXT, observed_evidence_id TEXT,
  error_class_primary TEXT, error_class_secondary TEXT, rationale TEXT,
  initial_status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_implication (
  imp_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, client_segment TEXT,
  action TEXT, trigger TEXT, stop_condition TEXT, decision_horizon TEXT,
  evidence_grade TEXT, reviewer_primary TEXT, reviewer_secondary TEXT,
  initial_status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_item (
  rit_id TEXT PRIMARY KEY, queue_source TEXT, source_event_id TEXT,
  title TEXT, priority TEXT, claim_id TEXT,
  initial_status TEXT NOT NULL DEFAULT 'queued',
  claimed_by TEXT, claimed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_event (
  evt_id TEXT PRIMARY KEY,        -- ULID, 天然时间序
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  from_status TEXT, to_status TEXT NOT NULL,
  actor TEXT, reason TEXT, occurred_at TEXT NOT NULL,
  payload_sha256 TEXT
);

-- 不可变性强制：7 表全部禁 UPDATE/DELETE（合法代码从不 UPDATE，见 §2）
-- SQLite 不支持一次性挂全表，逐表写。
%{TRIGGERS}

-- 状态机索引：按实体回放事件
CREATE INDEX IF NOT EXISTS idx_event_entity ON ledger_event(entity_type, entity_id, evt_id);
```

`%{TRIGGERS}` 展开为对 7 表各两条：
```sql
CREATE TRIGGER IF NOT EXISTS noguard_upd_<t> BEFORE UPDATE ON <t> BEGIN
  SELECT RAISE(ABORT, 'ledger table <t> is append-only: UPDATE forbidden'); END;
CREATE TRIGGER IF NOT EXISTS noguard_del_<t> BEFORE DELETE ON <t> BEGIN
  SELECT RAISE(ABORT, 'ledger table <t> is append-only: DELETE forbidden'); END;
```

## 4. run.py 集成点（精确行号）

| 钩子 | 位置 | 改动 |
|---|---|---|
| T2 快照哈希 | `save_local_snapshot`(run.py:97-101) | 写文件后算 sha256，返回 (path, hash)；调用方落 evidence_snapshot |
| T2 evidence 落账 | `process_fred`(127 后) / `process_cn_release`(160 后) | 新数据周期时 create evidence_snapshot（含 included/missing metrics, G2） |
| G1 失败事件 | fetch 失败(117)/空行(120)/CN discover(143)/parse(151) | 调 `ledger.record_failure(source, series, error_class, detail, last_valid_evi)` |
| ResearchItem | `run()` 主循环 updates 非空时(435 附近) | 每源 create_research_item(queued)，关联 source_event |
| `_yoy` 修复 | run.py:166-167 | `skey = key if key.endswith("_yoy") else key + "_yoy"` |
| claim 报告卡(单向) | `run()` 末尾或 `--rebuild` | `vault_writer.put_pipeline("_ledger/<clm_id>.md", render_claim_card(clm_id))` |

**关键边界**：`record_failure` 不抛异常、不中断 run（与现有 `notify` 并存，不替换）；evidence 落账失败要 log 但不阻塞采集（采集优先）。

## 5. 函数签名（lib/ledger.py）

```python
def init_schema(conn): ...                      # 建表 + triggers（幂等）
def ulid(prefix: str) -> str: ...               # stdlib: ts_ms(48bit)+rand(80bit) Crockford base32, 带前缀
def append_event(conn, entity_type, entity_id, to_status, actor, reason, from_status=None, payload=None): ...
def current_status(conn, entity_type, entity_id) -> str: ...   # 回放事件链
def transition(conn, entity_type, entity_id, to_status, actor, reason, allowed: set): ...
    # 校验 from∈allowed→to；同事务 append_event
# create_*：INSERT 实体行 + 首条 created 事件，同一事务
def create_evidence_snapshot(conn, *, source_url, published_at, observed_period, metric_id, value, unit, content_sha256, raw_path, included, missing) -> str
def create_claim(conn, *, statement, mechanism, alternatives, evidence_ids, confidence, scope) -> str
def create_forecast(conn, *, claim_id, metric_id, target_period, decision_rule, threshold, direction, review_due_at) -> str
def create_client_implication(conn, *, claim_id, segment, action, trigger, stop_condition, grade, reviewer_p, reviewer_s) -> str
def create_research_item(conn, *, queue_source, source_event_id, title, priority) -> str
def record_failure(conn, *, source, series, error_class, detail, last_valid_evi=None) -> str  # evt_, entity_type='source'
def render_claim_card(conn, clm_id) -> str       # 10 分钟重建所需的 markdown
def seed_phase1(conn): ...                       # 录入 §6 命题数据（幂等：已存在则跳过）
```

状态机（transition 的 allowed 集）：
```
research_item: {queued→claimed, claimed→completed, queued→blocked, blocked→claimed}
claim:         {draft→active, active→superseded}
forecast:      {draft→active, active→due, due→hit/miss/partial/indeterminate, *→closed}
```

## 6. Phase 1 命题种子（seed_phase1，幂等）

命题：**中国需求是否进入持续修复**。素材 = 2026-08-12 待解读（已在 store/cache）。

| 实体 | 内容 |
|---|---|
| 指标(5) | cn_pbc:pbc_m2(8.0%)、cn_pbc:pbc_m1(4.0%)、cn_stats_inv:inv_total(-5.7%)、cn_stats_pmi:pmi_mfg(49.2)、cn_stats_cpi:cpi_yoy(0.5%) |
| 证据快照(2, content-addressed) | ① cn_pbc 2026-06 发布稿（M2/M1/社融，raw 已在 data/snapshots/cn_pbc/）② cn_stats_inv 2026-06 发布稿（固投，raw 在 data/snapshots/cn_stats_inv/）。各算 sha256 + 记 included/missing metrics |
| Claim #1 | "货币宽松已启动但未传导至实体"（M2 8.0%↑ vs M1 4.0% 弱）。替代解释：**M1 口径 2024 年调整**（非真宽松传导问题）。confidence 中 |
| Claim #2 | "总需求仍弱"（固投 -5.7%、PMI 49.2<50、CPI 0.5% 低位）。confidence 中 |
| Forecast(1, 前置注册阈值) | metric=固投累计同比，target=2026 1-7月，rule：**>-5.0%=hit（修复确认）/<-6.0%=miss/中间=partial**，review_due_at=**2026-08-25**（统计局约8/15、财政部约8/22 发 1-7 月数据后） |
| ClientImplication(1) | segment=逆周期布局型；action=维持基建链条观察仓；trigger=固投连续两月回升；stop=PMI 跌破 48；grade=**B**（官方一手单源）；reviewer 双签（待填） |

## 7. 测试计划（pytest，scripts/test_ledger.py）

```
CODE PATHS                                          TESTS
[+] lib/ledger.py
  ├── ulid()              [★★★] 唯一性/时序/前缀 — test_ulid
  ├── append_event()      [★★★] 写入+字段完整 — test_append_event
  ├── current_status()    [★★★] 回放正确(无事件=初始/多事件=最新) — test_current_status
  ├── transition()        [★★★] 允许集通过 + 非法转换被拒 — test_transition_allowed/rejected
  ├── create_*()          [★★★] 实体行+created事件同事务 — test_create_atomic
  ├── record_failure()    [★★★] source 失败事件可查+last_valid 引用 — test_record_failure
  └── render_claim_card() [★★★] 10分钟重建: clm→证据→forecast→implication 全链可点 — test_reconstruction
[+] trigger 不可变性      [★★★] UPDATE/DELETE 对 7 表均 ABORT — test_trigger_rejects_update_delete (验收门禁1)
[+] _yoy 修复(regression) [★★★] cpi_yoy 不再变 cpi_yoy_yoy — test_yoy_key_regression (REGRESSION, CRITICAL)
[+] seed_phase1 幂等      [★★★] 重复 seed 不重复创建 — test_seed_idempotent

USER FLOWS
[+] 10分钟重建验收(门禁1) [→E2E] 从随机 clm_id 起步,纯靠 ledger 重建证据链 ≤10min — test_reconstruction

COVERAGE: 10/10 paths tested (100%)  | GAPS: 0
```

门禁映射：① trigger 拒绝=test_trigger_rejects_update_delete ② 10 分钟重建=test_reconstruction ③ 前置阈值 forecast=seed 的 Forecast ④ implication 审核=seed 的 ClientImplication（双签占位）。

## 8. 失败模式

| 失败 | 测试 | 错误处理 | 用户可见 |
|---|---|---|---|
| evidence 落账时 DB 锁 | test_create_atomic | log + 不阻塞采集 | 日志 |
| 同周期修订（再发布） | — | 新建 evidence_snapshot（同 observed_period, 新 published_at） | 报告卡多版本 |
| record_failure 在采集异常路径再抛 | test_record_failure | 内部 try/except，绝不抛 | 日志 |
| ULID 时钟回拨 | test_ulid | rand 段保证唯一 | — |
| _yoy 旧脏数据(cpi_yoy_yoy)残留 | test_yoy_key_regression | 不迁移历史（P2），只保证新写入正确 | — |

无"无测试+无错误处理+静默"的 critical gap。

## 9. 实施顺序（串行，共享 store.py→sequential）

1. `lib/ledger.py`：init_schema + ulid + append_event + current_status + transition + create_*（核心）
2. `lib/store.py`：_connect 并排 init_schema；修 `_yoy`
3. `run.py`：3 钩子（hash/failure/research_item）+ _yoy（已在 step2）
4. `seed_phase1` + render_claim_card
5. `scripts/test_ledger.py`（pytest，含 trigger/reconstruction/regression）
6. 跑测试 → 验收 4 门禁 → 单向生成报告卡到 vault `_ledger/`

无并行机会（全共享 store.py）。Sequential。

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 2 issues (test fw + _yoy), both resolved (pytest / fix-in-phase1); 0 critical gaps |
| Outside Voice | subagent | Cross-model 2nd opinion | 1 | CLEAR | 13 findings: 9 folded as §2a hardening (uuid7/busy_timeout/FK/backup/content-addressed path/self-contained card/ResearchItem authority/P2 revision-scope); §2 already resolves #1 trigger-status; 3 already covered (#10/#11); 2 cross-model → user decided 2026-08-13 (战略:锁B+加固; D1:双帽自签同日) |

- **VERDICT:** ENG CLEARED (LOCKED) — outside voice ran; 2 cross-model tensions surfaced & resolved by user (2026-08-13). All P0 addressed; 9 hardening items folded (§2a). Ready to implement.
- Architecture verdict: strict append-only ledger via event-sourced status derivation; single-module consolidation; 6 P0 all addressed; uuid7 IDs; backup precondition.

PLAN LOCKED — IMPLEMENTING (§9 order)
