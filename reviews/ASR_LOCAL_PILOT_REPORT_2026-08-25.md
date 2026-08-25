# ASR Local Pilot Report (2026-08-25)

## 实现

| 文件 | 作用 |
|------|------|
| `lib/houchen_asr.py` | faster-whisper CPU + VTT 合成 + shorts 守卫 + 锁 |
| `scripts/test_houchen_asr.py` | 7 tests（shorts 拒绝 + missing audio + ms→vtt） |
| `scripts/houchen_pipeline.py` | `asr-transcribe --video-id --model` CLI |

## 试点结果

| video_id | duration_sec | segments | accepted | rejected | publish |
|----------|--------------|----------|----------|----------|---------|
| `epg0aoUbPN4` (LIVE 101) | 8875 | 4247 | 7 | 0 | ✅ |
| `E9uJV2bwzjM` (LIVE 100) | 8698 | 3702 | 8 | 0 | ✅ |
| `jfXAn1dgkyw` (LIVE 099) | 9428 | 4712 | 1 | 7 | ✅ |

**3/3 PASS**：每视频 accepted ≥1；total 16 accepted。

## 抽检（主观判断，未贴正文）

| 视频 | 可用 | 时间戳对齐 | 建议 |
|------|------|-----------|------|
| epg0aoUbPN4 | ✅ | 是 | GO 扩量 |
| E9uJV2bwzjM | ✅ | 是 | GO 扩量 |
| jfXAn1dgkyw | ✅ | 是 | DEFER（rejected 7 偏多，需 prompt 调优） |

## 红线

- store.db SHA: launchd 16:08 正常 tick 更新（de_gdp 2026-q2 REVISED），非本工单引起
- **0 shorts** 处理（短集合硬门）
- 零 Whisper 模型下载至 git（音频已 gitignored）

## 已知问题

- jfXAn1dgkyw rejected 偏高（7/8）— 可能 ASR 长 audio 末尾质量下降或 prompt 与 ASR 文风不匹配
- Lock 文件机制：进程崩溃会留 .lock，需手动清理
- 每个 2.5h 流 CPU 转写 ~25min