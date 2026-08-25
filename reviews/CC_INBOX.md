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
| **工单** | `reviews/PR4_PROMPT_ALIGN_V3_KICKOFF_2026-08-25.md` |
| **门禁** | validate `validated` ≥ 1 → render `--from-db` → publish |
| **更新** | 2026-08-25 Cursor（用户「v3」） |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
