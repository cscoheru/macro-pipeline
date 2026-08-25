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
| **常驻** | `reviews/CC_AUTOPILOT_CC.md`（Stop / compact / SessionStart 后巡检待命） |
| **已完成（勿重做）** | ASR 试点 3/3 PASS；报告 `reviews/ASR_LOCAL_PILOT_REPORT_2026-08-25.md` |
| **还要做** | 单进程转写扩 5；有 pid/`.lock` **禁止**再开 asr-transcribe |
| **更新** | 2026-08-25 Cursor：下达 CC Autopilot 待命；扩 5 仍有效 |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
