# ASR Expand-5h Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5H_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `3JS7zk12EHw` | 10461 | 5543 | 334773 | ok |
| `QGMMf3A5JxQ` | 8190 | 3694 | 224449 | ok |
| `hM-3nZcTj3k` | 6656 | 3231 | 194882 | ok |
| `0Vu8Ip0OYoU` | 9494 | 3850 | 252093 | ok |
| `IPOKcXRZfi4` | 9222 | 4907 | 293064 | ok |

**5/5 `transcript_version` ok。** FAIL=0。accepted 0（未 analyze）。零 shorts。

## 抽检（未贴正文）

五支均为 `streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（5/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `07d418dc6ec9958431b0f9946ed17a692a01a20c884f06dd44f785806af656b6` |
| 报告无转写正文 | PASS |

## 交付

INBOX → 下一刀 ASR 5i（streams 最后 5 条，含 2 条 LIVE SPECIAL）。余 streams 无 transcript 5。
