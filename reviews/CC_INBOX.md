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
| **工单** | `reviews/DUAL_TRACK_PR5_ASR_KICKOFF_2026-08-25.md` |
| **授权** | 用户「都做」（PR-5 实现 + ASR 试点） |
| **顺序** | P1 PR-5 →（测试绿）→ P2 ASR 3 streams |
| **更新** | 2026-08-25 Cursor |

### 禁止伪裁定门

不要问先做哪个。按 kickoff P1→P2。P1 失败则停并 `WAIT_CURSOR`。

报告禁贴字幕/ASR 正文。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
