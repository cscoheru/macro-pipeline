# macro-pipeline — Claude Code

每回合先读并遵守：

1. `reviews/CC_INBOX.md`（唯一行动指针）
2. `reviews/AGENT_BUS.md`（与 Cursor 的 git 总线）
3. `reviews/CC_STANDING_ORDERS.md`

`STATUS=DO` → 立刻执行工单，不问用户。  
交卷 `WAIT_CURSOR` 后 **Stop**（hook poll）。压缩后立刻读 `reviews/CC_AUTOPILOT_CC.md`，禁止 idle 等用户。  
不要请用户在 Cursor 和 CC 之间传话。  
ASR：已有 `asr-transcribe` 或 `.lock` 时禁止再开；禁止 `rm` ASR lock/tmp。
