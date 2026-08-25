# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=WAIT_USER
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_USER` |
| **审验** | `reviews/PR4_CONCEPT_EXIT_ACCEPTANCE_2026-08-25.md` — **PASS** |
| **说明** | PR-4 退出已关；下一刀 brief §26 |
| **更新** | 2026-08-25 Cursor（用户「审验」） |

### 用户裁定门（brief §26）

| 你说 | 方向 |
|------|------|
| **全量字幕** | 全频道 caption fetch（分析仍限量） |
| **PR-5** | 只读宏观桥 kickoff |
| **ASR** | 缺字幕视频 |
| **commit** | 审验报告 + CC 交卷文档入库 |
| **停** | 本阶段结束，无新工单 |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
