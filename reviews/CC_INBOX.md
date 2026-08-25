# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=WAIT_USER
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_USER` |
| **审验** | `reviews/SECTION26_BUNDLE_ACCEPTANCE_2026-08-25.md` — **PASS** |
| **说明** | A/B/C 交卷已过；等用户短词开下一刀 |
| **更新** | 2026-08-25 Cursor |

### 用户裁定门

| 你说 | 方向 |
|------|------|
| **ASR试点** | 3 streams + faster-whisper（新 kickoff） |
| **PR-5实现** | 按 `docs/plans/pr5-macro-bridge.md` 编码 |
| **都做** | PR-5 实现 + ASR 试点（Cursor 排期后 DO） |
| **停** | 无新工单 |
| **commit** | 交卷/审验文档入库 |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
