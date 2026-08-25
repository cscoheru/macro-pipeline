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
| **工单** | `reviews/ASR_EXPAND5_ANALYZE_KICKOFF_2026-08-25.md`（**被外部阻断**） |
| **现况** | 父 zsh 25206 已 exit（18:58）；5/5 VTT+transcript_version ✅；**analyze 全 HTTP 402（DeepSeek Insufficient Balance）** |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | ASR 试点 3/3 PASS；扩 5 转写+import 5/5 PASS |
| **还要做** | **硬阻断待 Cursor 派修复 DO**：A) 充值 DeepSeek / B) 切 anthropic|minimax / C) 接受「无 claims」直接报告 |
| **更新** | 2026-08-25 19:00 CC：analyze 跑了一次 7L9X75dL1Dg → 402；curl 验证 `Insufficient Balance`；详细见 `reviews/CC_HANDOFF_2026-08-25.md` §19:00 |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
