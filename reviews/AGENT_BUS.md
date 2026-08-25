# Cursor ↔ Claude Code 通信总线

> 用户不传话。汇合点 = **git `main` 上的 `reviews/`**。  
> 两边都要 **自动轮询**，不要等人把文件贴进聊天。

---

## 文件

| 路径 | 谁写 | 谁读 |
|------|------|------|
| `reviews/CC_INBOX.md` | Cursor 派工 `DO`；CC 交卷 `WAIT_CURSOR` | **双方每轮必读** |
| `reviews/bus/state.json` | 派工时 Cursor bump `cursor_seq` | 双方 |
| `reviews/*_KICKOFF_*` | Cursor | CC 执行 |
| `reviews/*_REPORT_*` | CC | Cursor 验收 |
| `reviews/*_ACCEPTANCE_*` | Cursor | 记录 |
| `reviews/SUPERVISOR_STATE.md` | Cursor 值守 | 人类/Cursor |

## 状态机

```text
DO  --CC 做完-->  WAIT_CURSOR  --Cursor 验收+派下一刀-->  DO
                 WAIT_USER     --仅协议表裁定门-->
```

## Cursor（Autopilot 巡检）

详见 `reviews/CC_AUTOPILOT.md`。每 120s 脚本巡检；仅 `severity!=OK` 叫醒 Cursor。

1. `python3 scripts/cc_autopilot_inspect.py`
2. INBOX=`WAIT_CURSOR` → 验收 → 写下一工单 → INBOX=`DO` → **立刻 `git push`**
3. 有 pid/lock → **禁止**再开 `asr-transcribe`；禁止 `rm` ASR lock/tmp

## Claude Code（本仓库 hook）

`.claude/settings.json`：

- **SessionStart / PreCompact**：`git pull` + Autopilot 注入（压缩后禁止 idle）
- **Stop**：  
  - `DO` → 禁止退出，执行工单  
  - `WAIT_CURSOR` → hook 内 poll；到期前一直拦着待命，不 idle  
  - `WAIT_USER` 或超过 `watch_until` → 允许退出

CC **禁止**压缩后空等用户。命令：`reviews/CC_AUTOPILOT_CC.md`。

## 防打架

- 改 INBOX 前 `git pull`
- 只改 STATUS 那一块，工单路径写在表里
- 冲突：Cursor 的 `DO`/`WAIT_USER` 优先；CC 只应写 `WAIT_CURSOR`
