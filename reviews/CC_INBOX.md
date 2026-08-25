# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。  
> 总线：`reviews/AGENT_BUS.md`。交卷 `WAIT_CURSOR` 后 Stop，hook 会 pull。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **剩余** | ASR 试点未完成的 streams |
| **工单** | `reviews/ASR_LOCAL_PILOT_KICKOFF_2026-08-25.md` |
| **已完成（勿重做）** | 概念 P4 PASS；`KLJJuMybVsc` PASS；`epg0aoUbPN4` 已 accepted |
| **还要做** | 单进程转写 `E9uJV2bwzjM`→`jfXAn1dgkyw`；有 `.lock` 则 **禁止** 再开 asr-transcribe |
| **更新** | 2026-08-25 杀掉 CC 并行 whisper；flock 防重入 |

完成后 `WAIT_CURSOR`（Cursor 会自动验收并可能派 ASR 扩 5）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；Cursor 自动验收 |
| `WAIT_USER` | 仅协议表内裁定门 |
