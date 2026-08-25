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
| **v3 扩量** | `reviews/PR4_PROMPT_ALIGN_V3_EXPAND_REPORT_2026-08-25.md` |
| **7 视频** | 30 accepted；Obsidian 7 页已同步 |
| **更新** | 2026-08-25 Cursor（扩量+commit 进行中） |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
