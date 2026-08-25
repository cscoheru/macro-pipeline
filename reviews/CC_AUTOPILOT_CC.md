# CC Autopilot 巡检命令（给 Claude Code）

压缩、Stop、idle 之后都跑这一段。**禁止空等用户。**

```text
git pull --ff-only origin main
读 reviews/CC_INBOX.md 与 reviews/CC_AUTOPILOT.md
python3 scripts/cc_autopilot_inspect.py
```

| INBOX | 你做什么 |
|-------|----------|
| `DO` | 立刻执行当前工单，不问用户 |
| `WAIT_CURSOR` | 不要问「Cursor 好了吗」。**Stop**（hook 会 poll）。不要 idle |
| `WAIT_USER` | 才真正停 |

硬禁令：已有 `asr-transcribe` pid 或 `.lock` → 不准再开；不准 `rm` ASR lock/tmp。

当前工单以 `reviews/CC_INBOX.md` 为准（现为 ASR 扩 5）。
