# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。  
> 总线：`reviews/AGENT_BUS.md`。交卷 `WAIT_CURSOR` 后 Stop，hook 会 pull。  
> **压缩/idle 后禁止空等**：立刻执行 `reviews/CC_AUTOPILOT_CC.md`。

---

## 状态

```text
STATUS=WAIT_CURSOR
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_CURSOR` |
| **工单** | `reviews/CLAIM_MINIMAX_M3_BATCH1_KICKOFF_2026-08-26.md` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | 试点 3；扩 5；5b–5j ASR。MiniMax-M3 claim 首批 5（analyze 5/5；accepted 19）。**禁止 DeepSeek** |
| **还要做** | 无（本工单交卷） |
| **更新** | 2026-08-26 16:37 CC：batch1 报告 `CLAIM_MINIMAX_M3_BATCH1_REPORT_2026-08-26.md` |

Stop。禁止 ASR。禁止 Wait pid 74695。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
