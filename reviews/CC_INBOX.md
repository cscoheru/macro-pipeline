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
| **工单** | `reviews/POST_CLAIM_CATCHUP_KICKOFF_2026-08-26.md`（**已完成**） |
| **现况** | A 概念 138 publish；B stream 0 待 publish（Cursor 已 50/50）；C MiniMax 14 videos: 10 ✅ / 1 ✅CC / **4 DEFER（MiniMax content filter 422）** |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成（勿重做）** | 试点 3；扩 5；5b–5j；MiniMax batch1–9 + CC f_jd_j3eEuE；POST_CLAIM_CATCHUP A+B+C |
| **报告** | `reviews/POST_CLAIM_CATCHUP_REPORT_2026-08-26.md` |
| **更新** | 2026-08-26 20:55 CC：235 total published（+18 net）；4 videos DEFER（MiniMax HTTP 422 input new_sensitive） |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
