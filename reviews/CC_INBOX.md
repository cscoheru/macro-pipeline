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
| **事件** | PR #2 **已合并** → `main` @ `37ef395` |
| **合并记录** | `reviews/PR4_MERGED_2026-08-24.md` |
| **更新** | 2026-08-24 Cursor |

### 用户裁定门

| 你说 | INBOX 改为 | 工单 |
|------|------------|------|
| **live smoke** | `DO` | `reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md` |

### CC 本状态行为

- `git checkout main && git pull` 同步到 `37ef395`
- **不要**再 merge PR #2（已完成）
- 用户说 live smoke 前不要联网跑 catalog/fetch

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
