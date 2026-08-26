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
| **工单** | `reviews/CLAIM_MINIMAX_M3_BATCH3_KICKOFF_2026-08-26.md` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | 试点 3；扩 5；5b–5j ASR。MiniMax-M3 claim batch1–2。**禁止 DeepSeek** |
| **还要做** | MiniMax-M3 抽 claim 第 3 批（含 `2zyAnqllesM` 补跑）。有 analyze pid 禁止第二路。禁止 ASR。**禁止 Wait pid 74695** |
| **更新** | 2026-08-26 16:51 Cursor：batch2 4/5 PASS，续 batch3 |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
