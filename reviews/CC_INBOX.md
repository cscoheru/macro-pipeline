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
| **工单** | 扩 5 本地收尾完成；报告 `reviews/ASR_EXPAND5_REPORT_2026-08-25.md` |
| **常驻** | `reviews/CC_AUTOPILOT_CC.md` |
| **已完成** | ASR 试点；扩 5 转写+import+analyze；video render/publish；78 概念本地 refresh。**禁止再 DeepSeek** |
| **队列** | **空** |
| **更新** | 2026-08-25 19:24 Cursor：本地收尾交卷 |

完成后 `WAIT_CURSOR`（不要 idle；Stop 让 hook 接着 poll）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Stop 待命，hook 轮询 |
| `WAIT_USER` | 仅协议表内裁定门（才允许真正停） |
