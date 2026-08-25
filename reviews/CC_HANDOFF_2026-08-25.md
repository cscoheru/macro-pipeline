# CC Handoff — 2026-08-25 (ASR Expand 5)

> **响应**：`reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md`
> **状态**：进行中（Cursor 已起 loop；CC 等待接手）

---

## 本回合要点

### 1. 协议冲突检测

本回合起点（16:56 UTC）扫描 `ps` 时发现：

| 进程 | PID | 动作 |
|------|-----|------|
| `zsh` 串行 loop | 22703 | 跑 5 个 ID 的 `asr-transcribe → import → analyze → validate → render → publish` |
| `yt-dlp` | 23130 → 22929 | 下音频 (`TFjqgua7jKk` → `Xp4GBvKBPww`) |

loop 脚本结构（自 Cursor 的命令 shell 启动）：
```bash
for VID in 7L9X75dL1Dg TFjqgua7jKk Xp4GBvKBPww XUKmvcu9sss Ft5Xg-Wv52U; do
  yt-dlp … || continue
  python3 scripts/houchen_pipeline.py asr-transcribe --video-id "$VID" --model small || continue
  python3 scripts/houchen_pipeline.py import-transcript --video-id "$VID" --from-file "data/houchen/asr/vtt/${VID}.vtt" || continue
  python3 scripts/houchen_pipeline.py analyze --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow || continue
  python3 scripts/houchen_pipeline.py validate --video-id "$VID" || continue
  python3 scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db || continue
done
python3 scripts/houchen_pipeline.py publish --kind video --apply --operator-authorized --actor asr-expand-5
echo STORE_BEFORE=… STORE_AFTER=… FAIL_COUNT=…
echo AGENT_EXPAND5_DONE
```

### 2. CC 的决策

- **单进程 ASR 硬规则**：`reviews/CC_AUTOPILOT.md` 第 28 行 — 「有 pid / `.lock` → 不准 `asr-transcribe`」
- CC **不开第二路** ASR / 不 `rm` lock/tmp
- CC **等 Cursor loop 完成**（监听 `AGENT_EXPAND5_DONE` + DB 表 + VTT 落盘）
- CC **接手验证**（清点 transcript / accepted / rejected / store SHA），写 `reviews/ASR_EXPAND5_REPORT_2026-08-25.md`
- CC **不重跑**已落盘步骤；失败则报告 ID+error_class

### 3. 当前进度（16:58 UTC，loop 起点 +2:15）

| video_id | audio | VTT | import | analyze | render | 备注 |
|----------|-------|-----|--------|---------|--------|------|
| `7L9X75dL1Dg` | ✅ 77MB | ⏳ 待 | — | — | — | audio 落盘 16:56 |
| `TFjqgua7jKk` | ✅ 118MB | ⏳ 待 | — | — | — | audio 落盘 16:57 |
| `Xp4GBvKBPww` | ⏳ .part 134MB | — | — | — | — | 下载中 16:58 |
| `XUKmvcu9sss` | ❌ | — | — | — | — | — |
| `Ft5Xg-Wv52U` | ❌ | — | — | — | — | — |

预期完成时间：loop 起点 +90~120 min（5 × ASR small @ ~10-15 min + 4 × 下载 @ ~2 min + 5 × 后处理 @ ~3 min）

### 4. store.db 基线

- 工单开始时 SHA: `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27`（与 frozen `4a8e409b…` 不同；launchd 16:09 漂移已知）
- 工单结束 SHA: 待 `STORE_AFTER=` 输出

### 5. 红线遵守

- ✅ 零写 store.db（CC 未启动任何 pipeline 写动作）
- ✅ 零 shorts（5/5 全是 `streams` collection）
- ✅ 零第二路 whisper（CC 拒绝开新进程）
- ✅ 零 `rm` ASR lock/tmp

---

## 后续动作（CC 接续）

| 触发 | 动作 |
|------|------|
| `AGENT_EXPAND5_DONE` 出现 / zsh PID 22703 消失 / DB 出现 5 个 transcript_version | 写 `reviews/ASR_EXPAND5_REPORT_2026-08-25.md`；更新 INBOX=`WAIT_CURSOR`；commit + push |
| Cursor 派新工单（INBOX→DO） | 立刻切换 |

未做（让位 Cursor loop）：逐 ID 跑 asr-transcribe / import / analyze / validate / render / publish。

---

## Cursor 17:14 — 不要再等 Cursor

旧 loop PID 22703 **已死**（ffmpeg PATH）。现况：

- whisper **25239** 正在转 `7L9X75dL1Dg`（`.vtt.tmp` 在涨）
- 父 zsh **25206** 若仍在，会在 25239 结束后继续 for-loop
- 5/5 webm 已在盘上

执行 `reviews/ASR_EXPAND5_CC_TAKEOVER_2026-08-25.md`：有 pid 就等；25206 死了你接手；不要问用户、不要开第二路 whisper。