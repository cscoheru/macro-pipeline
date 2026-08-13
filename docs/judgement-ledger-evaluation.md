# 判断账本 · 深度评估与路线图

> 配套设计文档：`~/.gstack/projects/garrytan-gstack/kjonekong-frontend-design-20260812-213000.md`
> 日期：2026-08-13
> 判定标准：**已锁定的严格账本**（2026-08-13 采用）——`ResearchItem` + `LedgerEvent` + 独立 Claim/Forecast 状态机；阶段一客户行动仅限经审核的建议，不做客户行为因果归因。
> 评估基线：对 `~/macro-pipeline/` 的实际代码逐项核实（2026-08-13），非纸面推演。

---

## 一、评估总览

方向正确，规格已锁定。四个维度各有 1–2 个**必须在 Phase 1 前处理的 P0**，其余为 P1/P2 增强。不存在需要推翻设计的发现；但有一类发现值得重视——**现有采集层有 3 个事实问题会让账本的「证据可追溯」前提落空**（静默覆盖修订、无内容寻址、失败易失），它们被作为 P0 纳入原型范围，而不是留给以后。

| 维度 | 判定 | P0 阻断项 |
|---|---|---|
| 技术 | 选型正确（SQLite），1 个 P0 | T1 REPLACE/UPDATE 防护 · T2 快照内容寻址 |
| 数据治理 | 边界已基本成立，2 个 P0 | G1 失败事件化 · G2 快照不依赖 cache 最终态 |
| 分析方法 | 可证伪设计正确，1 个 P0 | A1 只选 1 个真实命题入账本，不批量迁 |
| 交付呈现 | 单向生成已锁定，1 个 P0 | D1 evidence_grade 分级细则 + reviewer 双签 |

---

## 二、技术维度

### 现状（实测）

- `data/store.db` 是单表 `observations(source, series, date, value)`，写入用 **`INSERT OR REPLACE`**（`lib/store.py:25-28`）。
- 快照文件按 `(series, period)` 命名（FRED 全量 CSV、CN 发布稿 txt），**无任何内容哈希**；代码里搜不到 hash/sha/version/supersede/as-of。
- Obsidian 写入已是一向：REST API → `宏观经济/_pipeline/`；vault 只在「更新日志追加」时被读回，**从不作为真相源**（`lib/vault_writer.py`）。
- 待解读积压实际存在 vault 的 `待解读/`（8 份 2026-08-12 简报），本地 `queue/` 目录是空的。

### 结论

1. **存储选型：SQLite 正确，且应为严格账本的首选。** 判断账本是单进程写、多进程读、年增数千行的量级——SQLite 的 ACID + 零运维完全匹配。迁移触发条件要写明确，避免将来「看到大表就换库」：只有出现**多写入者**（Obsidian 双向同步——已被锁定排除）或**需要 ledger 与时序数据跨库联查且量级上升**时，才评估 PostgreSQL/DuckDB。DuckDB 适合分析侧，不适合做事务账本，不进原型。
2. **ID 策略：ULID + 类型前缀。** `evi_`/`clm_`/`fcst_`/`rev_`/`imp_`/`rit_`/`evt_`。ULID 时间有序，`LedgerEvent` 天然可按 ID 回放，不依赖时钟列。
3. **追加式强制：SQLite trigger 是最低成本、可验证的保障。** 对 7 张 ledger 表挂 `BEFORE UPDATE / BEFORE DELETE → RAISE(ABORT)`；所有写入收敛到单一 `append_event()`，实体变更 + 对应 `LedgerEvent` 在**同一事务**提交。原型验收里加一个「对 ledger 表 UPDATE/DELETE 被拒」的脚本证明。
4. **P0 · T1 — `INSERT OR REPLACE` 会静默覆盖修订值。** 严格账本要求 EvidenceSnapshot 不可变；ledger 表从第一行起就绝不能用 REPLACE。观测表的历史修订保留是既存管线的坑，列为 Phase 2 数据治理项（见 G 节）。
5. **P0 · T2 — 快照没有内容寻址。** EvidenceSnapshot 的 `content_sha256` + `raw_path` 字段不能空着。Phase 1 录入的 2 个证据快照，必须同时落一份 sha256 文件（或快照自含 hash），否则「当时看到的确切字节」无法证明。这正是「修订不覆盖旧依据」的技术落点。
6. **P2 — 两个既存键/读者问题不影响账本启动，但做证据时要意识。** CN 序列在 SQLite 里是**写后无读者**（stats 只对 fred 系列调用）；`cpi_yoy_yoy`（store 键）与 `cpi_yoy`（cache 键）错位。跨序列触发器（M2−CPI、M2−M1）用的是 cache 最新值，不是 store。做交叉验证证据时以「发布稿原文快照」为准，别引 store 的 CN 行。

---

## 三、数据治理维度

### 现状（实测）

- 失败处理：HTTP/parse/列表未匹配 → `logging` + 一次 macOS 通知，**无持久化错误记录**；FRED 的空行被静默丢弃。
- null 行为：CN 指标解析为 None 时不写 SQLite，但 cache + 简报行仍写入「—」；源整体失败时 cache 保留上次有效值（这一点是对的）；**但发布稿缺某个先前存在的指标时，cache 会用 null 覆盖**（cache upsert 无条件）。
- 版本/修订：无 content hash、无 as-of 摄取时间、无 supersede 语义。

### 结论

1. **P0 · G1 — 「失败必须可见」当前不成立。** 设计约束写的是「失败必须可见，不能静默更新为空」，而实测是失败只存在于日志 + 一次性通知。修复方式不是改日志，而是让失败进入账本：`LedgerEvent` 支持 `entity_type='source'` 的失败事件（source、series、error_class、detail、last_valid_reading 引用）。这才是「named failure event」的落地，也是后续「失败是否再次发生」可度量的前提。
2. **P0 · G2 — 展示层 null 会让「当时看到的数据」失真。** 发布稿缺指标时 cache 被 null 覆盖、vault 显示「—」，判断账本引用它就会引用一个「更新后」的真相。对策：**EvidenceSnapshot 记录该次发布实际包含哪些指标、哪些缺失**，判断永远引快照，不引 cache 最终态。
3. **版本与修订语义要落实。** EvidenceSnapshot 靠 `(observed_period, published_at, retrieved_at)` 三元组天然区分「同周期修订」（新发布/修正版 → 新建 snapshot，指向同一 observed_period）与「新观测」（新周期）。设计已定，Phase 1 录入时按此语义执行一次即可固化习惯。
4. **Authority boundary 已基本成立，保持即可。** vault 只读回一次（更新日志追加），从不作为真相。追加式设计继续保证这一点。

---

## 四、分析方法维度

### 结论

1. **可证伪性设计正确，是整套模型的地基。** `Forecast.decision_rule` **前置注册**（预先写清什么算 hit/miss/partial/indeterminate）是防「事后解释」的锚。Phase 1 的那一个预测必须把 decision_rule 写到**可机检**的程度，不能是散文。
2. **P0 · A1 — 现有资产不批量迁入，只选 1 个真实命题。** 设计已定「每主题手工回填一条代表 Claim」，Phase 1 就只做 1 个命题。**建议命题：「中国需求是否进入持续修复」**——2026-08-12 那次待解读正好覆盖 M2−CPI、M2−M1、固投、PMI、CPI/PPI，跨序列触发器也命中该命题的数据面。3 篇现有研究（中国财政、中国货币、美国财政货币错配）各回填 1 条 Claim 放到 Phase 2。
3. **验证点看板是现成的 Forecast 素材。** 中国财政篇已埋「8 月底 1–7 月数据」验证点，美国篇埋「9 月中 FOMC」验证点——这两个天然就是带 `review_due_at` 的 Forecast。Phase 1 的预测可以直接用「中国财政篇」的 8 月底验证点，让原型贴着真实研究走。
4. **错误分类需补裁决程序。** `error_class` 六类合理，但多种因素并存时归哪类要有程序：建议**主类 + 次类 + 一句 rationale**，Phase 1 的 Review 模板按此设计。
5. **置信度用粗三档，不假装精度。** `confidence` 字段一阶段只允许 高/中/低 + 一句话依据；没有 track record 前，任何更细的置信度都是虚假精确。等有十来条预测到期复盘后，再谈校准。

---

## 五、交付呈现维度

### 结论

1. **单向生成已锁定，实现简单。** 队列看板、claim report card、预测到期列表全部从 ledger 生成；显示层带稳定 ID + `_ledger_hash`（该实体事件链的哈希）做陈旧检测；vault 永不写回状态。这是设计里最不需要犹豫的部分。
2. **10 分钟重建测试是验收硬标准。** report card 必须让评审者从 `clm_…` 出发 → 证据快照 → 来源 URL → as-of 时间 → 替代解释 → 预测阈值 → 客户行动，全程可点、无断链。原型就验收这一个真实命题。
3. **P0 · D1 — `evidence_grade` 与 `reviewer` 没有细则。** 建议 `evidence_grade` 用 A/B/C 三级：A=官方一手发布稿 + 交叉验证；B=官方一手单源；C=二手/推算。`reviewer` 一阶段要求「自审 + 第二人签字」双名，不能只留一个人名。
4. **P1 — 待解读停留时间的度量交给 ResearchItem。** 成功指标里有「待解读中位停留 <48h」，但当前把简报挪到 `_done/` 是**手工约定**，无代码支撑。Phase 1 让队列状态由 `ResearchItem` 承载（queued→claimed→completed），vault 的待解读文件只做显示——度量才有起点和终点。

---

## 六、优先级汇总

| 级别 | 项 | 维度 | 做什么 | 阻塞 |
|---|---|---|---|---|
| **P0** | T1 | 技术 | ledger 表禁 REPLACE/UPDATE，SQLite trigger 强制；单事务 append_event | 阻塞 Phase 1（账本核心保证） |
| **P0** | T2 | 技术 | 证据快照内容寻址：sha256 + raw_path，Phase 1 的 2 个快照必须带 | 阻塞 Phase 1（证据不可证明） |
| **P0** | G1 | 数据治理 | 失败事件化：LedgerEvent 支持 source 失败事件 + last valid 引用 | 阻塞 Phase 1（失败必须可见） |
| **P0** | G2 | 数据治理 | 快照记录发布实际包含/缺失的指标，判断只引快照不引 cache | 阻塞 Phase 1（当时数据失真） |
| **P0** | A1 | 分析 | 只选「中国需求是否进入持续修复」1 个命题；不批量迁 | 阻塞 Phase 1（范围控制） |
| **P0** | D1 | 交付 | evidence_grade A/B/C 分级 + reviewer 双签 | 阻塞 Phase 1（客户行动可信度） |
| P1 | — | 分析 | confidence 粗三档；error_class 主+次裁决程序 | 原型内顺手做 |
| P1 | — | 交付 | ResearchItem 接管待解读队列状态（替代手工 _done/ 约定） | 原型内顺手做 |
| P2 | — | 技术 | 观测历史修订保留（REPLACE 治理）；键错位 `cpi_yoy_yoy` 修正 | 下一阶段 |
| P2 | — | 数据 | 8 份积压受控回填 + 3 篇研究各回填 1 条 Claim | 下一阶段 |
| P2 | — | 技术 | PostgreSQL/DuckDB 决策点（触发条件已写明确） | 下一阶段 |
| P2 | — | 交付 | DecisionRecord（客户行为因果）——明确不在阶段一 | 更后 |

---

## 七、路线图

### Phase 0 · 规格锁定（2026-08-13，完成）

- 设计文档锁定严格账本：`ResearchItem` + `LedgerEvent` + 独立状态机 + 阶段一客户行动收窄。

### Phase 1 · 48 小时原型（1 个真实命题）

- **命题**：「中国需求是否进入持续修复」——素材即 2026-08-12 待解读（M2−CPI、M2−M1、固投、PMI、CPI/PPI）。
- **建**：ledger schema（7 表 + trigger）、append-only 事件层、ID 方案（ULID）。
- **录**（设计文档「48 小时原型边界」：
  - 3–5 个指标（建议：M2、M1、固投、PMI 中选）
  - 2 个证据快照（**content-addressed**，带 sha256 + raw_path）
  - 2–3 条 Claim（至少 1 条带替代解释）
  - 1 个带阈值 Forecast——直接用「中国财政篇」的 8 月底验证点（`review_due_at` = 8 月底）
  - 1 条 ClientImplication（action / trigger / stop_condition / evidence_grade / reviewer 双签）
- **Obsidian**：单向生成 1 张队列看板 + 1 张 claim report card。
- **验收门禁**：
  1. 10 分钟重建测试通过（clm ID → 证据链全程可点）
  2. 脚本证明：对 ledger 表 UPDATE/DELETE 被 trigger 拒绝
  3. 1 个 forecast 有前置注册阈值 + `review_due_at`
  4. 1 条 implication 通过审核清单
- **明确不做**：新数据源、双向同步、图谱、dashboard、多用户、自动判断、客户行为归因。

### Phase 2 · 回填 + 纪律飞轮

- 8 份 2026-08-12 待解读积压 → 受控回填样本（ResearchItem 承接）。
- 3 篇现有研究每篇手工回填 1 条代表 Claim。
- 真实跑队列 SLA（48h 中位）+ 升级事件（未认领 24h / 到期 7 天）。
- 首个到期 forecast 复盘 → 第一份 terminal Review（error_class 主 + 次 + rationale）。

### Phase 3 · 扩展决策门

- 选项（全部以 Phase 1–2 证明的价值为前提）：
  - 指标字典 / 证据图谱扩展
  - PostgreSQL/DuckDB（触发条件见技术节）
  - DecisionRecord（客户行为因果归因）
  - 新数据源（海关 WAF 源等既有延期项）
- 原则：**让真实复盘驱动平台边界**，不预先膨胀。

---

## 八、成功指标复核（对照设计文档）

| 指标 | 复核 |
|---|---|
| 10 分钟重建 | 可测；Phase 1 验收项 1 |
| 100% 预测纪律 | 分母=当月 reviewed claims，清晰 |
| review 完成率 | 需补计时起点：`review_due_at`；报中位数 + P90 超时小时数 |
| client-action quality | ✅ 已按严格账本收窄为「通过审核清单」，不承诺客户行为因果 |
| ledger integrity（新增） | Phase 1 用 trigger 测试证明；随机抽一条已结 claim 可从事件链完整重放 |
