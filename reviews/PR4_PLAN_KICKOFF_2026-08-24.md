# Claude Code — 启动 PR-4 计划（仅 Plan-First）

> **签发**：Cursor（2026-08-24）  
> **用户授权**：启动 PR-4 计划  
> **禁止**：写 PR-4 实现代码，直到 Cursor 写出 `PR4_PLAN_AUDIT` 且用户/工单说「启动 PR-4 实现」

---

## 用户摘要

| 项 | 含义 |
|----|------|
| 已授权 | **只写计划** |
| Brief 正式 PR-4 | **Obsidian research map**（§11 / 路线图 PR-4） |
| 历史债 | Brief **PR-2** 原含 FTS5，本地 PR-2 未做；须在计划中处理（见 §2） |
| 你（用户） | 计划落档后等 Cursor 审；一般无需传话 |

---

## 1. CC 立即动作

1. 读本文件 + `reviews/CC_STANDING_ORDERS.md`
2. 只读 brief：
   - `CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` §10（FTS5）、§11（Obsidian）、路线图 PR-2/PR-4/PR-5
   - `lib/insight_publisher.py` / VaultWriter 模式（**只复用协议思想**，禁止写入宏观 insight 状态）
3. 产出计划文件（唯一交付）：

   **`docs/plans/pr4-obsidian-research-map.md`**

4. 写 `reviews/CC_HANDOFF_2026-08-24.md`（或追加）一节：计划路径、未实现、等 Cursor 审验
5. **停止**。不要开 feat 分支写代码，除非工单另说。

可选：在 `feat/houchen-pr4-plan` 上 **仅 commit 计划 + handoff**（勿 push，除非另授）。

---

## 2. 范围裁定（写进计划正文）

### 2.1 Brief 对齐（权威）

**PR-4 = Obsidian research map**，交付至少：

- 覆盖报告、视频页、概念页、预测候选页、review queue
- 研究库独立 Obsidian 路径（如 `Research/世界苦茶/`），**不得**进宏观目录
- 独立发布记录；PUT → GET 读回 → SHA；失败不标 published
- 稳定重生成 / 幂等发布测试
- 宏观隔离：不写 `data/store.db` / 宏观 insight ledger

退出条件（brief）：至少一张可用概念页；重复发布无漂移；发布失败不误记 published。

### 2.2 FTS5 债（必须在计划中二选一，推荐 A）

Brief 把 FTS5 放在 **PR-2**；本地 PR-2/PR-3 未交。计划须明确：

| 选项 | 内容 | Cursor 倾向 |
|------|------|-------------|
| **A（推荐）** | PR-4 **Phase 0**：schema 增量 FTS5（transcript / claim / concept+alias）+ 固定查询集基准 + CLI `search`；再 Phase 1 Obsidian 页 | 默认采用 |
| B | 独立薄 PR「PR-3.5 / PR-4a」只做 FTS，Obsidian 另开 | 仅当文件爆炸时 |

写明 tokenizer 策略：先 unicode / 二元辅助字段 + 固定查询集，**不**引入 embedding（brief §10）。

### 2.3 明确 Out of scope

- 真模型 eval、全频道分析
- 宏观 bridge（brief **PR-5**）
- 向量检索、自定义 UI
- 直接调用 `insight_publisher` 写宏观状态

---

## 3. 计划文件必须含有的章节

与 `docs/plans/pr3-claim-extraction.md` 同构：

1. Context / Approach  
2. Schema（若 Phase 0：FTS 虚表 + triggers；发布记录表）  
3. Migrations / Paths（artifacts 根、Obsidian 前缀配置）  
4. 模块拆分 + **>8 文件理由**（brief §707）  
5. Publisher 适配（REST / 读回 hash / 幂等）  
6. 页面模板清单（coverage / video / concept / forecast / review queue）  
7. Runner + CLI（`publish` / `search` 等）  
8. Fixtures + 测试矩阵  
9. Critical files 表  
10. Verification 命令  
11. Out of scope  
12. 风险（中文 FTS、REST 不可用时的行为）

复用：`houchen_quote`、只读 status/coverage、VaultWriter **协议**（新 `houchen_publish*` 模块，隔离 env）。

---

## 4. 硬禁令

- 不实现 PR-4 代码  
- 不 push main、不 force、不部署、不真模型  
- 不改三份 Codex 基线文档正文  

---

## 5. Cursor 下一步（你完成后）

Cursor 读计划 → 写 `reviews/PR4_PLAN_AUDIT_*.md` → 用户/工单「启动 PR-4 实现」后才编码。

---

## 6. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 | 用户授权启动 PR-4 **计划**；范围 = brief Obsidian + FTS 债处理 |
