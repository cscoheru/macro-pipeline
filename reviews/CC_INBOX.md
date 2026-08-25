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
| **工单** | `reviews/CORPUS_EXPAND_KICKOFF_2026-08-25.md` |
| **计划** | `docs/plans/full-caption-corpus.md` |
| **目标** | P1 字幕抓取 → 扩竖切 ≥25 视频 accepted → macro review PR-5.1 |
| **排除** | whisper；WPS 下一批；全 129 analyze |
| **更新** | 2026-08-25 Cursor |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
