# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **工单** | `reviews/PR4_CONCEPT_EXIT_KICKOFF_2026-08-25.md` |
| **用户授权** | 按计划推进、**无必要不问用户**（2026-08-25） |
| **更新** | 2026-08-25 Cursor（驳回伪裁定门） |

### 禁止伪裁定门（立即生效）

以下 **不是** WAIT_USER，**禁止**再问用户：

- 「继续跑剩下 6 个」vs「停」
- v3 smoke 是否扩 7 视频（**已由 Cursor 跑完并 publish**）
- 是否做概念页（**本工单必做**）

**立刻执行** `PR4_CONCEPT_EXIT_KICKOFF` 全文：

1. §1 概念页 render+publish（门禁 ≥1 可用页）
2. §2 竖切补到 ≥8（fetch/normalize/analyze…；跳过永久失败 ID）
3. 写 REPORT + HANDOFF；INBOX → `WAIT_CURSOR`

已完成可跳过、在报告注明即可：7 视频 v3 analyze/validate/render/publish。

### 若你卡在旧对话

忘掉「剩下 6 个 / 停」。以**本文件 + CONCEPT_EXIT kickoff**为准，不要等用户短词。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 仅 brief §26（全量字幕/PR-5/ASR）才用；**本工单不用** |
