# ASR Expand-5c Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5C_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `2zyAnqllesM` | 10507 | 6036 | 369590 | ok |
| `19Xb-C7Rwkk` | 6699 | 3681 | 229744 | ok |
| `Gw1xjIQ2UhY` | 10067 | 6407 | 376882 | ok |
| `q0-y1To8dXE` | 10899 | 5779 | 358621 | ok |
| `eeMeb48BT5w` | 6229 | 3333 | 209166 | ok |

**5/5 `transcript_version` ok。** FAIL=0。accepted 0（未 analyze）。零 shorts。

## 抽检（未贴正文）

五支均为 `streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（5/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27` |
| 报告无转写正文 | PASS |

## 交付

INBOX → 下一刀 ASR 5d（零 DeepSeek）。余 streams 无 transcript 约 29。
