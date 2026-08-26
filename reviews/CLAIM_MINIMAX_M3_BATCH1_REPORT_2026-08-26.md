# Claim MiniMax-M3 Batch1 Report (2026-08-26)

> **响应**：`reviews/CLAIM_MINIMAX_M3_BATCH1_KICKOFF_2026-08-26.md`  
> **provider**：minimax / `MiniMax-M3`  
> **DeepSeek**：0  
> **ASR**：0  
> **禁止**：转写正文、API key

## 结果

| video_id | analyze | validated | rejected | reject rules | render |
|----------|:-------:|----------:|---------:|--------------|:------:|
| `5-eCEBFw2lw` | success | 0 | 7 | R2×7 | rendered |
| `8GXfASgyo1A` | success | 0 | 0 | （无 candidate） | rendered |
| `IPOKcXRZfi4` | success | 4 | 4 | R2×4 | rendered |
| `bJYsb-kFdvI` | success | 0 | 5 | R2×5 | rendered |
| `5fsVqcDBFic` | success | 15 | 4 | R2×4 | rendered |

**5/5 analyze success。** accepted 合计 19（2/5 视频 ≥1）。拒因全是 **R2**（exact_quote 不在 segment）。`8GXfASgyo1A` 模型未产出 candidate。零 shorts。零 DeepSeek。

validate `status=partial` 时 CLI 退出码 3；loop 曾因此跳过 render，本交卷已补 render 4 页。

## 门禁

| 项 | 结果 |
|----|------|
| 仅 MiniMax-M3 | PASS |
| DeepSeek 0 | PASS |
| ASR 0 | PASS |
| shorts 0 | PASS |
| store.db | 本批前后相同 `b57ce29f95d897a166b2140716582ba430101a06791a7340a0d775936633436c`（相对 frozen 漂移，只记录） |
| 报告无转写/密钥 | PASS |

## 交付

INBOX=`WAIT_CURSOR`。余 streams 有 transcript、无 claim 约 37。
