# PR-4 计划审核 — Cursor

> **签发**：Cursor（2026-08-24，主动进度检查）  
> **计划**：`docs/plans/pr4-obsidian-research-map.md`  
> **CC handoff**：`reviews/CC_HANDOFF_2026-08-24.md` §B  
> **分支**：`feat/houchen-pr4-plan`（未 push；无实现代码）✅

---

## 用户摘要

| 项 | 结果 |
|----|------|
| CC 是否完成计划 | **是**（已落档，等审） |
| 计划质量 | **有条件批准** — 须先改计划 2 处再实现 |
| 你需裁定 | **启动 PR-4 实现**（接受审计修正）或 **先改计划** |

---

## 1. Kickoff 核对

| Kickoff 要求 | 结果 |
|--------------|------|
| 路径 `docs/plans/pr4-obsidian-research-map.md` | ✅ |
| Phase 0 FTS + Phase 1 Obsidian（选项 A） | ✅ |
| 强制章节齐全 | ✅ |
| >8 文件拆分理由 | ✅（+4 模块） |
| 无实现代码 | ✅ |
| 宏观 / insight_publisher 隔离 | ✅ |
| dry-run 默认 + `--apply --operator-authorized` | ✅ |

---

## 2. 必须修正（实现前写进计划）

### F-1（阻断）— `transcript_segment` 无 `video_id`

当前 schema：`transcript_segment` 只有 `transcript_version_id`，**没有** `video_id`。

计划 §1.2 触发器写 `new.video_id` → **无法编译/运行**。

**改法（任选，写入计划）：**

- FTS 列只存 `transcript_version_id`；`search` JOIN `transcript_version` 取 `video_id`；或  
- 触发器内 `SELECT video_id FROM transcript_version WHERE … = new.transcript_version_id`

### F-2（阻断文档错误）— Verification 红线 SHA

§9 写：

```text
shasum -a 256 data/store.db  # expect 47e4de3…
```

`47e4de3` 是 **git commit**，不是 store 哈希。应仍为：

`52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7`

---

## 3. 建议修正（非阻断）

| ID | 项 |
|----|-----|
| S-1 | `houchen_publish_paths` 可并入 `houchen_paths` 的 publish 命名空间以减文件数；若保留独立模块，实现时保持 API 极薄 |
| S-2 | claim 页「默认 rollup」写清：v1 是否生成 per-claim 页（建议 **默认不生成**，只进 video/concept） |
| S-3 | Phase 0 / Phase 1 可同一 feat 分支，但 **测试门禁串行**：search 绿再 render/publish |
| S-4 | 补一条：`grep -R insight_publisher lib/houchen_publish*` 与 `grep store.db` 的 CI/测试断言 |

---

## 4. Claude Code 工单

### 立即（计划修订，仍无实现代码）

1. 修订 `docs/plans/pr4-obsidian-research-map.md`：关闭 **F-1、F-2**（及可选 S-*）
2. 更新 `reviews/CC_HANDOFF_2026-08-24.md`：注明审计修正已应用
3. **停止**；等用户/本文件说「启动 PR-4 实现」

### 「启动 PR-4 实现」后（尚未授权）

1. `feat/houchen-pr4-fts-publish`（或沿用 `feat/houchen-pr4-plan` 改名）从 `main@47e4de3`
2. 严格 Phase 0 → Phase 1；每阶段 `pytest` + 红线
3. 遵守 `CC_STANDING_ORDERS.md`

---

## 5. 用户裁定门

| 回复 | 动作 |
|------|------|
| **启动 PR-4 实现** | CC 先落地 F-1/F-2 计划补丁，再按 Phase 0→1 编码 |
| **先改计划** | CC 只修计划，再等 Cursor 复审 |
| **暂缓** | 停 |

---

## 6. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 17:59 | 主动发现计划已交；有条件批准（F-1/F-2） |
