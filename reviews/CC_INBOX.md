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
| **顺序** | ① 概念页（若未完成）→ ② ASR 试点 |
| **①** | `reviews/CONCEPT_INCREMENTAL_REFRESH_KICKOFF_2026-08-25.md` |
| **②** | `reviews/ASR_LOCAL_PILOT_KICKOFF_2026-08-25.md` |
| **禁止** | **全部 shorts**（切片）；勿等用户插话 |
| **更新** | 2026-08-25 Cursor |

概念页已交卷则跳过 ①，直接 ②。两件都完成后 `WAIT_CURSOR`。

### 试点 streams

```text
epg0aoUbPN4
E9uJV2bwzjM
jfXAn1dgkyw
```

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
