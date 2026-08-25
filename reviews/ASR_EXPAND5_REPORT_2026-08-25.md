# ASR Expand-5 Report (2026-08-25)

> **响应**：`reviews/ASR_EXPAND5_KICKOFF_2026-08-25.md` + 本地收尾  
> **转写**：faster-whisper `small` / CPU；入库 `wps_import/2026-08-25.1`  
> **analyze**：DeepSeek 5/5 已跑（用户叫停继续花费）；本收尾 **零** DeepSeek token  
> **禁止**：转写正文、完整 title

## 结果

| video_id | duration_s (VTT span) | segs | accepted | rejected | 抽检 |
|----------|----------------------:|-----:|---------:|---------:|------|
| `7L9X75dL1Dg` | 5581 | 3683 | 8 | 0 | 时间戳连续；1h–2h 窗 1310 cues；**GO** |
| `TFjqgua7jKk` | 8598 | 4109 | 5 | 3 | 同上 1727 cues；validate partial；**GO** |
| `Xp4GBvKBPww` | 10907 | 6008 | 0 | 8 | VTT 可用；**claims DEFER**（0 accepted） |
| `XUKmvcu9sss` | 7493 | 3007 | 6 | 2 | 1h–2h 1577 cues；**GO** |
| `Ft5Xg-Wv52U` | 6484 | 3318 | 6 | 2 | 1h–2h 1370 cues；**GO** |

**4/5 各 accepted≥1 → 入库+主张门禁 PASS。** `Xp4GBvKBPww` 不重跑模型。

未重转 WPS/试点六支。零 shorts analyze。

## 抽检方法（未贴正文）

VTT 时钟跨度；抽 **01:00–02:00** cue 数（直播 VTT 从 00:00 起，不用墙上 10:00）。未做耳机听音。

## 门禁

| 项 | 结果 |
|----|------|
| ≥4/5 `transcript_version` | PASS（5/5） |
| ≥3/5 accepted≥1 | PASS（4/5） |
| shorts | PASS |
| store.db | PASS：仍 `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27` |
| 报告无转写正文 | PASS |
| video publish | PASS：5 支均 `published`（全库 video 48，0 failed） |
| concept refresh | PASS：78 概念 render、publish 89、0 failed（本地，无 LLM） |

## 事故 / 花费

Cursor 父 loop 首次 analyze 无模型（`model=""`）。补跑 DeepSeek 5/5 成功后用户叫停继续花费。本收尾仅 render/publish。

## 交付

INBOX → `WAIT_USER`（队列空；禁止再 DeepSeek）。
