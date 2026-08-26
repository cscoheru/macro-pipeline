# ASR Expand-5j Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5J_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `8GXfASgyo1A` | 8917 | 6503 | 370578 | ok |

**1/1 `transcript_version` ok。** FAIL=0。accepted 0（未 analyze）。零 shorts。  
yt-dlp 从 `.webm.part` 续传成功。

## 抽检（未贴正文）

`streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。

## 门禁

| 项 | 结果 |
|----|------|
| 1/1 `transcript_version` | PASS |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `07d418dc6ec9958431b0f9946ed17a692a01a20c884f06dd44f785806af656b6` |
| 报告无转写正文 | PASS |

## 交付

streams ASR **50/50**，队列空。shorts 忽略。analyze/render 仍 DEFER（禁止 DeepSeek）。INBOX=`WAIT_USER`「队列空」。
