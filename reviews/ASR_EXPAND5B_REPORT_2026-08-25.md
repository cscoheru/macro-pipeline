# ASR Expand-5b Report (2026-08-25)

> **响应**：`reviews/ASR_EXPAND5B_KICKOFF_2026-08-25.md`  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：0（用户禁止 DeepSeek）  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s | segs | VTT bytes | tv | render |
|----------|-----------:|-----:|----------:|:--:|--------|
| `bJYsb-kFdvI` | 12878 | 7904 | 452643 | ok | 拒（无 analyze） |
| `5fsVqcDBFic` | 6360 | 3139 | 203640 | ok | 拒（无 analyze） |
| `3UamnjBEm4E` | 10256 | 5333 | 333178 | ok | 拒（无 analyze） |
| `vWBT_3DaCu8` | 10097 | 4966 | 319340 | ok | 拒（无 analyze） |
| `A5axQwdZchk` | 11028 | 6914 | 392848 | ok | 拒（无 analyze） |

**5/5 `transcript_version` ok。** accepted claims 0（未 analyze）。零 shorts。未重转 WPS/试点/扩 5 ID。

## 抽检（未贴正文）

五支均为 `streams`；VTT 均 >32B 且落盘；import `status=success`。未做耳机听音。**GO** 入库。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（5/5） |
| analyze / DeepSeek | PASS（0 次） |
| shorts | PASS |
| store.db | PASS：仍 `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27` |
| 报告无转写正文 | PASS |
| render | DEFER：`render --from-db` 需要 analyze；按工单禁止 DeepSeek |
| publish | 既有 video 48 页 republish，0 failed；本批 5 支无 rendered page |

`FAIL=5` 全部是 render skip，不是转写/入库失败。

## 交付

INBOX → 下一刀 ASR 再扩 5（零 DeepSeek）。
