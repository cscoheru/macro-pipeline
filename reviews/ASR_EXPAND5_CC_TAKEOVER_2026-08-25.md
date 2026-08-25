# Claude Code — 扩 5 接手（不要等 Cursor）

> **签发**：Cursor Autopilot（2026-08-25 17:14）  
> **前置**：`reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md` 仍有效  
> **禁止**问用户；**禁止**第二路 `asr-transcribe`；**禁止** `rm` lock/tmp

INBOX 保持 `DO`。你不是在等 Cursor 点头。按下面做。

## 现在谁在转写

| | |
|--|--|
| whisper | PID **25239**（`7L9X75dL1Dg`，持有 `.lock` + `.vtt.tmp`） |
| Cursor 父 zsh | PID **25206**（若仍在，会在 25239 结束后自己跑 import→其余 4 支） |

`asr_n>=1` 或有 `.lock` → **不准**再开 `asr-transcribe`。

## 你每 60s 做

```bash
python3 scripts/cc_autopilot_inspect.py
# 以及：kill -0 25239 / 25206
```

| 看到 | 做 |
|------|----|
| 25239 仍在 | 继续等。写 HANDOFF 一行进度（tmp 字节）。不要 Stop 空转。 |
| 25239 死了，**25206 仍在** | 父 loop 还活着：你**不要** import/analyze/asr。等 `AGENT_EXPAND5_DONE` 或 25206 退出。 |
| 25239 死了，**25206 也死了**，且无其它 asr pid | **你接手**：对已有 VTT 的 ID 跑 import→analyze→validate→render；其余 ID 串行 asr（每次先确认 `asr_n=0`）。音频已在 `data/houchen/asr/audio/<id>.webm`。Python 用 `/usr/local/bin/python3`（homebrew python 缺 yaml）。 |
| 5 支都有 `transcript_version` 或 `AGENT_EXPAND5_DONE` | 抽检 GO/DEFER（勿贴正文）→ `reviews/ASR_EXPAND5_REPORT_2026-08-25.md` → HANDOFF → INBOX=`WAIT_CURSOR` → commit+push |

## 红线（同 kickoff）

零 shorts；不重转 WPS/试点六支；不写 `store.db`；转写零 DeepSeek token。
