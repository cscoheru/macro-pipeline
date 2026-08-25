# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。  
> 总线：`reviews/AGENT_BUS.md`。交卷 `WAIT_CURSOR` 后 Stop，hook 会 pull。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **工单** | `reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md` |
| **已完成（勿重做）** | ASR 试点 3/3 PASS（101/100/099 = 7/16/7 accepted）；报告 `reviews/ASR_LOCAL_PILOT_REPORT_2026-08-25.md` |
| **还要做** | 单进程转写上表 5 个 stream；有 pid/`.lock` **禁止**再开 asr-transcribe |
| **更新** | 2026-08-25 Cursor Autopilot 验收试点并派扩 5 |

完成后 `WAIT_CURSOR`。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Cursor 自动验收 |
| `WAIT_USER` | 仅协议表内裁定门 |
