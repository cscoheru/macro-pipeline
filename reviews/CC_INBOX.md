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
| **工单** | `reviews/SECTION26_BUNDLE_KICKOFF_2026-08-25.md` |
| **授权** | 用户「全量字幕 / PR-5 / ASR」（2026-08-25） |
| **顺序** | A 全量字幕 → B ASR 预研（无实现）→ C PR-5 计划（无实现） |
| **禁止** | 全频道 analyze；ASR 下模型；PR-5 写代码 |
| **更新** | 2026-08-25 Cursor |

### 禁止伪裁定门

不要问「先做哪个」。按 kickoff A→B→C 执行到底，然后 `WAIT_CURSOR`。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
