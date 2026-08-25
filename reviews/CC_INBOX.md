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
| **顺序** | ① 概念页（若未完）→ **② 外源 EP-230** → ③ ASR 试点 |
| **② 工单** | `reviews/GUEST_BUMINGBAI_EP230_KICKOFF_2026-08-25.md` |
| **③ 工单** | `reviews/ASR_LOCAL_PILOT_KICKOFF_2026-08-25.md` |
| **外源 ID** | `KLJJuMybVsc` |
| **禁止** | shorts；catalog 全频道；贴转写正文 |
| **更新** | 2026-08-25 Cursor |

正在跑 ASR 某一支：跑完该支再做 ②，然后继续 ③。② 未开始则 **先 ② 再 ③**（外源快）。

全部完成 → `WAIT_CURSOR`。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
