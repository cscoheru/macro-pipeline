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
| **工单** | `reviews/PR4_REAL_MODEL_EXPAND_KICKOFF_2026-08-24.md` |
| **触发** | 用户「真模型，然后扩视频」 |
| **实现** | Cursor 已接线 `houchen_analyze.env` + 真 provider |
| **更新** | 2026-08-24 Cursor |
| **完成后** | HANDOFF + `PR4_REAL_MODEL_EXPAND_REPORT_*`；INBOX → `WAIT_CURSOR` |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
