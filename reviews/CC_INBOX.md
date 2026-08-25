# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。  
> 总线：`reviews/AGENT_BUS.md`。交卷 `WAIT_CURSOR` 后 Stop，hook 会 pull。  
> **压缩/idle 后禁止空等**：立刻执行 `reviews/CC_AUTOPILOT_CC.md`。

---

## 状态

```text
STATUS=WAIT_USER
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_USER` |
| **工单** | 用户已选 **B**，但 `houchen_analyze.env` / `insight.env` **没有** `ANTHROPIC_API_KEY` 或 `MINIMAX_API_KEY` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | ASR 试点；扩 5 asr-transcribe（勿再开） |
| **还要** | 往 `config/houchen_analyze.env` 写入可用的 anthropic 或 minimax key（chmod 600），或改选 A/C |
| **更新** | 2026-08-25 19:04 Cursor：B 无法切换——本机只有 DeepSeek key（已 402） |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
