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
| **工单** | `reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md`（**未验收 PASS**） |
| **现况** | 父 zsh **25206** 串行转写中：`7L9X75dL1Dg` VTT+transcript 已入库、accepted=0；whisper **29901** 正在转 `TFjqgua7jKk` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | ASR 试点 3/3 PASS |
| **还要做** | **Stop 待命**（hook poll）。不准第二路 asr-transcribe；不准 rm lock/tmp。loop 结束后 Cursor 派 `DO`：补 5 支 analyze（`config/houchen_analyze.env`）+ 报告 |
| **更新** | 2026-08-25 17:30 Cursor：按用户 `INBOX=WAIT_CURSOR`；扩 5 未完成，不派概念 refresh |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
