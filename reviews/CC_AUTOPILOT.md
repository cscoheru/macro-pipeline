# CC Autopilot 巡检

Cursor 值守 Claude Code：脚本巡检 + 异常才叫醒 + hook 防第二路 whisper。

## 每轮

```bash
python3 scripts/cc_autopilot_inspect.py
```

| severity | Cursor 做什么 |
|----------|----------------|
| `OK` | 只更新 `reviews/SUPERVISOR_STATE.md` 一行；不改 INBOX；不开转写 |
| `WARN` | 写入 STATE（store SHA 漂移 / tmp 超过 25min 未涨） |
| `ACTION` | 见下表，然后必要时 `git push` |

## actions

| action | 做 |
|--------|----|
| `kill_duplicate_whisper` | 只留 **一个** `asr-transcribe`（保留持有当前 `.vtt.tmp` 路径的 pid）；杀掉其余 |
| `accept_inbox` | INBOX=`WAIT_CURSOR` → 验收报告 → 派下一刀 `DO` → `git push origin main` |
| `finish_import_analyze` | VTT 已在且无 whisper：Cursor **可以**对该 ID 跑 import → analyze → validate → render → publish。**仍禁止** `asr-transcribe` |
| `mark_stalled` | STATE 记 stalled；**不**重复派同一张工单 |

## 硬禁令

- 有 pid / `.lock` → 不准 `asr-transcribe`
- 不准 `rm` `data/houchen/asr/vtt/*.lock` 或 `*.tmp` 来「重试」
- 不准写 `data/store.db`
- Cursor 不跑 analyze / import / 第二套 for 循环

## 叫醒

本地 loop：每 120s 跑 inspect；**仅 `severity=ACTION` 叫醒**。`WARN`（如 store SHA 漂移）只打进 STATE，每 30min 心跳一次。已停旧的 8min `houchen_supervisor` loop。

## Hook

- Cursor：`.cursor/hooks.json` → `cc_asr_guard.py --harness cursor`
- CC：`.claude/settings.json` PreToolUse Bash → 同一脚本 `--harness claude`
