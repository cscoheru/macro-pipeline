# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **工单** | `reviews/SECTION26_BUNDLE_KICKOFF_2026-08-25.md` |
| **授权** | 用户「全量字幕 / PR-5 / ASR」 |
| **故障** | 旧会话 compaction → `data_inspection_failed`（代理内容审查，非 pipeline bug） |
| **恢复** | **新开会话**；禁止对本话题 `/compact`；报告只写 ID+计数 |
| **更新** | 2026-08-25 Cursor |

### 恢复后立刻做

1. `git pull`
2. 读本文件 + `SECTION26_BUNDLE_KICKOFF`（含「上下文纪律」）
3. 从阶段 A 继续（已完成的 caption 批次用 sqlite **COUNT** 核对后跳过，勿重贴字幕）

### 禁止伪裁定门

不要问用户「要不要换模型 / 要不要停」。按 kickoff A→B→C 做完 → `WAIT_CURSOR`。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
