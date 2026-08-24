# PR-4 GitHub 审验（Cursor）

> **PR**：https://github.com/cscoheru/macro-pipeline/pull/2  
> **分支**：`feat/houchen-pr4-fts-publish` → `main`  
> **签发**：Cursor（2026-08-24 20:12）

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **GitHub 审验** | **PASS**（建议合并） |
| **本地复验** | 384 passed |
| **CI** | 无 GitHub Actions workflow（`statusCheckRollup` 空） |
| **Merge** | **未授权** — 等用户说「合并 PR」 |

---

## 1. PR 元数据

| 字段 | 值 |
|------|-----|
| State | OPEN |
| Commits | 4（plan ×2 + feat + docs） |
| +/− | +5219 / −107 |
| Base | `main` @ `47e4de3`（PR-3 merge） |

---

## 2. 审验结论

- [x] 实现与 `PR4_ACCEPTANCE_CURSOR` 一致
- [x] FTS5 F-1 修正（无 `transcript_fts.video_id`）
- [x] S-2 claim 页默认关闭
- [x] S-4 AST 隔离守卫
- [x] 无 `insight_publisher` / `store.db` 耦合
- [x] `data/houchen/` 验收红线在测试中保持

**无阻断项。** 合并后 `main` 将含 PR-1～PR-4 完整厚辰栈。

---

## 3. 已知非阻断

1. **`data/store.db` SHA** 仍为 `3c2ceda…`（launchd 宏观 tick；与 PR-4 无关）。
2. **无 CI** — 合并前本地 `pytest scripts -q` 为唯一门禁。
3. **Live Obsidian** — `ObsidianLocalRestWriter` 未实现；合并不自动产生可读研究页。

---

## 4. 下一步（用户裁定门）

| 用户短词 | CC 工单 |
|----------|---------|
| **合并 PR** | `reviews/PR4_MERGE_KICKOFF_2026-08-24.md` |
| **live smoke** | `reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md` |

合并与 live smoke 可先后做；**要看到 Obsidian 成果必须先 live smoke**（合并只把代码进 main）。
