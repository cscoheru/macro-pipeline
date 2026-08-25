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
| **工单** | `reviews/CONCEPT_REFRESH_PR5_LAND_KICKOFF_2026-08-25.md` |
| **目标** | 概念页刷新（≤12）+ 收 PR-5（测试/scan/git land/acceptance） |
| **排除** | `scripts/asr_transcribe.py`；全库 analyze；whisper |
| **更新** | 2026-08-25 Cursor |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
