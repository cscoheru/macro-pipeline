# ASR Expand-5d Report (2026-08-26)

> **响应**：`reviews/ASR_EXPAND5D_KICKOFF_2026-08-26.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv |
|----------|-----------:|-----:|----------:|:--:|
| `kZUwR4ORFH4` | — | — | — | FAIL download（YouTube 中途断流，10 次重试后放弃） |
| `Fc6p-EoSC3Q` | 10384 | 4951 | 316365 | ok |
| `WbsIKtNB4Mg` | 9391 | 4681 | 293048 | ok |
| `reTK61PfFic` | 9607 | 5943 | 343004 | ok |
| `uFUeIdHAFdM` | 10437 | 5211 | 322746 | ok |

**4/5 `transcript_version` ok。** FAIL=1（仅下载）。accepted 0（未 analyze）。零 shorts。

## 抽检（未贴正文）

四支出库均为 `streams`；VTT >32B；import `status=success`。未做耳机听音。**GO** 入库。  
`kZUwR4ORFH4` 无音频/VTT → 下一批补下。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（4/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27` |
| 报告无转写正文 | PASS |

## 交付

INBOX → 下一刀 ASR 5e（零 DeepSeek；首条补 `kZUwR4ORFH4`）。余 streams 无 transcript 约 25。
