# ASR Expand-5g Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5G_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `IUMsA7FO7OU` | 9238 | 5729 | 327544 | ok |
| `OT4ExP3IOU0` | 10185 | 5532 | 327060 | ok |
| `WT8ur6mDIc8` | 9032 | 4016 | 256469 | ok |
| `Bs358g3utqI` | 8891 | 4387 | 265214 | ok |
| `o1KevNmFggw` | 8956 | 3971 | 244035 | ok |

**5/5 `transcript_version` ok。** FAIL=0。accepted 0（未 analyze）。零 shorts。

## 抽检（未贴正文）

五支均为 `streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（5/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | WARN：开批 `0c0cfbc5…`，结束 `07d418dc6ec9958431b0f9946ed17a692a01a20c884f06dd44f785806af656b6`（mtime 09:07）。houchen import 不写该库；只记录，不修复 |
| 报告无转写正文 | PASS |

## 交付

INBOX → 下一刀 ASR 5h（零 DeepSeek）。余 streams 无 transcript 约 10。
