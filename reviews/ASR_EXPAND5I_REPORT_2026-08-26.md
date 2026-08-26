# ASR Expand-5i Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5I_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `d5GD60u0BNg` | 8804 | 3842 | 240370 | ok |
| `FpUouK8Rnqo` | 10851 | 5173 | 314720 | ok |
| `H8H_pVRdkKo` | 12196 | 6500 | 387194 | ok |
| `5-eCEBFw2lw` | 8104 | 6026 | 343363 | ok |
| `8GXfASgyo1A` | — | — | — | FAIL download（YouTube 中途断流，10 次重试后放弃；留有 `.webm.part`） |

**4/5 `transcript_version` ok。** FAIL=1（仅下载）。accepted 0（未 analyze）。零 shorts。

## 抽检（未贴正文）

四支出库均为 `streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。  
`8GXfASgyo1A` 无完整音频/VTT → 下一批补下（yt-dlp 可续传 `.part`）。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（4/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `07d418dc6ec9958431b0f9946ed17a692a01a20c884f06dd44f785806af656b6` |
| 报告无转写正文 | PASS |

## 交付

INBOX → 下一刀 ASR 5j（补 `8GXfASgyo1A`）。余 streams 无 transcript 1。shorts 忽略。
