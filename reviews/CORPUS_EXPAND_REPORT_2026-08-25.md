# Corpus Expand Report (2026-08-25)

## A — 字幕 P1

pending=0, frozen=53, normalized=53, missing=76（terminal）

详见 `reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25-P1.md`

## B — 扩竖切（25 视频）

| 项 | 值 |
|----|-----|
| 候选池 | 38 视频 |
| 跳过 | f_jd_j3eEuE, mg_BuWqSL9A（已知问题）|
| 处理 | 25（上限）|
| analyze 失败 | 1 (6O8fWfJBnZs) |
| accepted=0 | 1 (6YMrnOSzNLU) |
| 成功 | 23 |
| **accepted claims** | **160** |
| publish | 39 video pages |

## C — Macro-bridge 人工 Review

| 项 | 值 |
|----|-----|
| queue size | 347 candidates |
| 试点 review | 20 candidates |
| reviewed=1 | 20/20 ✅ |
| evaluation (macro_bridge) | 20 ✅ |

### 代码（4 文件改动）

- `lib/macro_bridge.py`：+`review_queue` / `mark_reviewed` / `import_reviewed` / dedupe in `scan_all`
- `scripts/houchen_pipeline.py`：+`--review-queue` / `--mark-reviewed` / `--import-reviewed` CLI
- scan dedupe：同 (claim_id, macro_source, macro_series, macro_period) 不重复 INSERT
- 28 测试通过

### Decisions

`reviews/MACRO_BRIDGE_REVIEW_DECISIONS_2026-08-25.jsonl`（20 条，`confirm contextualizes`）

## 红线

- store.db SHA `4a8e409b…` ✅
- 不 whisper ✅
- 不弱化 validator ✅