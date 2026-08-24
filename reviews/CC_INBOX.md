# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=WAIT_CURSOR
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `WAIT_CURSOR` |
| **工单** | `reviews/PR4_COMMIT_KICKOFF_2026-08-24.md`（已完成） |
| **PR** | https://github.com/cscoheru/macro-pipeline/pull/2 |
| **commits** | `e5c8dc2` (docs) + `3d1b784` (feat) on `feat/houchen-pr4-fts-publish` |
| **push** | origin 已更新 |
| **merge** | 未 merge（等用户授权） |
| **更新** | 2026-08-24 CC |
| **请 Cursor** | 用户贴 GitHub 审验反馈后改 INBOX；用户说「合并 PR」→ CC 再开 merge kickoff |

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |

---

## 给用户的一句话（会话粘贴给 CC）

```text
强制协议：每回合先读 reviews/CC_INBOX.md 与 reviews/CC_STANDING_ORDERS.md。
STATUS=DO 时直接执行工单，不要问我做什么、不要等我转发 Cursor。
做完写 CC_HANDOFF，把 INBOX 改为 WAIT_CURSOR，然后停。
现在执行 INBOX 指向的工单。
```
