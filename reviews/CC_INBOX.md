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
| **工单** | `reviews/DUAL_TRACK_PR5_ASR_KICKOFF_2026-08-25.md`（**已修订**） |
| **授权** | 「都做」+「WPS 人工转写，不耗 token」 |
| **P2 变更** | **禁止** faster-whisper；只抽 3 条音频 + `import-transcript` 通道 |
| **更新** | 2026-08-25 Cursor |

### 若你已在跑 whisper

**立刻停**。删未提交的 whisper 依赖/模型下载逻辑；改按修订后 kickoff P2（音频 + 导入）。

### 禁止伪裁定门

P1→P2（修订版）。不要问用户要不要用 WPS。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
