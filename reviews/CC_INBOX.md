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
| **说明** | v3 扩量+commit 已由 Cursor 完成；**无待执行工单** |
| **报告** | `reviews/PR4_PROMPT_ALIGN_V3_EXPAND_REPORT_2026-08-25.md` |
| **tip** | `8dd685c`（已 push `origin/main`） |
| **更新** | 2026-08-25 Cursor |

### 用户裁定门

| 你说 | 方向 |
|------|------|
| **push** | 推 `8dd685c` 到 `origin/main` |
| **再扩** | 新视频 caption→normalize→analyze→…（需新 kickoff） |
| **审验** | Cursor 对扩量报告做验收 |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
