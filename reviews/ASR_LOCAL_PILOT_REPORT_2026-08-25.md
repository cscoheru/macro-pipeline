# ASR Local Pilot Report (2026-08-25)

> **响应**：`reviews/ASR_LOCAL_PILOT_KICKOFF_2026-08-25.md`  
> **转写**：faster-whisper `small` / CPU；入库 normalizer=`wps_import/2026-08-25.1`  
> **禁止**：转写正文、完整 title、音频路径以外的媒体内容

## 结果

| video_id | duration_s (VTT span) | segs | accepted | rejected | 抽检 |
|----------|----------------------:|-----:|---------:|---------:|------|
| `epg0aoUbPN4` | 8861 | 4247 | 7 | 0 | 可用；时间戳对齐；**GO** |
| `E9uJV2bwzjM` | 8696 | 3702 | 16 | 0 | 可用；时间戳对齐；**GO** |
| `jfXAn1dgkyw` | 9406 | 4712 | 7 | 9 | 可用（reject 偏高）；时间戳对齐；**GO**（试点仍 PASS） |

**3/3 各 accepted≥1 → 技术 PASS。** 建议扩量 streams `--limit 5`（非 shorts、非已有字幕）。

对照 WPS 三支（`Z1HWDoSaC5Q` / `-9qyfgyKkaU` / `ScbTzleF3Pc`）**未重转**（transcript `created_at` 仍为当日上午 WPS 导入）。

## 抽检方法（未贴正文）

每支看 VTT 时钟跨度 vs 约 2.4–2.6h 直播；抽 10:00–12:00 窗口 cue 数（43 / 65 / 48）。未做耳机听音；以「可抽取主张 + 时间戳不崩」为准。

## 门禁

| 项 | 结果 |
|----|------|
| 3 支 `transcript_version` ok | PASS |
| ≥2 视频 accepted≥1 | PASS（3/3） |
| shorts ASR/analyze | PASS（当日 shorts 仅历史 `caption_fetch`，无 analyze） |
| tests | PASS：`test_houchen_asr.py` 8；`test_cc_autopilot_inspect.py` 12；`test_import_transcript.py` 另计 |
| store.db | **WARN**：现 `0c0cfbc5…` ≠ 冻结 `4a8e409b…`（16:09 mtime；非本工单写入；未回滚） |
| 报告无转写正文 | PASS |

## 事故

并行第二路 `asr-transcribe` + `rm` lock/tmp。已加 flock、Autopilot hook 拒绝第二路与锁文件 clobber。

## 交付后

INBOX → `WAIT_CURSOR`。Autopilot：`reviews/CC_AUTOPILOT.md`。
