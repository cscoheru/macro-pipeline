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
| **刚完成** | WPS 三直播 analyze→publish — **PASS**（`reviews/WPS_STREAM_ANALYZE_ACCEPTANCE_2026-08-25.md`） |
| **结果摘要** | 20 accepted / 3 rejected；3 vault pages HTTP 200；store SHA 不变 |
| **下一工单** | 无；等用户短词定下一步 |
| **更新** | 2026-08-25 Cursor 审验 |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
