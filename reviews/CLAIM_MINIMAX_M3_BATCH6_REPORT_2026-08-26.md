# Claim MiniMax-M3 Batch6 Report (2026-08-26)

> **响应**：`reviews/CLAIM_MINIMAX_M3_BATCH6_KICKOFF_2026-08-26.md`  
> **provider**：minimax / `MiniMax-M3`  
> **DeepSeek**：0  
> **ASR**：0  
> **禁止**：转写正文、API key

## 结果

| video_id | analyze | validated | rejected | reject rules | render |
|----------|:-------:|----------:|---------:|--------------|:------:|
| `H8H_pVRdkKo` | FAIL | — | — | `provider_error`（invalid JSON） | skipped |
| `IUMsA7FO7OU` | success | 2 | 6 | R2×6 | rendered |
| `KfneDkfwYqw` | success | 0 | 6 | R2×6 | rendered |
| `OSri3YbeNhQ` | success | 1 | 5 | R2×5 | rendered |
| `OT4ExP3IOU0` | success | 2 | 5 | R2×5 | rendered |

**4/5 analyze success。** accepted 合计 5。拒因全是 R2。零 shorts。零 DeepSeek。FAIL=1。

## 门禁

| 项 | 结果 |
|----|------|
| 仅 MiniMax-M3 | PASS |
| DeepSeek / ASR / shorts | PASS |
| store.db | 本批前后相同 `b57ce29f95d897a166b2140716582ba430101a06791a7340a0d775936633436c` |
| 报告无转写/密钥 | PASS |

## 交付

INBOX → 下一刀 batch7（首条补 `H8H_pVRdkKo`）。余 streams 无 claim 行（未 analyze）约 11。
