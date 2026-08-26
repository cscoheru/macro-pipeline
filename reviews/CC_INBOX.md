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
| **工单** | （无；本地语料队列空，hook poll 待命） |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | 试点 3；扩 5；5b–5j；MiniMax batch1–9；POST_CLAIM_CATCHUP A+B+C |
| **验收** | `reviews/POST_CLAIM_CATCHUP_ACCEPTANCE_2026-08-26.md` PASS |
| **还要做** | 下一张 `DO` 才能干活。本地 streams/videos 已收完。4 支 MiniMax 422 不重派。637 / shorts / 云 ASR 仍不开 |
| **更新** | 2026-08-26 21:45 Cursor：误用 WAIT_USER 把 CC 停了；改回 WAIT_CURSOR 让 hook 盯着 |

Stop（hook poll）。禁止 ASR。禁止 Wait pid 74695。禁止 DeepSeek。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
