# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=WAIT_CURSOR
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_CURSOR` |
| **工单** | `reviews/SECTION26_BUNDLE_KICKOFF_2026-08-25.md` |
| **授权** | 用户「全量字幕 / PR-5 / ASR」 |
| **完成** | A(frozen 50, missing 79, pending 0) + B(GO_PILOT) + C(6 files ≤8) |
| **报告** | `reviews/SECTION26_BUNDLE_REPORT_2026-08-25.md` |
| **SHA** | `4a8e409b…` before == after ✅ |
| **更新** | 2026-08-25 CC |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
