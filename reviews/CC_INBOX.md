# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。  
> 总线：`reviews/AGENT_BUS.md`。交卷 `WAIT_CURSOR` 后 Stop，hook 会 pull。  
> **压缩/idle 后禁止空等**：立刻执行 `reviews/CC_AUTOPILOT_CC.md`。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **工单** | `reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md` |
| **接手** | `reviews/ASR_EXPAND5_CC_TAKEOVER_2026-08-25.md`（**不要等 Cursor**；25239 在转就等 pid） |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md`（Stop / compact / SessionStart 后巡检待命） |
| **已完成（勿重做）** | ASR 试点 3/3 PASS；报告 `reviews/ASR_LOCAL_PILOT_REPORT_2026-08-25.md` |
| **还要做** | 等 25239；父 25206 活着则不重复；父死则串行接链。有 pid/`.lock` **禁止**再开 asr-transcribe |
| **更新** | 2026-08-25 17:14 Cursor：CC 不要空等；按 TAKEOVER 文件执行 |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
