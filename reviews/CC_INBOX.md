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
| **工单** | `reviews/ASR_EXPAND5_ANALYZE_KICKOFF_2026-08-25.md` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | ASR 试点；扩 5 asr-transcribe+import 5/5（勿再开 asr） |
| **还要做** | 用户选 **A**：`provider deepseek` 补跑 5 支 analyze → validate → render → publish → 报告。仍 402 则交卷勿死循环 |
| **更新** | 2026-08-25 19:12 Cursor：用户改选 A |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
